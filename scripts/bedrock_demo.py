#!/usr/bin/env python3
"""
bedrock_demo.py — Phase 8.7 Claude Bedrock AI Integration Demo
===============================================================
Demonstrates all Bedrock AI advisor capabilities against the live 5G core:

  1. Query live Prometheus metrics
  2. Compute network health score (0-100) with per-slice breakdown
  3. Natural language Q&A against live metrics
  4. Simulate anomaly event → AI triage + SNS alert
  5. Capacity forecast with AI planning
  6. Predictive maintenance for all 14 NFs
  7. Generate post-incident report
  8. Print all results + confirm S3 saves

Usage:
  # From laptop (with kubectl port-forward):
  kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090 &
  python3 scripts/bedrock_demo.py

  # Or with custom Prometheus URL:
  PROMETHEUS_URL=http://localhost:9090 python3 scripts/bedrock_demo.py
"""

import os
import sys
import json
import time
import math
import urllib.request
import urllib.parse
import logging
from datetime import datetime, timezone

# Make sure automation/ is on the path when run from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'automation'))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bedrock-demo")

PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://localhost:9090"
)

# ── Helpers ────────────────────────────────────────────────────────────────────
def banner(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def pprint(obj, indent: int = 2):
    print(json.dumps(obj, indent=indent, default=str))

def prom_scalar(query: str, default: float = 0.0) -> float:
    url = f"{PROMETHEUS_URL}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception as e:
        log.debug(f"Prometheus query failed: {e}")
    return default

def get_live_metrics() -> dict:
    """Fetch live metrics from Prometheus (or return realistic defaults)."""
    cpu_upf = prom_scalar(
        'sum(rate(container_cpu_usage_seconds_total{namespace="open5gs",'
        'pod=~"upf.*",container="upf"}[1m])) * 100'
    )
    cpu_amf = prom_scalar(
        'sum(rate(container_cpu_usage_seconds_total{namespace="open5gs",'
        'pod=~"amf.*",container="amf"}[1m])) * 100'
    )
    replicas = prom_scalar(
        'kube_horizontalpodautoscaler_status_current_replicas{'
        'namespace="open5gs",horizontalpodautoscaler="upf-hpa"}'
    ) or 1.0
    restarts = prom_scalar(
        'sum(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~"upf.*"})'
    )

    # Use realistic defaults if Prometheus unreachable (sandbox / no cluster)
    if cpu_upf == 0.0:
        log.warning("Prometheus unreachable — using realistic demo metrics")
        cpu_upf, cpu_amf, replicas, restarts = 38.5, 12.3, 2.0, 0.0

    return {
        "cpu_upf_pct"   : round(cpu_upf,  2),
        "cpu_amf_pct"   : round(cpu_amf,  2),
        "upf_replicas"  : int(replicas),
        "pod_restarts"  : int(restarts),
        "anomaly_score" : 0.18,     # normal baseline
        "forecast_max_ues": 90.0,
        "uptime_pct"    : 99.97,
    }


# ── Demo steps ─────────────────────────────────────────────────────────────────
def run_demo():
    from bedrock_advisor import BedrockNetworkAdvisor, NetworkEvent

    advisor = BedrockNetworkAdvisor()
    start_ts = datetime.now(timezone.utc).isoformat()

    # ── Step 1: Live metrics ───────────────────────────────────────────────────
    banner("STEP 1 — Live 5G Core Metrics")
    metrics = get_live_metrics()
    print(f"  UPF CPU      : {metrics['cpu_upf_pct']:.1f}%")
    print(f"  AMF CPU      : {metrics['cpu_amf_pct']:.1f}%")
    print(f"  UPF replicas : {metrics['upf_replicas']}")
    print(f"  Pod restarts : {metrics['pod_restarts']}")
    print(f"  Anomaly score: {metrics['anomaly_score']}")

    # ── Step 2: Network health score ──────────────────────────────────────────
    banner("STEP 2 — Network Health Score (0-100)")
    health = advisor.get_network_health_score(metrics)
    print(f"  Overall score : {health['overall_score']}/100")
    print(f"  Grade         : {health['grade']}")
    print(f"  Status        : {health['status']}")
    print(f"  Slice scores:")
    for sl, sc in health["slice_scores"].items():
        bar = "█" * int(sc / 5)
        print(f"    {sl.upper():6s}: {sc:5.1f}  {bar}")
    print(f"\n  Component scores:")
    for comp, sc in health["component_scores"].items():
        print(f"    {comp:12s}: {sc:.1f}")
    print(f"\n  AI insight:\n  {health['ai_insight']}")

    # ── Step 3: Natural language Q&A ──────────────────────────────────────────
    banner("STEP 3 — Natural Language Network Query")
    questions = [
        "Is the UPF under stress right now and should we add more replicas?",
        "Which network slice is most at risk and why?",
    ]
    for q in questions:
        print(f"\n  Q: {q}")
        answer = advisor.query_network(q, metrics)
        # Wrap to 70 chars
        words = answer.split()
        line, lines = [], []
        for w in words:
            if len(" ".join(line + [w])) > 68:
                lines.append("  A: " + " ".join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            lines.append("  A: " + " ".join(line))
        print("\n".join(lines))

    # ── Step 4: Simulated anomaly event → Bedrock analysis ───────────────────
    banner("STEP 4 — Simulated Anomaly Event (score=0.82)")
    anomaly_metrics = dict(metrics, anomaly_score=0.82, cpu_upf_pct=78.4, upf_replicas=3)
    anomaly_event = NetworkEvent(
        event_type    = "anomaly",
        severity      = "critical",
        anomaly_score = 0.82,
        cpu_upf_pct   = 78.4,
        cpu_amf_pct   = anomaly_metrics["cpu_amf_pct"],
        upf_replicas  = 3,
        network_state = "STATE-3",
        forecast_max_ues = 187.0,
        pod_restarts  = 2,
        description   = "Simulated UPF overload: IsolationForest anomaly score 0.82 "
                        "during 5G traffic stress test",
    )
    print("  Invoking Bedrock anomaly analysis…")
    analysis = advisor.analyse_network_event(anomaly_event)
    print(f"\n  Root cause    : {analysis.get('root_cause','N/A')}")
    print(f"  Severity      : {analysis.get('severity_assessment')}")
    print(f"  Confidence    : {analysis.get('confidence', 0):.0%}")
    print(f"  Scale target  : {analysis.get('recommended_scale_target')}")
    print(f"\n  Immediate actions:")
    for i, a in enumerate(analysis.get("immediate_actions", []), 1):
        print(f"    {i}. {a}")
    print(f"\n  S3 report     : {analysis.get('s3_uri','N/A')}")

    # ── Step 5: Capacity forecast ─────────────────────────────────────────────
    banner("STEP 5 — AI Capacity Forecast (ARIMA + Bedrock)")
    # Simulate 12-step ARIMA forecast that peaks above threshold
    fc_data = [85, 98, 112, 131, 148, 162, 171, 165, 155, 142, 130, 118]
    hist_data = [
        {"cpu_upf_pct": v, "upf_replicas": 2, "timestamp": f"t-{6-i}"}
        for i, v in enumerate([34, 36, 38, 41, 45, 50])
    ]
    print(f"  ARIMA forecast: {fc_data}")
    print(f"  Peak predicted: {max(fc_data)} UEs (threshold=150)")
    print("  Invoking Bedrock capacity planning…")
    cap_plan = advisor.generate_capacity_forecast(hist_data, fc_data)
    print(f"\n  Recommendation: {cap_plan.get('recommendation','').upper()}")
    print(f"  Target replicas: {cap_plan.get('target_replicas')}")
    print(f"  Risk level    : {cap_plan.get('risk_level')}")
    print(f"  Pre-scale when: {cap_plan.get('pre_scale_window')}")
    print(f"  Reasoning     : {cap_plan.get('reasoning','N/A')}")
    print(f"  S3 report     : {cap_plan.get('s3_uri','N/A')}")

    # ── Step 6: Predictive maintenance ───────────────────────────────────────
    banner("STEP 6 — Predictive Maintenance (14 NFs)")
    nf_metrics = {
        "amf"  : {"cpu_pct": metrics["cpu_amf_pct"], "restarts": 0, "uptime_pct": 99.9,  "error_rate": 0.001},
        "smf"  : {"cpu_pct": 5.2,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "upf"  : {"cpu_pct": metrics["cpu_upf_pct"],  "restarts": int(metrics["pod_restarts"]),
                   "uptime_pct": 99.8, "error_rate": 0.003},
        "ausf" : {"cpu_pct": 2.1,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "udm"  : {"cpu_pct": 2.3,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "udr"  : {"cpu_pct": 1.8,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "nrf"  : {"cpu_pct": 3.1,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "pcf"  : {"cpu_pct": 2.7,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "nssf" : {"cpu_pct": 1.2,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "bsf"  : {"cpu_pct": 1.1,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "scp"  : {"cpu_pct": 1.5,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "gnb"  : {"cpu_pct": 4.5,  "restarts": 0, "uptime_pct": 99.8,  "error_rate": 0.001},
        "ue"   : {"cpu_pct": 0.5,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
        "webui": {"cpu_pct": 0.5,  "restarts": 0, "uptime_pct": 100.0, "error_rate": 0.0},
    }
    print("  Invoking Bedrock predictive maintenance…")
    pm = advisor.predict_maintenance(nf_metrics)
    print(f"\n  Fleet health  : {pm.get('overall_fleet_health')}")
    print(f"  Critical NFs  : {pm.get('critical_nfs', []) or 'none'}")
    print(f"  Next window   : {pm.get('next_maintenance_window')}")
    print(f"\n  NF Predictions:")
    print(f"  {'NF':8s}  {'Urgency':10s}  {'Action':12s}  {'Window':14s}")
    print(f"  {'-'*8}  {'-'*10}  {'-'*12}  {'-'*14}")
    for nf, p in pm.get("predictions", {}).items():
        print(
            f"  {nf:8s}  {p.get('maintenance_urgency','?'):10s}  "
            f"{p.get('recommended_action','?'):12s}  "
            f"{p.get('maintenance_window','?'):14s}"
        )
    print(f"\n  S3 report     : {pm.get('s3_uri','N/A')}")

    # ── Step 7: Post-incident report ──────────────────────────────────────────
    banner("STEP 7 — Post-Incident Report")
    end_ts = datetime.now(timezone.utc).isoformat()
    print("  Generating post-incident report for simulated anomaly…")
    pir = advisor.generate_post_incident_report({
        "incident_id"             : "INC-DEMO-8.7",
        "start_time"              : start_ts,
        "end_time"                : end_ts,
        "event_type"              : "anomaly",
        "severity"                : "critical",
        "root_cause_hypothesis"   : "UPF memory pressure under 5G stress test causing IsolationForest anomaly",
        "actions_taken"           : [
            "IsolationForest anomaly score 0.82 triggered at 78% UPF CPU",
            "UPF scaled from 2 → 3 replicas by closed-loop engine",
            "Bedrock AI triage identified UPF load spike as root cause",
            "Traffic normalised after 3 minutes",
        ],
        "metrics_at_onset"        : anomaly_metrics,
        "metrics_at_resolution"   : metrics,
        "affected_ues"            : 3,
        "bedrock_analyses"        : [analysis],
    })
    print(f"\n  Incident ID   : {pir.get('incident_id')}")
    print(f"  Duration      : {pir.get('duration_min')} minutes")
    print(f"  Executive summary:")
    summary_text = pir.get("executive_summary", "N/A")
    words = summary_text.split()
    line, lines = [], []
    for w in words:
        if len(" ".join(line + [w])) > 60:
            lines.append("    " + " ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append("    " + " ".join(line))
    print("\n".join(lines))
    print(f"\n  Recurrence    : {pir.get('recurrence_probability')}")
    print(f"  S3 report     : {pir.get('s3_uri','N/A')}")

    # ── Step 8: Daily summary ─────────────────────────────────────────────────
    banner("STEP 8 — Daily Operations Summary")
    stats = advisor.get_stats()
    daily = advisor.generate_daily_summary({
        "total_anomalies"       : 1,
        "max_cpu_upf"           : 78.4,
        "avg_cpu_upf"           : 38.5,
        "max_replicas"          : 3,
        "total_scale_events"    : 2,
        "total_ue_registrations": 3,
        "uptime_pct"            : 99.97,
        "bedrock_invocations"   : stats.get("invocations", 0),
        "sagemaker_invocations" : 0,
    })
    print(f"  Grade         : {daily.get('overall_grade')}")
    print(f"  Headline      : {daily.get('headline')}")
    print(f"  Capacity trend: {daily.get('capacity_trend')}")
    print(f"\n  Highlights:")
    for h in daily.get("highlights", []):
        print(f"    • {h}")
    if daily.get("concerns"):
        print(f"\n  Concerns:")
        for c in daily.get("concerns", []):
            print(f"    ⚠ {c}")
    print(f"\n  Tomorrow's focus:")
    for f in daily.get("tomorrow_focus", []):
        print(f"    → {f}")
    print(f"\n  AI contribution: {daily.get('ai_assist_value','N/A')}")
    print(f"\n  S3 report     : {daily.get('s3_uri','N/A')}")

    # ── Final summary ─────────────────────────────────────────────────────────
    banner("DEMO COMPLETE — Summary")
    final_stats = advisor.get_stats()
    print(f"  Bedrock invocations : {final_stats['invocations']}")
    print(f"  Bedrock failures    : {final_stats['failures']}")
    print(f"  S3 reports saved    : {final_stats['s3_saves']}")
    print(f"  SNS alerts sent     : {final_stats['sns_sent']}")
    print(f"\n  All reports in      : s3://5g-core-ml-models-749534910877/")
    print(f"    incidents/")
    print(f"    capacity-forecasts/")
    print(f"    predictive-alerts/")
    print(f"    post-incident-reports/")
    print(f"    daily-summaries/")
    print(f"\n  Check SNS email     : nigelkadzinga91@gmail.com")
    print()


if __name__ == "__main__":
    run_demo()
