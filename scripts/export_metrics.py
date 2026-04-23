#!/usr/bin/env python3
"""
export_metrics.py — Prometheus → CSV exporter for Open5GS Phase 4

Queries the Prometheus HTTP API at localhost:9090 for all key metrics over
the specified time range and writes per-metric CSVs to ~/5g-project/data/raw/.

Usage:
  python3 export_metrics.py [--start START] [--end END] [--step STEP]
  python3 export_metrics.py --start 2h  # relative: last 2 hours
  python3 export_metrics.py --start 2026-04-23T10:00:00 --end 2026-04-23T12:00:00

Output columns: timestamp, metric_name, pod_name, value, load_phase
"""

import argparse
import csv
import os
import sys
import time
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
PROMETHEUS_URL = "http://localhost:9090"
DATA_DIR = Path.home() / "5g-project" / "data" / "raw"
LOAD_PHASE_CSV = DATA_DIR / "load_phases.csv"
NAMESPACE = "open5gs"

# ---------------------------------------------------------------------------
# Metrics to export. Each entry: (metric_name_label, promql_expression, description)
METRICS = [
    (
        "cpu_usage_percent",
        f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{NAMESPACE}",container!="",container!="POD"}}[1m])) * 100',
        "CPU usage % per pod (1m rate of cpu_seconds_total)"
    ),
    (
        "memory_working_set_bytes",
        f'container_memory_working_set_bytes{{namespace="{NAMESPACE}",container!="",container!="POD"}}',
        "Memory working set bytes per pod"
    ),
    (
        "container_restarts_total",
        f'kube_pod_container_status_restarts_total{{namespace="{NAMESPACE}"}}',
        "Total container restarts per pod"
    ),
    (
        "upf_hpa_current_replicas",
        f'kube_horizontalpodautoscaler_status_current_replicas{{namespace="{NAMESPACE}",horizontalpodautoscaler="upf-hpa"}}',
        "UPF HPA current replica count"
    ),
    (
        "upf_hpa_desired_replicas",
        f'kube_horizontalpodautoscaler_status_desired_replicas{{namespace="{NAMESPACE}",horizontalpodautoscaler="upf-hpa"}}',
        "UPF HPA desired replica count"
    ),
    (
        "upf_gtp_in_packets",
        "fivegs_ep_n3_gtp_indatapktn3upf",
        "UPF N3 uplink GTP packet count (cumulative)"
    ),
    (
        "upf_gtp_out_packets",
        "fivegs_ep_n3_gtp_outdatapktn3upf",
        "UPF N3 downlink GTP packet count (cumulative)"
    ),
    (
        "upf_gtp_in_pps",
        "rate(fivegs_ep_n3_gtp_indatapktn3upf[1m])",
        "UPF N3 uplink packets/sec (1m rate)"
    ),
    (
        "upf_gtp_out_pps",
        "rate(fivegs_ep_n3_gtp_outdatapktn3upf[1m])",
        "UPF N3 downlink packets/sec (1m rate)"
    ),
    (
        "amf_gnb_count",
        "gnb",
        "Number of connected gNBs (AMF metric)"
    ),
    (
        "amf_ran_ue_count",
        "ran_ue",
        "Number of active RAN UEs (AMF metric)"
    ),
    (
        "amf_amf_ue_count",
        "amf_ue",
        "Number of AMF UE contexts (AMF metric)"
    ),
    (
        "smf_session_count",
        "smf_sessions",
        "Number of active SMF PDU sessions"
    ),
    (
        "pcf_am_policy_req_total",
        "fivegs_pcffunction_pa_policyamassoreq_total",
        "PCF AM policy association requests (cumulative)"
    ),
]

# ---------------------------------------------------------------------------

def parse_relative_time(s: str) -> float:
    """Parse '2h', '30m', '1d' into seconds-ago offset. Returns epoch float."""
    now = time.time()
    s = s.strip()
    if s.endswith("h"):
        return now - float(s[:-1]) * 3600
    if s.endswith("m"):
        return now - float(s[:-1]) * 60
    if s.endswith("d"):
        return now - float(s[:-1]) * 86400
    # Try ISO datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    raise ValueError(f"Cannot parse time: {s!r}")


def query_range(expr: str, start: float, end: float, step: str) -> list[dict]:
    """Call Prometheus /api/v1/query_range, return list of series dicts."""
    params = urllib.parse.urlencode({
        "query": expr,
        "start": start,
        "end": end,
        "step": step,
    })
    url = f"{PROMETHEUS_URL}/api/v1/query_range?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"  ERROR querying Prometheus: {e}", file=sys.stderr)
        return []
    if data.get("status") != "success":
        print(f"  Prometheus returned non-success: {data.get('error','')}", file=sys.stderr)
        return []
    return data["data"]["result"]


def load_phase_map(csv_path: Path) -> dict[float, str]:
    """Read load_phases.csv → {epoch_float: phase_label} for join."""
    phases = {}
    if not csv_path.exists():
        return phases
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        current_phase = "unknown"
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc).timestamp()
                current_phase = row.get("load_phase", "unknown")
                phases[ts] = current_phase
            except Exception:
                pass
    return phases


def infer_phase(ts: float, phase_map: dict) -> str:
    """Find the load phase active at timestamp ts (closest earlier entry)."""
    if not phase_map:
        return "unknown"
    earlier = [t for t in phase_map if t <= ts]
    if not earlier:
        return "pre_test"
    return phase_map[max(earlier)]


def extract_pod_name(labels: dict) -> str:
    """Best-effort pod name from Prometheus series labels."""
    for key in ("pod", "exported_pod", "instance"):
        if key in labels:
            return labels[key]
    return "unknown"


def write_metric_csv(metric_name: str, description: str, expr: str,
                     start: float, end: float, step: str,
                     phase_map: dict, out_dir: Path) -> int:
    """Query Prometheus and write CSV. Returns number of rows written."""
    print(f"  Exporting: {metric_name} ...", end=" ", flush=True)
    series = query_range(expr, start, end, step)
    if not series:
        print("no data")
        return 0

    out_path = out_dir / f"{metric_name}.csv"
    rows = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "metric_name", "pod_name", "value", "load_phase"])
        for s in series:
            pod = extract_pod_name(s.get("metric", {}))
            for ts_str, val_str in s.get("values", []):
                ts = float(ts_str)
                iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                phase = infer_phase(ts, phase_map)
                writer.writerow([iso_ts, metric_name, pod, val_str, phase])
                rows += 1

    print(f"{rows} rows → {out_path.name}")
    return rows


def validate_csv(out_dir: Path) -> None:
    """Check for NaN gaps > 30s in each CSV and report."""
    print("\nValidating CSVs for NaN gaps > 30s ...")
    for csv_path in sorted(out_dir.glob("*.csv")):
        if csv_path.name == "load_phases.csv":
            continue
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            continue

        # Group by pod
        pods: dict[str, list] = {}
        for row in rows:
            pod = row["pod_name"]
            pods.setdefault(pod, []).append(row)

        issues = []
        for pod, prows in pods.items():
            try:
                times = sorted(
                    datetime.fromisoformat(r["timestamp"]).timestamp()
                    for r in prows
                    if r["value"] not in ("NaN", "nan", "+Inf", "-Inf", "")
                )
            except Exception:
                continue
            for i in range(1, len(times)):
                gap = times[i] - times[i - 1]
                if gap > 30:
                    issues.append(f"  {pod}: gap={gap:.0f}s at {datetime.fromtimestamp(times[i], tz=timezone.utc).isoformat()}")

        status = "OK" if not issues else f"WARNING ({len(issues)} gaps)"
        print(f"  {csv_path.name}: {status}")
        for issue in issues[:3]:  # cap at 3 per metric
            print(issue)


def write_readme(out_dir: Path, metrics: list, start: float, end: float) -> None:
    readme = out_dir / "README.md"
    lines = [
        "# Open5GS Phase 4 — Raw Metrics",
        "",
        f"**Export time range**: {datetime.fromtimestamp(start, tz=timezone.utc).isoformat()} → {datetime.fromtimestamp(end, tz=timezone.utc).isoformat()}",
        "",
        "## CSV Column Descriptions",
        "",
        "| Column | Description |",
        "|--------|-------------|",
        "| `timestamp` | ISO-8601 UTC timestamp of the sample |",
        "| `metric_name` | Prometheus metric identifier (matches filename) |",
        "| `pod_name` | Kubernetes pod name the metric belongs to |",
        "| `value` | Numeric sample value (units depend on metric — see below) |",
        "| `load_phase` | Load test phase active at sample time (from `load_phases.csv`) |",
        "",
        "## Metric Descriptions",
        "",
        "| Metric | Units | Source |",
        "|--------|-------|--------|",
    ]
    for name, expr, desc in metrics:
        lines.append(f"| `{name}` | — | {desc} |")
    lines += [
        "",
        "## Load Phases",
        "",
        "| Phase | Duration | Description |",
        "|-------|----------|-------------|",
        "| `A_baseline` | 10 min | 2 parallel iperf3 streams — light load |",
        "| `B_moderate` | 15 min | 20 parallel streams — moderate load |",
        "| `C_high` | 15 min | 64 parallel streams — high load targeting UPF CPU >70% |",
        "| `D_recovery` | 10 min | Back to 2 streams — observe HPA scale-down |",
        "| `unknown` | — | Samples before load test started |",
        "",
        "## Files",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| `load_phases.csv` | Timestamped phase log from `load_generator.sh` |",
    ]
    for name, _, _ in metrics:
        lines.append(f"| `{name}.csv` | {name} time series |")

    readme.write_text("\n".join(lines) + "\n")
    print(f"\nREADME written: {readme}")


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export Prometheus metrics to CSV")
    parser.add_argument("--start", default="2h", help="Start time (e.g. '2h', '30m', ISO datetime)")
    parser.add_argument("--end", default="now", help="End time ('now' or ISO datetime)")
    parser.add_argument("--step", default="15s", help="Resolution step (default: 15s)")
    parser.add_argument("--out", default=str(DATA_DIR), help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = parse_relative_time(args.start)
    end = time.time() if args.end == "now" else parse_relative_time(args.end)

    print(f"Prometheus: {PROMETHEUS_URL}")
    print(f"Range: {datetime.fromtimestamp(start, tz=timezone.utc).isoformat()} → {datetime.fromtimestamp(end, tz=timezone.utc).isoformat()}")
    print(f"Step: {args.step}")
    print(f"Output: {out_dir}")
    print()

    phase_map = load_phase_map(LOAD_PHASE_CSV)
    if phase_map:
        print(f"Loaded {len(phase_map)} phase entries from {LOAD_PHASE_CSV}")
    else:
        print(f"No load_phases.csv found — load_phase column will be 'unknown'")
    print()

    total_rows = 0
    for metric_name, expr, description in METRICS:
        rows = write_metric_csv(metric_name, description, expr, start, end,
                                args.step, phase_map, out_dir)
        total_rows += rows

    print(f"\nTotal rows exported: {total_rows}")

    write_readme(out_dir, METRICS, start, end)
    validate_csv(out_dir)

    print("\nDone. Next steps:")
    print("  1. Open Grafana at localhost:3000 (admin / open5gs)")
    print("  2. Run: kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090")
    print("  3. Run: kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80")


if __name__ == "__main__":
    main()
