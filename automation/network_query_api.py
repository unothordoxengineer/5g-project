#!/usr/bin/env python3
"""
network_query_api.py — Phase 8.8: Natural Language 5G Network Query API
=========================================================================
Flask REST API that exposes live Prometheus metrics + Amazon Bedrock Claude
as a natural-language interface to the 5G core network.

Endpoints:
  GET  /                   — Interactive web UI
  GET  /health             — API liveness check
  GET  /status             — Network health score (0-100)
  GET  /slices             — Status of all 3 network slices (eMBB/mMTC/URLLC)
  GET  /metrics            — Current key metrics summary
  POST /ask                — Natural language query answered by Bedrock
  POST /simulate-anomaly   — Inject a test anomaly for demo purposes

Environment variables:
  PROMETHEUS_URL   default: http://prometheus-kube-prometheus-prometheus.monitoring:9090
  PORT             default: 8080
  NAMESPACE        default: open5gs
  BEDROCK_ENABLED  default: true
  BEDROCK_REGION   default: us-east-1
"""

import os
import json
import math
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from threading import Lock

from flask import Flask, request, jsonify, render_template_string, Response

# ── Configuration ─────────────────────────────────────────────────────────────
PROMETHEUS_URL = os.environ.get(
    "PROMETHEUS_URL",
    "http://prometheus-kube-prometheus-prometheus.monitoring:9090"
)
PORT       = int(os.environ.get("PORT", "8080"))
NAMESPACE  = os.environ.get("NAMESPACE", "open5gs")
DEBUG      = os.environ.get("DEBUG", "false").lower() == "true"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("network-query-api")

# ── Bedrock advisor (graceful import) ─────────────────────────────────────────
BEDROCK_ENABLED = os.environ.get("BEDROCK_ENABLED", "true").lower() == "true"
_advisor   = None
_BEDROCK_OK = False

if BEDROCK_ENABLED:
    try:
        from bedrock_advisor import get_advisor
        _advisor   = get_advisor()
        _BEDROCK_OK = True
        log.info("BedrockNetworkAdvisor loaded successfully")
    except Exception as _be:
        log.warning(f"bedrock_advisor unavailable ({_be}); AI answers disabled")

# ── Anomaly injection state ───────────────────────────────────────────────────
_anomaly_lock     = Lock()
_injected_anomaly = None   # dict or None

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ═══════════════════════════════════════════════════════════════════════════════
# Prometheus helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _prom_query(promql: str, default: float = 0.0) -> float:
    """Execute an instant PromQL query; return scalar value or default."""
    encoded = urllib.parse.quote(promql)
    url = f"{PROMETHEUS_URL}/api/v1/query?query={encoded}"
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read())
            results = data.get("data", {}).get("result", [])
            if results:
                v = results[0].get("value", [None, None])[1]
                if v is not None and str(v) not in ("NaN", "Inf", "-Inf"):
                    return float(v)
    except Exception as e:
        log.debug(f"Prometheus query failed ({promql[:40]}...): {e}")
    return default


def _prom_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{PROMETHEUS_URL}/-/ready", timeout=3):
            return True
    except Exception:
        return False


def _get_current_metrics() -> dict:
    """
    Collect current network metrics from Prometheus.
    Returns synthetic fallback values if Prometheus is unreachable,
    and overlays any injected anomaly data on top.
    """
    prom_up = _prom_reachable()

    if prom_up:
        # ── Live Prometheus metrics ──────────────────────────────────────────
        cpu_upf = _prom_query(
            f'avg(rate(container_cpu_usage_seconds_total'
            f'{{namespace="{NAMESPACE}",pod=~".*upf.*",container!="POD"}}[2m])) * 100'
        )
        cpu_amf = _prom_query(
            f'avg(rate(container_cpu_usage_seconds_total'
            f'{{namespace="{NAMESPACE}",pod=~".*amf.*",container!="POD"}}[2m])) * 100'
        )
        cpu_smf = _prom_query(
            f'avg(rate(container_cpu_usage_seconds_total'
            f'{{namespace="{NAMESPACE}",pod=~".*smf.*",container!="POD"}}[2m])) * 100'
        )
        upf_replicas = int(_prom_query(
            f'kube_deployment_status_replicas_ready'
            f'{{namespace="{NAMESPACE}",deployment=~".*upf.*"}}',
            default=1
        ))
        ue_count = int(_prom_query(
            f'kube_deployment_status_replicas_ready'
            f'{{namespace="{NAMESPACE}",deployment=~".*ue[^r].*"}}',
            default=0
        ))
        pods_ready = int(_prom_query(
            f'count(kube_pod_status_ready{{namespace="{NAMESPACE}",condition="true"}})',
            default=0
        ))
        pod_restarts = int(_prom_query(
            f'sum(increase(kube_pod_container_status_restarts_total'
            f'{{namespace="{NAMESPACE}",pod!=""}}[1h]))',
            default=0
        ))
        mem_upf_mb = _prom_query(
            f'avg(container_memory_working_set_bytes'
            f'{{namespace="{NAMESPACE}",pod=~".*upf.*",container!="POD"}}) / 1048576',
            default=0.0
        )
        gtp_bytes_total = _prom_query(
            f'sum(rate(container_network_transmit_bytes_total'
            f'{{namespace="{NAMESPACE}",pod=~".*upf.*"}}[5m]))',
            default=0.0
        )
    else:
        # ── Synthetic fallback (local dev / Prometheus unreachable) ──────────
        log.info("Prometheus unreachable — using synthetic metrics")
        cpu_upf      = 12.4
        cpu_amf      = 4.2
        cpu_smf      = 3.1
        upf_replicas = 1
        ue_count     = 3
        pods_ready   = 14
        pod_restarts = 0
        mem_upf_mb   = 84.0
        gtp_bytes_total = 1_024.0

    metrics = {
        "cpu_upf_pct":      round(cpu_upf, 2),
        "cpu_amf_pct":      round(cpu_amf, 2),
        "cpu_smf_pct":      round(cpu_smf, 2),
        "upf_replicas":     upf_replicas,
        "ue_count":         ue_count,
        "pods_ready":       pods_ready,
        "pod_restarts":     pod_restarts,
        "mem_upf_mb":       round(mem_upf_mb, 1),
        "gtp_throughput_bps": round(gtp_bytes_total * 8, 1),
        "anomaly_score":    0.0,
        "forecast_max_ues": 0.0,
        "uptime_pct":       100.0 if pods_ready >= 14 else max(0.0, pods_ready / 14 * 100),
        "prometheus_reachable": prom_up,
        "simulated":        not prom_up,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }

    # ── Overlay injected anomaly ─────────────────────────────────────────────
    with _anomaly_lock:
        if _injected_anomaly:
            metrics.update(_injected_anomaly)

    return metrics


def _get_slice_status(metrics: dict) -> dict:
    """
    Derive per-slice health from current metrics.
    In production this would use NSSF / slice-specific counters.
    """
    cpu_upf    = metrics.get("cpu_upf_pct", 0.0)
    anom_score = metrics.get("anomaly_score", 0.0)
    pods_ready = metrics.get("pods_ready", 14)
    ue_count   = metrics.get("ue_count", 0)
    simulated  = metrics.get("simulated", False)

    def _score(base):
        return round(max(0.0, min(100.0, base)), 1)

    embb_load  = _score(min(100, cpu_upf * 1.1))
    urllc_load = _score(min(100, cpu_upf * 0.9 + anom_score * 20))
    mmtc_load  = _score(min(100, cpu_upf * 0.4))

    def _status(load):
        if load < 40: return "healthy"
        if load < 70: return "moderate"
        if load < 85: return "degraded"
        return "critical"

    slices = {
        "embb": {
            "name": "eMBB",
            "sst": 1,
            "dnn": "internet",
            "ip_pool": "10.45.0.0/16",
            "ambr_dl_mbps": 100,
            "ambr_ul_mbps": 50,
            "current_ues": max(1, int(ue_count * 0.6)) if ue_count else (1 if not simulated else 5),
            "load_pct": embb_load,
            "status": _status(embb_load),
            "latency_p99_ms": round(1.3 + cpu_upf * 0.08, 2),
            "sla_met": cpu_upf < 80,
        },
        "mmtc": {
            "name": "mMTC",
            "sst": 2,
            "dnn": "iot",
            "ip_pool": "10.46.0.0/16",
            "ambr_dl_mbps": 1,
            "ambr_ul_mbps": 1,
            "current_ues": max(1, int(ue_count * 0.3)) if ue_count else (1 if not simulated else 2),
            "load_pct": mmtc_load,
            "status": _status(mmtc_load),
            "latency_p99_ms": round(1.4 + cpu_upf * 0.05, 2),
            "sla_met": True,
        },
        "urllc": {
            "name": "URLLC",
            "sst": 3,
            "dnn": "urllc",
            "ip_pool": "10.47.0.0/16",
            "ambr_dl_mbps": 10,
            "ambr_ul_mbps": 5,
            "current_ues": max(0, ue_count - max(1, int(ue_count * 0.9))) if ue_count else (1 if not simulated else 1),
            "load_pct": urllc_load,
            "status": _status(urllc_load),
            "latency_p99_ms": round(1.3 + cpu_upf * 0.06 + anom_score * 5, 2),
            "sla_met": (cpu_upf < 70 and anom_score < 0.5),
        },
    }
    return slices


# ═══════════════════════════════════════════════════════════════════════════════
# HTML Web UI
# ═══════════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>5G Network AI — Ask Your Network</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --navy:    #0d1b2a;
      --blue:    #1b4f8a;
      --accent:  #2d8cf0;
      --green:   #22c55e;
      --yellow:  #eab308;
      --red:     #ef4444;
      --surface: #112240;
      --card:    #1a2f4a;
      --border:  #2a4a6a;
      --text:    #ccd6f6;
      --muted:   #8892a4;
    }
    body { background: var(--navy); color: var(--text); font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; }

    /* ── Header ── */
    header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }
    header h1 { font-size: 20px; font-weight: 700; color: #fff; }
    header h1 span { color: var(--accent); }
    .header-meta { font-size: 12px; color: var(--muted); text-align: right; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; margin-left: 6px; }
    .badge-ok   { background: rgba(34,197,94,.15); color: var(--green); border: 1px solid rgba(34,197,94,.3); }
    .badge-warn { background: rgba(234,179,8,.15);  color: var(--yellow); border: 1px solid rgba(234,179,8,.3); }
    .badge-err  { background: rgba(239,68,68,.15);  color: var(--red);    border: 1px solid rgba(239,68,68,.3); }

    /* ── Layout ── */
    .main { display: grid; grid-template-columns: 320px 1fr; gap: 20px; padding: 24px 28px; max-width: 1400px; margin: 0 auto; }
    @media (max-width: 900px) { .main { grid-template-columns: 1fr; } }

    /* ── Cards ── */
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
    .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); margin-bottom: 14px; }
    .card h3 { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 10px; }

    /* ── Health Gauge ── */
    .gauge-wrap { display: flex; flex-direction: column; align-items: center; gap: 6px; margin-bottom: 12px; }
    .gauge-svg { width: 180px; height: 110px; }
    .gauge-score { font-size: 38px; font-weight: 800; }
    .gauge-label { font-size: 13px; color: var(--muted); }
    .gauge-grade { font-size: 18px; font-weight: 700; margin-top: 2px; }

    /* ── Slice cards ── */
    .slice-grid { display: flex; flex-direction: column; gap: 8px; }
    .slice-item { background: rgba(255,255,255,.04); border-radius: 7px; padding: 10px 12px; border-left: 3px solid var(--accent); }
    .slice-item.healthy  { border-color: var(--green);  }
    .slice-item.moderate { border-color: var(--yellow); }
    .slice-item.degraded { border-color: #f97316; }
    .slice-item.critical { border-color: var(--red);   }
    .slice-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
    .slice-name { font-weight: 700; font-size: 14px; }
    .slice-stats { font-size: 11px; color: var(--muted); display: flex; gap: 12px; }
    .bar { height: 4px; border-radius: 2px; background: rgba(255,255,255,.1); margin-top: 6px; }
    .bar-fill { height: 4px; border-radius: 2px; transition: width .4s; }
    .bar-fill.green  { background: var(--green); }
    .bar-fill.yellow { background: var(--yellow); }
    .bar-fill.orange { background: #f97316; }
    .bar-fill.red    { background: var(--red); }

    /* ── Metrics grid ── */
    .metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric-box { background: rgba(255,255,255,.04); border-radius: 7px; padding: 10px 12px; }
    .metric-val { font-size: 22px; font-weight: 700; color: #fff; }
    .metric-lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }

    /* ── Right column ── */
    .right-col { display: flex; flex-direction: column; gap: 20px; }

    /* ── Ask box ── */
    .ask-card { flex-shrink: 0; }
    .ask-card h3 { font-size: 22px; font-weight: 800; color: #fff; margin-bottom: 6px; }
    .ask-card p  { font-size: 13px; color: var(--muted); margin-bottom: 16px; }
    .input-row { display: flex; gap: 10px; }
    .ask-input { flex: 1; background: rgba(255,255,255,.06); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; color: #fff; font-size: 14px; outline: none; transition: border .2s; }
    .ask-input:focus { border-color: var(--accent); }
    .ask-btn { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 12px 22px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background .2s; white-space: nowrap; }
    .ask-btn:hover { background: #1a7ae0; }
    .ask-btn:disabled { background: #2a4a6a; cursor: not-allowed; }

    /* ── Example questions ── */
    .examples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .example-btn { background: rgba(45,140,240,.12); border: 1px solid rgba(45,140,240,.3); color: var(--accent); padding: 6px 14px; border-radius: 20px; font-size: 12px; cursor: pointer; transition: background .2s; }
    .example-btn:hover { background: rgba(45,140,240,.25); }

    /* ── Answer box ── */
    .answer-card { flex: 1; min-height: 0; }
    .answer-state-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; color: var(--muted); text-align: center; gap: 10px; min-height: 200px; }
    .answer-icon { font-size: 40px; }
    .answer-text { background: rgba(255,255,255,.04); border-radius: 8px; padding: 18px; font-size: 15px; line-height: 1.7; white-space: pre-wrap; color: var(--text); min-height: 80px; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid rgba(45,140,240,.3); border-top-color: var(--accent); border-radius: 50%; animation: spin .7s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Metrics used accordion ── */
    .metrics-used { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; }
    .metrics-used summary { cursor: pointer; font-size: 12px; color: var(--muted); user-select: none; list-style: none; display: flex; align-items: center; gap: 6px; }
    .metrics-used summary::before { content: "▶"; font-size: 9px; transition: transform .2s; }
    details[open] .metrics-used summary::before { transform: rotate(90deg); }
    .metrics-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 10px; }
    .metrics-table td { padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,.05); color: var(--muted); }
    .metrics-table td:first-child { color: var(--text); font-family: monospace; }
    .metrics-table td:last-child { text-align: right; color: #fff; font-family: monospace; }

    /* ── Simulate anomaly ── */
    .sim-btn { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.3); color: var(--red); padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; transition: background .2s; }
    .sim-btn:hover { background: rgba(239,68,68,.25); }
    .sim-notice { display: none; font-size: 11px; color: var(--red); margin-top: 6px; }
    .sim-notice.show { display: block; }

    /* ── Status bar ── */
    .status-bar { font-size: 11px; color: var(--muted); margin-top: 4px; }
    .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 4px; }
    .dot-green  { background: var(--green); }
    .dot-yellow { background: var(--yellow); }
    .dot-red    { background: var(--red); }
  </style>
</head>
<body>

<header>
  <h1>5G Network <span>AI Operations</span></h1>
  <div class="header-meta">
    <div>Open5GS v2.7.2 · EKS 1.30 · Bedrock Claude</div>
    <div id="hdr-status"><span class="dot dot-yellow"></span>Connecting…</div>
  </div>
</header>

<div class="main">
  <!-- ── Left sidebar ── -->
  <aside>
    <!-- Health gauge card -->
    <div class="card" style="margin-bottom:16px">
      <h2>Network Health</h2>
      <div class="gauge-wrap">
        <svg class="gauge-svg" viewBox="0 0 180 110">
          <defs>
            <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%"   stop-color="#ef4444"/>
              <stop offset="50%"  stop-color="#eab308"/>
              <stop offset="100%" stop-color="#22c55e"/>
            </linearGradient>
          </defs>
          <!-- Track -->
          <path d="M20,100 A70,70 0 0,1 160,100" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="14" stroke-linecap="round"/>
          <!-- Fill arc (length = 220 = total arc) -->
          <path id="gauge-arc" d="M20,100 A70,70 0 0,1 160,100" fill="none" stroke="url(#gaugeGrad)" stroke-width="14" stroke-linecap="round"
                stroke-dasharray="220 220" stroke-dashoffset="220"/>
          <!-- Needle -->
          <circle id="gauge-needle" cx="20" cy="100" r="7" fill="white" filter="drop-shadow(0 0 3px rgba(0,0,0,.5))"/>
        </svg>
        <div class="gauge-score" id="g-score" style="color:#22c55e">—</div>
        <div class="gauge-grade" id="g-grade" style="color:#22c55e">—</div>
        <div class="gauge-label" id="g-status">Loading…</div>
      </div>
      <div style="margin-top:10px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
        <button class="sim-btn" onclick="simulateAnomaly()">⚡ Simulate Anomaly</button>
        <button class="sim-btn" style="color:var(--muted);border-color:var(--border)" onclick="clearAnomaly()">✕ Clear</button>
      </div>
      <div class="sim-notice" id="sim-notice">⚠ Anomaly injected — metrics are simulated</div>
      <div class="status-bar" style="margin-top:10px">
        <span class="dot" id="prom-dot" style="background:var(--muted)"></span>
        <span id="prom-status">Checking Prometheus…</span>
      </div>
    </div>

    <!-- Slice status -->
    <div class="card" style="margin-bottom:16px">
      <h2>Network Slices</h2>
      <div class="slice-grid" id="slice-grid">
        <div style="color:var(--muted);font-size:12px">Loading slice status…</div>
      </div>
    </div>

    <!-- Key metrics -->
    <div class="card">
      <h2>Live Metrics</h2>
      <div class="metrics-grid" id="metrics-grid">
        <div style="color:var(--muted);font-size:12px;grid-column:span 2">Loading…</div>
      </div>
    </div>
  </aside>

  <!-- ── Right column ── -->
  <section class="right-col">
    <!-- Ask card -->
    <div class="card ask-card">
      <h3>Ask Your Network</h3>
      <p>Ask any question about your 5G core in plain English. Claude will analyse live metrics and answer.</p>
      <div class="input-row">
        <input class="ask-input" id="q-input" type="text" placeholder="Why is UPF CPU high? Is the URLLC SLA being met?"
               onkeydown="if(event.key==='Enter')askNetwork()"/>
        <button class="ask-btn" id="ask-btn" onclick="askNetwork()">Ask →</button>
      </div>
      <div class="examples">
        <button class="example-btn" onclick="setQ(this)">What is the current network health?</button>
        <button class="example-btn" onclick="setQ(this)">Which slice has the highest load?</button>
        <button class="example-btn" onclick="setQ(this)">Should I scale up UPF replicas?</button>
        <button class="example-btn" onclick="setQ(this)">What happened in the last 30 minutes?</button>
        <button class="example-btn" onclick="setQ(this)">Is the URLLC slice meeting its latency SLA?</button>
        <button class="example-btn" onclick="setQ(this)">How does current CPU compare to the autoscaling threshold?</button>
      </div>
    </div>

    <!-- Answer card -->
    <div class="card answer-card">
      <h2>AI Response</h2>
      <div id="answer-area">
        <div class="answer-state-empty">
          <div class="answer-icon">🤖</div>
          <div>Ask a question above to get an AI-powered analysis of your 5G network.</div>
          <div style="font-size:12px">Powered by Amazon Bedrock · Claude Sonnet 4.6 → Haiku 4.5 → Nova Lite → Nova Micro</div>
        </div>
      </div>
      <div id="metrics-used-area" style="display:none">
        <details>
          <summary class="metrics-used"><span>Metrics used for this answer</span></summary>
          <table class="metrics-table" id="metrics-used-table"></table>
        </details>
      </div>
      <div id="ts-area" style="font-size:11px;color:var(--muted);margin-top:10px;display:none"></div>
    </div>
  </section>
</div>

<script>
// ── Gauge animation ──────────────────────────────────────────────────────────
function setGauge(score, grade, status) {
  const arc    = document.getElementById('gauge-arc');
  const needle = document.getElementById('gauge-needle');
  const total  = 220;  // total arc length
  const filled = total * (score / 100);
  arc.setAttribute('stroke-dashoffset', String(total - filled));

  // Needle position along the arc (semicircle from 180° to 0°)
  const angle = Math.PI - (score / 100) * Math.PI;
  const cx    = 90 + 70 * Math.cos(angle);
  const cy    = 100 - 70 * Math.sin(angle);
  needle.setAttribute('cx', cx.toFixed(1));
  needle.setAttribute('cy', cy.toFixed(1));

  const c = score >= 90 ? '#22c55e' : score >= 75 ? '#86efac' : score >= 50 ? '#eab308' : '#ef4444';
  document.getElementById('g-score').textContent = Math.round(score);
  document.getElementById('g-score').style.color  = c;
  document.getElementById('g-grade').textContent  = grade;
  document.getElementById('g-grade').style.color  = c;
  document.getElementById('g-status').textContent = status.toUpperCase();
}

// ── Slice render ─────────────────────────────────────────────────────────────
function renderSlices(slices) {
  const grid = document.getElementById('slice-grid');
  grid.innerHTML = '';
  for (const [key, s] of Object.entries(slices)) {
    const barColor = s.load_pct < 40 ? 'green' : s.load_pct < 70 ? 'yellow' : s.load_pct < 85 ? 'orange' : 'red';
    const sla = s.sla_met ? '<span style="color:var(--green)">✓ SLA</span>' : '<span style="color:var(--red)">✗ SLA breach</span>';
    grid.innerHTML += `
      <div class="slice-item ${s.status}">
        <div class="slice-header">
          <span class="slice-name">${s.name}</span>
          <span class="badge badge-ok" style="font-size:10px">${s.status}</span>
        </div>
        <div class="slice-stats">
          <span>SST ${s.sst}</span>
          <span>${s.current_ues} UE${s.current_ues!==1?'s':''}</span>
          <span>${s.latency_p99_ms}ms p99</span>
          ${sla}
        </div>
        <div class="bar"><div class="bar-fill ${barColor}" style="width:${s.load_pct}%"></div></div>
      </div>`;
  }
}

// ── Metrics render ───────────────────────────────────────────────────────────
function renderMetrics(m) {
  const g = document.getElementById('metrics-grid');
  const fmt = (v, unit='') => `${typeof v === 'number' ? v.toFixed(v<10?1:0) : v}${unit}`;
  g.innerHTML = `
    <div class="metric-box"><div class="metric-val" style="color:${m.cpu_upf_pct>70?'#ef4444':'#22c55e'}">${fmt(m.cpu_upf_pct,'%')}</div><div class="metric-lbl">UPF CPU</div></div>
    <div class="metric-box"><div class="metric-val">${fmt(m.cpu_amf_pct,'%')}</div><div class="metric-lbl">AMF CPU</div></div>
    <div class="metric-box"><div class="metric-val" style="color:#2d8cf0">${m.upf_replicas}</div><div class="metric-lbl">UPF Replicas</div></div>
    <div class="metric-box"><div class="metric-val">${m.pods_ready}/14</div><div class="metric-lbl">Pods Ready</div></div>
    <div class="metric-box"><div class="metric-val" style="color:${m.pod_restarts>0?'#eab308':'#22c55e'}">${m.pod_restarts}</div><div class="metric-lbl">Restarts (1h)</div></div>
    <div class="metric-box"><div class="metric-val">${fmt(m.mem_upf_mb,' MB')}</div><div class="metric-lbl">UPF Mem</div></div>`;
  // Prometheus indicator
  const dot    = document.getElementById('prom-dot');
  const status = document.getElementById('prom-status');
  if (m.prometheus_reachable) {
    dot.className = 'dot dot-green';
    status.textContent = 'Prometheus connected';
  } else {
    dot.className = 'dot dot-yellow';
    status.textContent = m.simulated ? 'Prometheus offline · synthetic data' : 'Prometheus offline';
  }
}

// ── Refresh status ───────────────────────────────────────────────────────────
async function refreshStatus() {
  try {
    const [statusR, slicesR, metricsR] = await Promise.all([
      fetch('/status').then(r=>r.json()),
      fetch('/slices').then(r=>r.json()),
      fetch('/metrics').then(r=>r.json()),
    ]);
    setGauge(statusR.health_score, statusR.grade, statusR.status);
    renderSlices(slicesR.slices);
    renderMetrics(metricsR.metrics);

    const hdrStatus = document.getElementById('hdr-status');
    const cls = statusR.status === 'healthy' ? 'badge-ok' : statusR.status === 'degraded' ? 'badge-warn' : 'badge-err';
    hdrStatus.innerHTML = `<span class="badge ${cls}">${statusR.status.toUpperCase()}</span> Score: ${statusR.health_score}`;
  } catch (e) {
    console.warn('Status refresh failed:', e);
    document.getElementById('hdr-status').innerHTML = '<span class="dot dot-red"></span>API Error';
  }
}

// ── Ask ───────────────────────────────────────────────────────────────────────
async function askNetwork() {
  const q = document.getElementById('q-input').value.trim();
  if (!q) return;
  const btn = document.getElementById('ask-btn');
  btn.disabled = true;

  document.getElementById('answer-area').innerHTML =
    `<div style="display:flex;align-items:center;gap:12px;padding:20px"><div class="spinner"></div><span style="color:var(--muted)">Querying Prometheus and asking Claude…</span></div>`;
  document.getElementById('metrics-used-area').style.display = 'none';
  document.getElementById('ts-area').style.display = 'none';

  try {
    const resp = await fetch('/ask', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question: q})
    });
    const data = await resp.json();

    if (data.error) {
      document.getElementById('answer-area').innerHTML =
        `<div class="answer-text" style="color:var(--red)">⚠ ${data.error}</div>`;
    } else {
      document.getElementById('answer-area').innerHTML =
        `<div class="answer-text">${escHtml(data.answer)}</div>`;

      // Metrics used
      if (data.metrics_used) {
        const tbl = document.getElementById('metrics-used-table');
        tbl.innerHTML = Object.entries(data.metrics_used)
          .map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
        document.getElementById('metrics-used-area').style.display = 'block';
      }
      // Timestamp
      const ts = document.getElementById('ts-area');
      ts.textContent = `Answered at ${data.timestamp} · Model: ${data.model_used || 'Bedrock cascade'}`;
      ts.style.display = 'block';
    }
    refreshStatus();
  } catch(e) {
    document.getElementById('answer-area').innerHTML =
      `<div class="answer-text" style="color:var(--red)">Request failed: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setQ(el) {
  document.getElementById('q-input').value = el.textContent;
  document.getElementById('q-input').focus();
}
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

async function simulateAnomaly() {
  await fetch('/simulate-anomaly', {method:'POST'});
  document.getElementById('sim-notice').classList.add('show');
  refreshStatus();
}
async function clearAnomaly() {
  await fetch('/simulate-anomaly', {method:'DELETE'});
  document.getElementById('sim-notice').classList.remove('show');
  refreshStatus();
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
refreshStatus();
setInterval(refreshStatus, 30000);
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    """Serve the interactive web UI."""
    return render_template_string(HTML_TEMPLATE)


@app.route("/health", methods=["GET"])
def health():
    """Liveness probe — always returns 200 while the process is alive."""
    return jsonify({
        "status":          "ok",
        "service":         "network-query-api",
        "version":         "1.0.0",
        "bedrock_enabled": _BEDROCK_OK,
        "prometheus_url":  PROMETHEUS_URL,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    })


@app.route("/status", methods=["GET"])
def status():
    """Return current network health score (0-100) with grade and component breakdown."""
    metrics = _get_current_metrics()

    if _advisor and _BEDROCK_OK:
        try:
            health = _advisor.get_network_health_score(metrics)
        except Exception as e:
            log.warning(f"get_network_health_score failed: {e}")
            health = _fallback_health_score(metrics)
    else:
        health = _fallback_health_score(metrics)

    health["metrics_snapshot"] = {
        k: metrics[k] for k in ("cpu_upf_pct", "cpu_amf_pct", "upf_replicas",
                                  "pods_ready", "pod_restarts", "simulated")
        if k in metrics
    }
    health["timestamp"] = datetime.now(timezone.utc).isoformat()
    return jsonify(health)


@app.route("/slices", methods=["GET"])
def slices():
    """Return status of all three network slices (eMBB/mMTC/URLLC)."""
    metrics = _get_current_metrics()
    slice_data = _get_slice_status(metrics)
    return jsonify({
        "slices":    slice_data,
        "simulated": metrics.get("simulated", False),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/metrics", methods=["GET"])
def metrics_endpoint():
    """Return current key metrics summary."""
    m = _get_current_metrics()
    return jsonify({
        "metrics":   m,
        "timestamp": m.get("timestamp", datetime.now(timezone.utc).isoformat()),
    })


@app.route("/metrics/prom", methods=["GET"])
def metrics_prom():
    """Prometheus text exposition format scraped by ServiceMonitor."""
    m = _get_current_metrics()
    lines = [
        "# HELP open5gs_anomaly_score IsolationForest anomaly score (0=normal, alert threshold=0.60)",
        "# TYPE open5gs_anomaly_score gauge",
        f"open5gs_anomaly_score {m.get('anomaly_score', 0.0):.6f}",
        "# HELP open5gs_ue_count Registered UEs in the 5G core",
        "# TYPE open5gs_ue_count gauge",
        f"open5gs_ue_count {float(m.get('ue_count', 0)):.0f}",
        "# HELP open5gs_upf_cpu_pct UPF CPU utilisation percentage",
        "# TYPE open5gs_upf_cpu_pct gauge",
        f"open5gs_upf_cpu_pct {m.get('cpu_upf_pct', 0.0):.4f}",
        "",
    ]
    return Response("\n".join(lines), content_type="text/plain; version=0.0.4; charset=utf-8")


@app.route("/ask", methods=["POST"])
def ask():
    """
    Natural language query endpoint.

    Request:  {"question": "Why is UPF CPU high?"}
    Response: {"answer": "...", "metrics_used": {...}, "timestamp": "..."}
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Missing 'question' in request body"}), 400

    metrics = _get_current_metrics()

    # Build a clean metrics dict for the advisor (no internal flags)
    advisor_metrics = {k: v for k, v in metrics.items()
                       if k not in ("timestamp", "prometheus_reachable", "simulated")}

    model_used = None
    if _advisor and _BEDROCK_OK:
        try:
            answer = _advisor.query_network(question, advisor_metrics)
            model_used = "Bedrock cascade (Claude Sonnet 4.6 → Haiku 4.5 → Nova Lite → Nova Micro)"
        except Exception as e:
            log.warning(f"query_network failed: {e}")
            answer = _local_answer(question, metrics)
            model_used = "local-fallback"
    else:
        answer = _local_answer(question, metrics)
        model_used = "local-fallback (Bedrock disabled)"

    return jsonify({
        "answer":      answer,
        "metrics_used": advisor_metrics,
        "model_used":  model_used,
        "question":    question,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


@app.route("/simulate-anomaly", methods=["POST", "DELETE"])
def simulate_anomaly():
    """
    POST  — inject a test anomaly into the metrics pipeline.
    DELETE — clear the injected anomaly.
    """
    global _injected_anomaly
    with _anomaly_lock:
        if request.method == "DELETE":
            _injected_anomaly = None
            return jsonify({"status": "cleared", "message": "Anomaly injection cleared"})

        # POST — inject
        _injected_anomaly = {
            "cpu_upf_pct":     87.5,
            "upf_replicas":    4,
            "cpu_amf_pct":     35.2,
            "anomaly_score":   0.82,
            "forecast_max_ues": 180.0,
            "pod_restarts":    1,
            "uptime_pct":      92.0,
            "simulated":       True,
        }
        log.info("Test anomaly injected via /simulate-anomaly")

    return jsonify({
        "status":  "injected",
        "message": "Test anomaly injected — cpu_upf=87.5%, anomaly_score=0.82, upf_replicas=4",
        "anomaly": _injected_anomaly,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _fallback_health_score(metrics: dict) -> dict:
    """
    Deterministic health score when Bedrock is unavailable.
    Mirrors the logic in BedrockNetworkAdvisor.get_network_health_score().
    """
    cpu_upf    = float(metrics.get("cpu_upf_pct", 0.0))
    cpu_amf    = float(metrics.get("cpu_amf_pct", 0.0))
    restarts   = int(metrics.get("pod_restarts", 0))
    anom_score = float(metrics.get("anomaly_score", 0.0))
    fc_max     = float(metrics.get("forecast_max_ues", 0.0))

    upf_score      = max(0.0, 100.0 - cpu_upf * 1.2 - restarts * 5)
    amf_score      = max(0.0, 100.0 - cpu_amf * 1.0)
    stability      = max(0.0, 100.0 - anom_score * 80)
    capacity       = max(0.0, 100.0 - max(0.0, fc_max - 100) * 0.5)

    overall = min(100.0, max(0.0,
        upf_score * 0.35 + amf_score * 0.20 + stability * 0.30 + capacity * 0.15
    ))

    if overall >= 90:   grade, status = "A", "healthy"
    elif overall >= 75: grade, status = "B", "healthy"
    elif overall >= 60: grade, status = "C", "degraded"
    elif overall >= 40: grade, status = "D", "degraded"
    else:               grade, status = "F", "critical"

    return {
        "overall_score": round(overall, 1),
        "health_score":  round(overall, 1),
        "grade":         grade,
        "status":        status,
        "component_scores": {
            "upf":         round(upf_score, 1),
            "amf":         round(amf_score, 1),
            "stability":   round(stability, 1),
            "capacity":    round(capacity, 1),
        },
        "slice_scores": {
            "embb":  round(min(100.0, upf_score * 0.6 + stability * 0.4), 1),
            "urllc": round(min(100.0, stability * 0.7 + upf_score * 0.3), 1),
            "mmtc":  round(min(100.0, amf_score * 0.5 + capacity * 0.5), 1),
        },
        "bedrock_used": False,
    }


def _local_answer(question: str, metrics: dict) -> str:
    """
    Rule-based fallback answer when Bedrock is unavailable.
    Covers the most common question patterns.
    """
    q   = question.lower()
    cpu = metrics.get("cpu_upf_pct", 0.0)
    rep = metrics.get("upf_replicas", 1)
    rst = metrics.get("pod_restarts", 0)
    pup = metrics.get("prometheus_reachable", False)

    note = " (Note: Bedrock AI is unavailable; this is a rule-based response.)"

    if any(w in q for w in ("health", "status", "overall", "fine", "ok")):
        score_data = _fallback_health_score(metrics)
        s = score_data["overall_score"]
        return (f"Current network health score is {s:.0f}/100 (grade: {score_data['grade']}, "
                f"status: {score_data['status']}). "
                f"UPF CPU is {cpu:.1f}%, AMF CPU is {metrics.get('cpu_amf_pct', 0):.1f}%, "
                f"with {rep} UPF replica(s) active and {rst} pod restart(s) in the last hour." + note)

    if any(w in q for w in ("cpu", "high", "load", "busy")):
        threshold = 70.0
        if cpu > threshold:
            return (f"UPF CPU is elevated at {cpu:.1f}% (above the {threshold}% HPA threshold). "
                    f"The HPA currently has {rep} replica(s) active and should scale if CPU remains high. "
                    f"This may indicate increased user plane traffic or an anomaly." + note)
        return (f"UPF CPU is {cpu:.1f}%, which is below the {threshold}% HPA threshold. "
                f"The system appears to be operating normally with {rep} active replica(s)." + note)

    if any(w in q for w in ("scale", "replica", "hpa")):
        if cpu > 60:
            return (f"With UPF CPU at {cpu:.1f}%, scaling up may be beneficial. "
                    f"The HPA threshold is 70% — currently running at {rep} replica(s). "
                    f"If load is expected to increase, proactively scaling to {min(rep+1, 5)} replicas is recommended." + note)
        return (f"UPF CPU is {cpu:.1f}%, which is comfortable. "
                f"Currently at {rep} replica(s) — no immediate scaling action needed. "
                f"The HPA will trigger automatically if CPU exceeds 70%." + note)

    if any(w in q for w in ("slice", "embb", "mmtc", "urllc", "latency", "sla")):
        slices = _get_slice_status(metrics)
        urllc  = slices["urllc"]
        return (f"eMBB slice status: {slices['embb']['status']} ({slices['embb']['load_pct']:.0f}% load, "
                f"p99 {slices['embb']['latency_p99_ms']}ms). "
                f"mMTC slice status: {slices['mmtc']['status']}. "
                f"URLLC slice status: {urllc['status']} (p99 {urllc['latency_p99_ms']}ms, "
                f"SLA {'met' if urllc['sla_met'] else 'BREACHED'})." + note)

    if any(w in q for w in ("30 minute", "last hour", "happened", "recent", "history")):
        return (f"In the last period: {rst} pod restart(s) recorded. "
                f"UPF CPU peaked around {cpu:.1f}%, with {rep} active replica(s). "
                f"Prometheus {'is connected and collecting live metrics' if pup else 'was unreachable — historical data unavailable'}." + note)

    # Generic fallback
    return (f"Current network snapshot: UPF CPU={cpu:.1f}%, AMF CPU={metrics.get('cpu_amf_pct',0):.1f}%, "
            f"UPF replicas={rep}, pods ready={metrics.get('pods_ready',0)}/14, "
            f"pod restarts (1h)={rst}. Prometheus reachable: {pup}." + note)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info(f"Starting Network Query API on port {PORT}")
    log.info(f"Prometheus URL : {PROMETHEUS_URL}")
    log.info(f"Bedrock enabled: {_BEDROCK_OK}")
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
