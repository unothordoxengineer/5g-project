#!/usr/bin/env python3
"""
closed_loop.py — Phase 8.6 Closed-Loop Automation Engine (SageMaker edition)
=============================================================================
Runs permanently in the cluster, polling every 30 s:

  1. Query Prometheus for current UPF CPU, replicas, latency
  2. Invoke SageMaker anomaly-detector-endpoint — if anomaly detected, scale UPF
  3. Invoke SageMaker traffic-forecaster-endpoint — if >150 UEs predicted, pre-scale to 3
  4. Invoke SageMaker state-classifier-endpoint  — log network state
  5. Write structured event log to /logs/closed_loop.log

Log format:
  [TIMESTAMP] DETECT: anomaly_score=0.72 → DECIDE: scale needed → ACT: UPF scaled to 3 replicas

Environment variables:
  PROMETHEUS_URL        default: http://prometheus-kube-prometheus-prometheus.monitoring:9090
  ANOMALY_ENDPOINT      default: anomaly-detector-endpoint
  FORECAST_ENDPOINT     default: traffic-forecaster-endpoint
  CLASSIFIER_ENDPOINT   default: state-classifier-endpoint
  AWS_REGION            default: us-east-1
  POLL_INTERVAL_S       default: 30
  LOG_FILE              default: /logs/closed_loop.log
  NAMESPACE             default: open5gs
  DRY_RUN               default: false  (set to "true" to log without acting)
"""

import os
import sys
import time
import math
import json
import logging
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# ── Configuration ─────────────────────────────────────────────────────────────
PROMETHEUS_URL      = os.environ.get("PROMETHEUS_URL",
    "http://prometheus-kube-prometheus-prometheus.monitoring:9090")
ANOMALY_ENDPOINT    = os.environ.get("ANOMALY_ENDPOINT",
    "anomaly-detector-endpoint")
FORECAST_ENDPOINT   = os.environ.get("FORECAST_ENDPOINT",
    "traffic-forecaster-endpoint")
CLASSIFIER_ENDPOINT = os.environ.get("CLASSIFIER_ENDPOINT",
    "state-classifier-endpoint")
AWS_REGION          = os.environ.get("AWS_REGION", "us-east-1")
POLL_INTERVAL       = int(os.environ.get("POLL_INTERVAL_S", "30"))
LOG_FILE            = os.environ.get("LOG_FILE", "/logs/closed_loop.log")
NAMESPACE           = os.environ.get("NAMESPACE", "open5gs")
DRY_RUN             = os.environ.get("DRY_RUN", "false").lower() == "true"

# Scaling thresholds
SCALE_MIN       = 1
SCALE_MAX       = 5
PROACTIVE_REPS  = 3    # replicas to set when forecast predicts high load
FORECAST_THRESH = 150  # UEs — if any of next-6h predictions exceed this, pre-scale

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else ".", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode='a'),
    ],
)
log = logging.getLogger("closed-loop")

# ── SageMaker runtime client ──────────────────────────────────────────────────
_smr = None

def get_smr():
    global _smr
    if _smr is None:
        _smr = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
    return _smr


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def event(detect: str, decide: str, act: str):
    """Write a structured event log entry."""
    line = f"[{now_str()}] DETECT: {detect} → DECIDE: {decide} → ACT: {act}"
    log.info(line)

# ── Prometheus query ──────────────────────────────────────────────────────────
def prom_scalar(query: str, default: float = float('nan')) -> float:
    """Run an instant PromQL query, return the scalar result."""
    url = f"{PROMETHEUS_URL}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception as e:
        log.debug(f"Prometheus query failed ({query[:60]}): {e}")
    return default

def get_current_metrics() -> dict:
    """Collect UPF CPU%, replica count, restarts from Prometheus."""
    cpu = prom_scalar(
        'sum(rate(container_cpu_usage_seconds_total{namespace="open5gs",'
        'pod=~"upf.*",container="upf"}[1m])) * 100'
    )
    replicas = prom_scalar(
        'kube_horizontalpodautoscaler_status_current_replicas{'
        'namespace="open5gs",horizontalpodautoscaler="upf-hpa"}'
    )
    restarts = prom_scalar(
        'sum(kube_pod_container_status_restarts_total{namespace="open5gs",'
        'pod=~"upf.*"})'
    )

    return {
        "cpu_upf_pct":  cpu      if not math.isnan(cpu)      else 0.0,
        "upf_replicas": replicas if not math.isnan(replicas) else 1.0,
        "pod_restarts": restarts if not math.isnan(restarts) else 0.0,
    }

# ── SageMaker invocations ─────────────────────────────────────────────────────
def sagemaker_invoke(endpoint_name: str, payload: dict) -> dict | None:
    """Invoke a SageMaker endpoint; return parsed JSON or None on error."""
    try:
        resp = get_smr().invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(payload).encode(),
        )
        return json.loads(resp["Body"].read())
    except ClientError as e:
        log.warning(f"SageMaker {endpoint_name} ClientError: {e.response['Error']['Message']}")
    except Exception as e:
        log.warning(f"SageMaker {endpoint_name} error: {e}")
    return None

# ── Kubectl actions ───────────────────────────────────────────────────────────
def get_current_replicas() -> int:
    try:
        out = subprocess.check_output(
            ["kubectl", "get", "deployment", "upf", "-n", NAMESPACE,
             "-o", "jsonpath={.spec.replicas}"],
            stderr=subprocess.DEVNULL, timeout=10
        )
        return int(out.strip())
    except Exception:
        return -1

def scale_upf(replicas: int) -> bool:
    replicas = max(SCALE_MIN, min(SCALE_MAX, replicas))
    if DRY_RUN:
        log.info(f"  [DRY-RUN] would scale UPF to {replicas} replicas")
        return True
    try:
        subprocess.run(
            ["kubectl", "scale", "deployment", "upf",
             "-n", NAMESPACE, f"--replicas={replicas}"],
            check=True, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except Exception as e:
        log.error(f"kubectl scale failed: {e}")
        return False

# ── Forecast history (rolling buffer for ARIMA input) ────────────────────────
_ue_history: list[float] = []
_MAX_HISTORY = 24   # keep last 24 samples (12 min at 30 s polling)

def push_ue_sample(ue_count: float):
    _ue_history.append(ue_count)
    if len(_ue_history) > _MAX_HISTORY:
        _ue_history.pop(0)

# ── Main control loop ─────────────────────────────────────────────────────────
def run_once():
    """Execute one control-loop iteration."""

    # 1 ── Collect metrics
    metrics = get_current_metrics()
    cpu     = metrics["cpu_upf_pct"]
    reps    = int(metrics["upf_replicas"])
    push_ue_sample(cpu)   # use CPU% as UE-count proxy

    # 2 ── Anomaly detection via SageMaker
    anom_result = sagemaker_invoke(ANOMALY_ENDPOINT, {
        "cpu_upf":      cpu,
        "upf_replicas": reps,
        "cpu_amf":      0.0,
    })

    if anom_result:
        score    = anom_result["anomaly_score"]
        is_anom  = anom_result["is_anomaly"]
        cur_reps = get_current_replicas()

        if is_anom:
            target_reps = min(SCALE_MAX, cur_reps + 1) if cur_reps > 0 else SCALE_MAX
            scale_upf(target_reps)
            event(
                detect=f"anomaly_score={score:.3f} cpu={cpu:.1f}% replicas={reps}",
                decide="anomaly detected — scale UPF up",
                act=f"UPF scaled to {target_reps} replicas" + (" (dry-run)" if DRY_RUN else ""),
            )
        else:
            event(
                detect=f"anomaly_score={score:.3f} cpu={cpu:.1f}% replicas={reps}",
                decide="normal — no action required",
                act="none",
            )
    else:
        event(
            detect=f"cpu={cpu:.1f}% replicas={reps} (SageMaker unreachable)",
            decide="cannot determine anomaly status",
            act="none — will retry",
        )

    # 3 ── Forecast-based pre-scaling (only if we have enough history)
    if len(_ue_history) >= 6:
        fc_result = sagemaker_invoke(FORECAST_ENDPOINT, {
            "sessions": list(_ue_history[-12:])
        })
        if fc_result:
            fc6      = fc_result["forecast_6h"]
            max_fc   = max(fc6) if fc6 else 0
            cur_reps = get_current_replicas()

            if max_fc > FORECAST_THRESH and cur_reps < PROACTIVE_REPS:
                scale_upf(PROACTIVE_REPS)
                event(
                    detect=f"forecast_max={max_fc:.0f} UEs (threshold={FORECAST_THRESH})",
                    decide=f"high load predicted — pre-scale to {PROACTIVE_REPS}",
                    act=f"UPF pre-scaled to {PROACTIVE_REPS} replicas" + (" (dry-run)" if DRY_RUN else ""),
                )
            else:
                event(
                    detect=f"forecast_max={max_fc:.0f} UEs (threshold={FORECAST_THRESH})",
                    decide="forecast within limits — no pre-scale needed",
                    act="none",
                )

    # 4 ── Network state classification
    cluster_result = sagemaker_invoke(CLASSIFIER_ENDPOINT, {
        "cpu_upf":      cpu,
        "cpu_amf":      0.0,
        "upf_replicas": reps,
        "ue_count":     0.0,
    })
    if cluster_result:
        state = cluster_result["cluster_name"]
        log.info(f"[{now_str()}] STATE: network_state={state} cpu={cpu:.1f}% replicas={reps}")


def main():
    log.info(f"[{now_str()}] Closed-loop engine starting (SageMaker mode)")
    log.info(f"  Prometheus          : {PROMETHEUS_URL}")
    log.info(f"  Anomaly endpoint    : {ANOMALY_ENDPOINT}")
    log.info(f"  Forecast endpoint   : {FORECAST_ENDPOINT}")
    log.info(f"  Classifier endpoint : {CLASSIFIER_ENDPOINT}")
    log.info(f"  Region              : {AWS_REGION}")
    log.info(f"  Poll every          : {POLL_INTERVAL}s")
    log.info(f"  Dry-run             : {DRY_RUN}")
    log.info(f"  Log file            : {LOG_FILE}")

    consecutive_errors = 0
    while True:
        try:
            run_once()
            consecutive_errors = 0
        except KeyboardInterrupt:
            log.info(f"[{now_str()}] Shut down by user")
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"[{now_str()}] Loop error (#{consecutive_errors}): {e}")
            if consecutive_errors >= 10:
                log.critical("Too many consecutive errors — exiting")
                sys.exit(1)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
