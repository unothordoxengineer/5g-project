#!/usr/bin/env python3
"""
closed_loop.py — Phase 8.7 Closed-Loop Automation Engine (SageMaker + Bedrock)
===============================================================================
Runs permanently in the cluster, polling every 30 s:

  1. Query Prometheus for current UPF CPU, replicas, latency
  2. Invoke SageMaker anomaly-detector-endpoint — if anomaly detected, scale UPF
  3. Invoke SageMaker traffic-forecaster-endpoint — if >150 UEs predicted, pre-scale to 3
  4. Invoke SageMaker state-classifier-endpoint  — log network state
  5. [Phase 8.7] Invoke Claude Bedrock for AI analysis when:
       • anomaly_score > 0.6  → analyse_network_event()
       • forecast max > 150   → generate_capacity_forecast()
       • network state changes → analyse_network_event()
       • every 6 hours        → generate_daily_summary()
       • hourly               → predict_maintenance()
       • anomaly resolves     → generate_post_incident_report()
  6. Write structured event log to /logs/closed_loop.log

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
  BEDROCK_ENABLED       default: true   (set to "false" to disable Bedrock integration)
  BEDROCK_REGION        default: us-east-1
  S3_BUCKET             default: 5g-core-ml-models-749534910877
  SNS_TOPIC_ARN         default: arn:aws:sns:us-east-1:749534910877:5g-core-network-alerts
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

# ── Phase 8.7: Bedrock advisor import ─────────────────────────────────────────
BEDROCK_ENABLED = os.environ.get("BEDROCK_ENABLED", "true").lower() == "true"

if BEDROCK_ENABLED:
    try:
        from bedrock_advisor import BedrockNetworkAdvisor, NetworkEvent, get_advisor
        _advisor = get_advisor()
        _BEDROCK_OK = True
    except ImportError as _be:
        _BEDROCK_OK = False
        logging.warning(f"bedrock_advisor not importable ({_be}); Bedrock disabled")
else:
    _BEDROCK_OK = False

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
ANOMALY_THRESH  = 0.6  # Bedrock trigger threshold

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
    cpu_amf = prom_scalar(
        'sum(rate(container_cpu_usage_seconds_total{namespace="open5gs",'
        'pod=~"amf.*",container="amf"}[1m])) * 100'
    )

    return {
        "cpu_upf_pct":  cpu      if not math.isnan(cpu)      else 0.0,
        "cpu_amf_pct":  cpu_amf  if not math.isnan(cpu_amf)  else 0.0,
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

# ── Phase 8.7: Bedrock state tracking ────────────────────────────────────────
_prev_network_state: str      = "STATE-0"
_prev_was_anomaly:   bool     = False
_anomaly_start_ts:   str      = ""
_anomaly_start_metrics: dict  = {}
_anomaly_actions_taken: list  = []
_last_daily_summary_hour: int = -1
_last_maintenance_hour:   int = -1
_poll_count:              int = 0

# Cumulative stats for daily summary
_daily_stats: dict = {
    "total_anomalies"       : 0,
    "max_cpu_upf"           : 0.0,
    "sum_cpu_upf"           : 0.0,
    "cpu_samples"           : 0,
    "max_replicas"          : 1,
    "total_scale_events"    : 0,
    "total_ue_registrations": 0,
    "bedrock_invocations"   : 0,
    "sagemaker_invocations" : 0,
}

# ── Bedrock helper wrappers ───────────────────────────────────────────────────
def bedrock_analyse(
    event_type: str, severity: str,
    cpu: float, cpu_amf: float, reps: int, anom_score: float,
    state: str, fc_max: float, restarts: int, description: str
) -> dict | None:
    """Trigger Bedrock analysis; log result; return analysis dict or None."""
    if not _BEDROCK_OK:
        return None
    try:
        net_event = NetworkEvent(
            event_type    = event_type,
            severity      = severity,
            anomaly_score = anom_score,
            cpu_upf_pct   = cpu,
            cpu_amf_pct   = cpu_amf,
            upf_replicas  = reps,
            network_state = state,
            forecast_max_ues = fc_max,
            pod_restarts  = int(restarts),
            description   = description,
        )
        analysis = _advisor.analyse_network_event(net_event)
        _daily_stats["bedrock_invocations"] += 1
        log.info(
            f"[{now_str()}] BEDROCK: severity={analysis.get('severity_assessment')} "
            f"confidence={analysis.get('confidence', 0):.2f} "
            f"s3={analysis.get('s3_uri', '')}"
        )
        return analysis
    except Exception as e:
        log.error(f"[BEDROCK] analyse_network_event failed: {e}")
        return None


def bedrock_health_score(metrics: dict) -> dict | None:
    if not _BEDROCK_OK:
        return None
    try:
        hs = _advisor.get_network_health_score(metrics)
        _daily_stats["bedrock_invocations"] += 1
        log.info(
            f"[{now_str()}] BEDROCK: health_score={hs['overall_score']}/100 "
            f"grade={hs['grade']} status={hs['status']} "
            f"eMBB={hs['slice_scores']['embb']} URLLC={hs['slice_scores']['urllc']} "
            f"mMTC={hs['slice_scores']['mmtc']}"
        )
        return hs
    except Exception as e:
        log.error(f"[BEDROCK] get_network_health_score failed: {e}")
        return None


# ── Main control loop ─────────────────────────────────────────────────────────
def run_once():
    """Execute one control-loop iteration."""
    global _prev_network_state, _prev_was_anomaly
    global _anomaly_start_ts, _anomaly_start_metrics, _anomaly_actions_taken
    global _last_daily_summary_hour, _last_maintenance_hour, _poll_count
    global _daily_stats

    _poll_count += 1
    now_hour = datetime.now(timezone.utc).hour

    # 1 ── Collect metrics
    metrics = get_current_metrics()
    cpu     = metrics["cpu_upf_pct"]
    cpu_amf = metrics["cpu_amf_pct"]
    reps    = int(metrics["upf_replicas"])
    restarts= metrics["pod_restarts"]
    push_ue_sample(cpu)   # use CPU% as UE-count proxy

    # Update daily stats
    _daily_stats["cpu_samples"] += 1
    _daily_stats["sum_cpu_upf"] += cpu
    _daily_stats["max_cpu_upf"]  = max(_daily_stats["max_cpu_upf"], cpu)
    _daily_stats["max_replicas"] = max(_daily_stats["max_replicas"], reps)

    # 2 ── Anomaly detection via SageMaker
    anom_result = sagemaker_invoke(ANOMALY_ENDPOINT, {
        "cpu_upf":      cpu,
        "upf_replicas": reps,
        "cpu_amf":      cpu_amf,
    })
    _daily_stats["sagemaker_invocations"] += 1

    anom_score  = 0.0
    is_anom     = False
    cur_reps    = get_current_replicas()
    scaled_to   = cur_reps

    if anom_result:
        anom_score = anom_result["anomaly_score"]
        is_anom    = anom_result["is_anomaly"]

        if is_anom:
            _daily_stats["total_anomalies"] += 1
            target_reps = min(SCALE_MAX, cur_reps + 1) if cur_reps > 0 else SCALE_MAX
            if scale_upf(target_reps):
                scaled_to = target_reps
                _daily_stats["total_scale_events"] += 1
                _anomaly_actions_taken.append(f"Scaled UPF to {target_reps} replicas at {now_str()}")
            event(
                detect=f"anomaly_score={anom_score:.3f} cpu={cpu:.1f}% replicas={reps}",
                decide="anomaly detected — scale UPF up",
                act=f"UPF scaled to {target_reps} replicas" + (" (dry-run)" if DRY_RUN else ""),
            )

            # ── Phase 8.7: Bedrock anomaly analysis ──────────────────────────
            if anom_score > ANOMALY_THRESH:
                if not _prev_was_anomaly:
                    # New anomaly started — record onset
                    _anomaly_start_ts      = now_str()
                    _anomaly_start_metrics = dict(metrics, anomaly_score=anom_score)
                    _anomaly_actions_taken = []

                severity = "critical" if anom_score > 0.8 else "high"
                bedrock_analyse(
                    event_type  = "anomaly",
                    severity    = severity,
                    cpu         = cpu,
                    cpu_amf     = cpu_amf,
                    reps        = reps,
                    anom_score  = anom_score,
                    state       = _prev_network_state,
                    fc_max      = 0.0,
                    restarts    = int(restarts),
                    description = f"IsolationForest anomaly score {anom_score:.4f} exceeds threshold {ANOMALY_THRESH}"
                )

            _prev_was_anomaly = True

        else:
            # ── Anomaly resolved — generate post-incident report ───────────
            if _prev_was_anomaly and _BEDROCK_OK and _anomaly_start_ts:
                try:
                    import hashlib
                    inc_id = "INC-" + hashlib.md5(_anomaly_start_ts.encode()).hexdigest()[:8].upper()
                    _advisor.generate_post_incident_report({
                        "incident_id"             : inc_id,
                        "start_time"              : _anomaly_start_ts,
                        "end_time"                : now_str(),
                        "event_type"              : "anomaly",
                        "severity"                : "high",
                        "root_cause_hypothesis"   : "IsolationForest anomaly detected, likely UPF load spike",
                        "actions_taken"           : _anomaly_actions_taken,
                        "metrics_at_onset"        : _anomaly_start_metrics,
                        "metrics_at_resolution"   : dict(metrics, anomaly_score=anom_score),
                        "affected_ues"            : 0,
                        "bedrock_analyses"        : [],
                    })
                    _daily_stats["bedrock_invocations"] += 1
                    log.info(f"[{now_str()}] BEDROCK: Post-incident report generated for {inc_id}")
                except Exception as e:
                    log.error(f"[BEDROCK] post_incident_report failed: {e}")
                _anomaly_start_ts      = ""
                _anomaly_actions_taken = []

            _prev_was_anomaly = False

            event(
                detect=f"anomaly_score={anom_score:.3f} cpu={cpu:.1f}% replicas={reps}",
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
    fc6 = []
    max_fc = 0.0
    if len(_ue_history) >= 6:
        fc_result = sagemaker_invoke(FORECAST_ENDPOINT, {
            "sessions": list(_ue_history[-12:])
        })
        _daily_stats["sagemaker_invocations"] += 1
        if fc_result:
            fc6    = fc_result["forecast_6h"]
            max_fc = max(fc6) if fc6 else 0

            if max_fc > FORECAST_THRESH and cur_reps < PROACTIVE_REPS:
                if scale_upf(PROACTIVE_REPS):
                    _daily_stats["total_scale_events"] += 1
                event(
                    detect=f"forecast_max={max_fc:.0f} UEs (threshold={FORECAST_THRESH})",
                    decide=f"high load predicted — pre-scale to {PROACTIVE_REPS}",
                    act=f"UPF pre-scaled to {PROACTIVE_REPS} replicas" + (" (dry-run)" if DRY_RUN else ""),
                )

                # ── Phase 8.7: Bedrock capacity forecast ─────────────────────
                if _BEDROCK_OK:
                    try:
                        hist = [
                            {"cpu_upf_pct": v, "upf_replicas": reps}
                            for v in _ue_history[-6:]
                        ]
                        cap_plan = _advisor.generate_capacity_forecast(hist, fc6)
                        _daily_stats["bedrock_invocations"] += 1
                        log.info(
                            f"[{now_str()}] BEDROCK: capacity_forecast "
                            f"rec={cap_plan.get('recommendation')} "
                            f"target={cap_plan.get('target_replicas')} "
                            f"s3={cap_plan.get('s3_uri','')}"
                        )
                    except Exception as e:
                        log.error(f"[BEDROCK] generate_capacity_forecast failed: {e}")
            else:
                event(
                    detect=f"forecast_max={max_fc:.0f} UEs (threshold={FORECAST_THRESH})",
                    decide="forecast within limits — no pre-scale needed",
                    act="none",
                )

    # 4 ── Network state classification
    network_state = _prev_network_state
    cluster_result = sagemaker_invoke(CLASSIFIER_ENDPOINT, {
        "cpu_upf":      cpu,
        "cpu_amf":      cpu_amf,
        "upf_replicas": reps,
        "ue_count":     0.0,
    })
    _daily_stats["sagemaker_invocations"] += 1
    if cluster_result:
        network_state = cluster_result["cluster_name"]
        log.info(f"[{now_str()}] STATE: network_state={network_state} cpu={cpu:.1f}% replicas={reps}")

    # ── Phase 8.7: Bedrock analysis on state change ───────────────────────────
    if network_state != _prev_network_state and _BEDROCK_OK:
        bedrock_analyse(
            event_type  = "state_change",
            severity    = "medium",
            cpu         = cpu,
            cpu_amf     = cpu_amf,
            reps        = reps,
            anom_score  = anom_score,
            state       = network_state,
            fc_max      = max_fc,
            restarts    = int(restarts),
            description = f"Network state changed: {_prev_network_state} → {network_state}"
        )
    _prev_network_state = network_state

    # 5 ── Phase 8.7: Health score every poll cycle ───────────────────────────
    hs_metrics = dict(metrics, anomaly_score=anom_score, forecast_max_ues=max_fc)
    bedrock_health_score(hs_metrics)

    # 6 ── Phase 8.7: Daily summary every 6 hours ─────────────────────────────
    if _BEDROCK_OK and (now_hour % 6 == 0) and (now_hour != _last_daily_summary_hour):
        _last_daily_summary_hour = now_hour
        try:
            samples = _daily_stats["cpu_samples"]
            summary_metrics = {
                "total_anomalies"       : _daily_stats["total_anomalies"],
                "max_cpu_upf"           : _daily_stats["max_cpu_upf"],
                "avg_cpu_upf"           : (_daily_stats["sum_cpu_upf"] / samples) if samples else 0.0,
                "max_replicas"          : _daily_stats["max_replicas"],
                "total_scale_events"    : _daily_stats["total_scale_events"],
                "total_ue_registrations": _daily_stats["total_ue_registrations"],
                "uptime_pct"            : 100.0,
                "bedrock_invocations"   : _daily_stats["bedrock_invocations"],
                "sagemaker_invocations" : _daily_stats["sagemaker_invocations"],
            }
            ds = _advisor.generate_daily_summary(summary_metrics)
            _daily_stats["bedrock_invocations"] += 1
            log.info(
                f"[{now_str()}] BEDROCK: daily_summary grade={ds.get('overall_grade')} "
                f"trend={ds.get('capacity_trend')} s3={ds.get('s3_uri','')}"
            )
        except Exception as e:
            log.error(f"[BEDROCK] generate_daily_summary failed: {e}")

    # 7 ── Phase 8.7: Predictive maintenance every hour ───────────────────────
    if _BEDROCK_OK and (now_hour != _last_maintenance_hour) and (_poll_count % 120 == 0 or _poll_count == 10):
        _last_maintenance_hour = now_hour
        try:
            nf_metrics = {
                "amf"  : {"cpu_pct": cpu_amf,  "restarts": int(restarts), "uptime_pct": 99.9, "error_rate": 0.001},
                "smf"  : {"cpu_pct": 5.0,       "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "upf"  : {"cpu_pct": cpu,        "restarts": int(restarts),"uptime_pct": 99.9, "error_rate": 0.002},
                "ausf" : {"cpu_pct": 2.0,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "udm"  : {"cpu_pct": 2.0,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "udr"  : {"cpu_pct": 1.5,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "nrf"  : {"cpu_pct": 3.0,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "pcf"  : {"cpu_pct": 2.5,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "nssf" : {"cpu_pct": 1.0,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "bsf"  : {"cpu_pct": 1.0,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "scp"  : {"cpu_pct": 1.5,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "gnb"  : {"cpu_pct": 4.0,        "restarts": 0,            "uptime_pct": 99.8, "error_rate": 0.001},
                "ue"   : {"cpu_pct": 0.5,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
                "webui": {"cpu_pct": 0.5,        "restarts": 0,            "uptime_pct": 100.0, "error_rate": 0.0},
            }
            pm = _advisor.predict_maintenance(nf_metrics)
            _daily_stats["bedrock_invocations"] += 1
            log.info(
                f"[{now_str()}] BEDROCK: predict_maintenance "
                f"fleet={pm.get('overall_fleet_health')} "
                f"critical={pm.get('critical_nfs', [])} "
                f"s3={pm.get('s3_uri','')}"
            )
        except Exception as e:
            log.error(f"[BEDROCK] predict_maintenance failed: {e}")


def main():
    log.info(f"[{now_str()}] Closed-loop engine starting (SageMaker + Bedrock mode)")
    log.info(f"  Prometheus          : {PROMETHEUS_URL}")
    log.info(f"  Anomaly endpoint    : {ANOMALY_ENDPOINT}")
    log.info(f"  Forecast endpoint   : {FORECAST_ENDPOINT}")
    log.info(f"  Classifier endpoint : {CLASSIFIER_ENDPOINT}")
    log.info(f"  Region              : {AWS_REGION}")
    log.info(f"  Poll every          : {POLL_INTERVAL}s")
    log.info(f"  Dry-run             : {DRY_RUN}")
    log.info(f"  Log file            : {LOG_FILE}")
    log.info(f"  Bedrock enabled     : {_BEDROCK_OK}")
    if _BEDROCK_OK:
        from bedrock_advisor import BEDROCK_PRIMARY_MODEL, BEDROCK_FALLBACK_MODEL, S3_BUCKET, SNS_TOPIC_ARN
        log.info(f"  Bedrock primary     : {BEDROCK_PRIMARY_MODEL}")
        log.info(f"  Bedrock fallback    : {BEDROCK_FALLBACK_MODEL}")
        log.info(f"  S3 bucket           : {S3_BUCKET}")
        log.info(f"  SNS topic           : {SNS_TOPIC_ARN}")

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
