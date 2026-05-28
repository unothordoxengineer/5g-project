#!/usr/bin/env python3
"""
bedrock_advisor.py — Phase 8.7 Claude Bedrock AI Network Operations Advisor
=============================================================================
Provides AI-powered analysis, forecasting, and recommendations for the 5G
core network using Amazon Bedrock (Claude models via IRSA — no static creds).

Features:
  • analyse_network_event()        — incident triage + root-cause analysis
  • generate_capacity_forecast()   — 6-hour proactive capacity planning
  • generate_daily_summary()       — end-of-day operations digest
  • query_network()                — natural-language Q&A against live metrics
  • get_network_health_score()     — 0-100 composite score with per-slice breakdown
  • predict_maintenance()          — predictive NF maintenance window scheduling
  • generate_post_incident_report()— structured markdown incident report → S3

All reports are saved to S3 and critical events are SNS-notified.

Configuration (environment variables):
  BEDROCK_REGION         default: us-east-1
  BEDROCK_PRIMARY_MODEL  default: anthropic.claude-sonnet-4-6
  BEDROCK_FALLBACK_MODEL default: anthropic.claude-haiku-4-5-20251001-v1:0
  S3_BUCKET              default: 5g-core-ml-models-749534910877
  SNS_TOPIC_ARN          default: arn:aws:sns:us-east-1:749534910877:5g-core-network-alerts
"""

import os
import sys
import json
import time
import logging
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

# ── Configuration ─────────────────────────────────────────────────────────────
BEDROCK_REGION         = os.environ.get("BEDROCK_REGION", "us-east-1")
BEDROCK_PRIMARY_MODEL  = os.environ.get("BEDROCK_PRIMARY_MODEL",
                                         "us.anthropic.claude-sonnet-4-6")
BEDROCK_FALLBACK_MODEL = os.environ.get("BEDROCK_FALLBACK_MODEL",
                                         "us.anthropic.claude-haiku-4-5-20251001-v1:0")
S3_BUCKET              = os.environ.get("S3_BUCKET",
                                         "5g-core-ml-models-749534910877")
SNS_TOPIC_ARN          = os.environ.get("SNS_TOPIC_ARN",
                                         "arn:aws:sns:us-east-1:749534910877:5g-core-network-alerts")

# 14 Network Functions tracked for predictive maintenance
NETWORK_FUNCTIONS = [
    "amf", "smf", "upf", "ausf", "udm", "udr",
    "nrf", "pcf", "nssf", "bsf", "scp", "gnb", "ue", "webui",
]

log = logging.getLogger("bedrock-advisor")


# ── Data model ─────────────────────────────────────────────────────────────────
@dataclass
class NetworkEvent:
    """Structured network event for Bedrock analysis."""
    event_type: str          # anomaly | state_change | forecast_alert | manual
    severity: str            # critical | high | medium | low | info
    timestamp: str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    anomaly_score: float     = 0.0
    cpu_upf_pct: float       = 0.0
    cpu_amf_pct: float       = 0.0
    upf_replicas: int        = 1
    ue_count: int            = 0
    network_state: str       = "STATE-0"
    forecast_max_ues: float  = 0.0
    pod_restarts: int        = 0
    description: str         = ""

    def to_context_str(self) -> str:
        return (
            f"Event type: {self.event_type}\n"
            f"Severity: {self.severity}\n"
            f"Timestamp: {self.timestamp}\n"
            f"Anomaly score: {self.anomaly_score:.4f}\n"
            f"UPF CPU: {self.cpu_upf_pct:.1f}%\n"
            f"AMF CPU: {self.cpu_amf_pct:.1f}%\n"
            f"UPF replicas: {self.upf_replicas}\n"
            f"UE count: {self.ue_count}\n"
            f"Network state: {self.network_state}\n"
            f"Forecast max UEs (6h): {self.forecast_max_ues:.0f}\n"
            f"Pod restarts: {self.pod_restarts}\n"
            f"Description: {self.description}"
        )


# ── Main advisor class ─────────────────────────────────────────────────────────
class BedrockNetworkAdvisor:
    """
    AI-powered network operations advisor using Amazon Bedrock Claude models.
    Uses IRSA for AWS credentials — no static keys needed.
    """

    def __init__(self):
        self._bedrock = None
        self._s3      = None
        self._sns     = None
        self._stats   = {"invocations": 0, "failures": 0, "s3_saves": 0, "sns_sent": 0}

    # ── AWS client helpers ─────────────────────────────────────────────────────
    def _get_bedrock(self):
        if self._bedrock is None:
            self._bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        return self._bedrock

    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=BEDROCK_REGION)
        return self._s3

    def _get_sns(self):
        if self._sns is None:
            self._sns = boto3.client("sns", region_name=BEDROCK_REGION)
        return self._sns

    # ── Core Bedrock invocation ────────────────────────────────────────────────
    def _invoke(self, prompt: str, system: str = "", max_tokens: int = 1500) -> str:
        """
        Invoke Bedrock with primary model, fall back to haiku on failure.
        Returns the assistant's text response.
        """
        messages = [{"role": "user", "content": prompt}]
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system

        last_error = ""
        for model_id in [BEDROCK_PRIMARY_MODEL, BEDROCK_FALLBACK_MODEL]:
            try:
                self._stats["invocations"] += 1
                resp = self._get_bedrock().invoke_model(
                    modelId=model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(body),
                )
                result = json.loads(resp["body"].read())
                text = result["content"][0]["text"]
                log.info(f"[BEDROCK] {model_id} — {len(text)} chars returned")
                return text
            except ClientError as e:
                code = e.response["Error"]["Code"]
                msg  = e.response["Error"]["Message"]
                self._stats["failures"] += 1
                last_error = f"{code}: {msg}"
                log.warning(f"[BEDROCK] {model_id} ClientError {code}: {msg}")
            except Exception as e:
                self._stats["failures"] += 1
                last_error = str(e)
                log.warning(f"[BEDROCK] {model_id} error: {e}")

        # Both models failed — return sentinel so callers can degrade gracefully
        return f"__BEDROCK_UNAVAILABLE__: {last_error}"

    # ── S3 helpers ─────────────────────────────────────────────────────────────
    def _save_report(self, content: str, prefix: str, extension: str = "md") -> str:
        """
        Save a text report to S3. Returns the s3:// URI.
        prefix examples: 'incidents', 'predictive-alerts', 'daily-summaries'
        """
        ts  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        h   = hashlib.md5(content.encode()).hexdigest()[:6]
        key = f"{prefix}/{ts}-{h}.{extension}"
        try:
            self._get_s3().put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown" if extension == "md" else "application/json",
                Metadata={"phase": "8.7", "generated-by": "bedrock-advisor"},
            )
            self._stats["s3_saves"] += 1
            uri = f"s3://{S3_BUCKET}/{key}"
            log.info(f"[S3] Saved report → {uri}")
            return uri
        except Exception as e:
            log.error(f"[S3] Failed to save report: {e}")
            return ""

    # ── SNS helpers ───────────────────────────────────────────────────────────
    def _send_sns_alert(self, subject: str, body: str) -> bool:
        """
        Send an SNS email notification. Subject is auto-prefixed with [5G-Core].
        Returns True on success.
        """
        full_subject = f"[5G-Core Alert] {subject}"[:100]  # SNS subject max 100 chars
        try:
            self._get_sns().publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=full_subject,
                Message=body,
            )
            self._stats["sns_sent"] += 1
            log.info(f"[SNS] Alert sent: {full_subject}")
            return True
        except Exception as e:
            log.error(f"[SNS] Failed to send alert: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def analyse_network_event(self, event: NetworkEvent) -> dict:
        """
        Triage a network event using Claude. Returns analysis dict with:
          root_cause, severity_assessment, immediate_actions (list),
          preventive_measures (list), estimated_impact, s3_uri
        Critical events trigger an SNS email alert.
        """
        system = (
            "You are an expert 5G core network operations AI embedded in a "
            "cloud-native Open5GS deployment on AWS EKS. You analyse real-time "
            "telemetry and provide concise, actionable incident triage. "
            "Your output must be valid JSON only — no markdown fences."
        )

        prompt = f"""Analyse this 5G core network event and return a JSON response.

NETWORK EVENT:
{event.to_context_str()}

CLUSTER CONTEXT:
- Platform: Open5GS v2.7.2 on EKS (3 nodes, us-east-1)
- Network functions: AMF, SMF, UPF (auto-scaled 1-5), AUSF, UDM, UDR, NRF, PCF, NSSF, BSF
- Network slices: eMBB (SST=1), URLLC (SST=2), mMTC (SST=3)
- SageMaker anomaly threshold: score > 0.6 = anomaly

Return ONLY this JSON (no markdown, no explanation outside the JSON):
{{
  "root_cause": "<2-3 sentence root cause analysis>",
  "severity_assessment": "<validated severity: critical|high|medium|low|info>",
  "immediate_actions": ["<action 1>", "<action 2>", "<action 3>"],
  "preventive_measures": ["<measure 1>", "<measure 2>"],
  "estimated_impact": "<user-facing impact description>",
  "confidence": <0.0-1.0>,
  "recommended_scale_target": <integer replicas or null>
}}"""

        raw = self._invoke(prompt, system=system, max_tokens=800)

        if raw.startswith("__BEDROCK_UNAVAILABLE__"):
            log.warning("[BEDROCK] analyse_network_event: model unavailable")
            analysis = {
                "root_cause": "Bedrock model unavailable — enable model access in AWS Console.",
                "severity_assessment": event.severity,
                "immediate_actions": ["Check pod logs", "Verify Prometheus metrics", "Enable Bedrock model access"],
                "preventive_measures": ["Enable Bedrock model access in AWS Console"],
                "estimated_impact": "Unknown — Bedrock AI unavailable",
                "confidence": 0.0,
                "recommended_scale_target": None,
            }
        else:
            try:
                # Strip any accidental markdown fences
                clean = raw.strip()
                if clean.startswith("```"):
                    clean = "\n".join(clean.split("\n")[1:])
                if clean.endswith("```"):
                    clean = "\n".join(clean.split("\n")[:-1])
                analysis = json.loads(clean.strip())
            except json.JSONDecodeError:
                log.warning("[BEDROCK] analyse_network_event: non-JSON response, wrapping")
                analysis = {
                    "root_cause": raw[:500],
                    "severity_assessment": event.severity,
                    "immediate_actions": ["Check pod logs", "Verify Prometheus metrics"],
                    "preventive_measures": ["Monitor closely"],
                    "estimated_impact": "Unknown — manual review required",
                    "confidence": 0.5,
                    "recommended_scale_target": None,
                }

        analysis["timestamp"]  = event.timestamp
        analysis["event_type"] = event.event_type

        # Save to S3
        report_md = (
            f"# Incident Analysis — {event.timestamp}\n\n"
            f"**Event type:** {event.event_type}  \n"
            f"**Severity:** {analysis.get('severity_assessment', event.severity)}\n\n"
            f"## Root Cause\n{analysis.get('root_cause', '')}\n\n"
            f"## Immediate Actions\n"
            + "\n".join(f"- {a}" for a in analysis.get("immediate_actions", []))
            + f"\n\n## Preventive Measures\n"
            + "\n".join(f"- {m}" for m in analysis.get("preventive_measures", []))
            + f"\n\n## Estimated Impact\n{analysis.get('estimated_impact', '')}\n\n"
            f"## Raw Metrics\n```\n{event.to_context_str()}\n```\n"
        )
        s3_uri = self._save_report(report_md, "incidents")
        analysis["s3_uri"] = s3_uri

        # SNS alert for high/critical events
        if analysis.get("severity_assessment", "").lower() in ("critical", "high"):
            self._send_sns_alert(
                subject=f"{event.event_type.upper()} — {analysis.get('severity_assessment', 'HIGH')} severity",
                body=(
                    f"5G Core Network Alert\n"
                    f"{'='*50}\n"
                    f"Timestamp : {event.timestamp}\n"
                    f"Type      : {event.event_type}\n"
                    f"Severity  : {analysis.get('severity_assessment')}\n\n"
                    f"Root Cause:\n{analysis.get('root_cause')}\n\n"
                    f"Immediate Actions:\n"
                    + "\n".join(f"  {i+1}. {a}" for i, a in enumerate(analysis.get("immediate_actions", [])))
                    + f"\n\nImpact: {analysis.get('estimated_impact')}\n\n"
                    f"Full report: {s3_uri}\n"
                ),
            )

        log.info(f"[BEDROCK] analyse_network_event complete — severity={analysis.get('severity_assessment')}")
        return analysis

    # ─────────────────────────────────────────────────────────────────────────
    def generate_capacity_forecast(
        self,
        historical_metrics: list[dict],
        forecast_data: list[float],
    ) -> dict:
        """
        AI-enhanced capacity planning report combining ARIMA forecast with
        Claude's contextual reasoning. Returns plan dict + s3_uri.

        historical_metrics: list of {cpu_upf, upf_replicas, timestamp} dicts
        forecast_data: 12-step ARIMA forecast (30s intervals = 6 hours)
        """
        system = (
            "You are a 5G network capacity planning AI. Given statistical "
            "forecasts and historical utilisation, produce actionable scaling "
            "plans. Output valid JSON only."
        )

        hist_summary = "\n".join(
            f"  t-{len(historical_metrics)-i}: cpu={m.get('cpu_upf_pct', 0):.1f}% replicas={m.get('upf_replicas', 1)}"
            for i, m in enumerate(historical_metrics[-6:])
        ) if historical_metrics else "  (no history available)"

        fc_str = ", ".join(f"{v:.1f}" for v in forecast_data)
        fc_max = max(forecast_data) if forecast_data else 0
        fc_avg = sum(forecast_data) / len(forecast_data) if forecast_data else 0

        prompt = f"""Analyse this 5G core capacity forecast and recommend scaling actions.

ARIMA FORECAST (next 6 hours, 12 x 30-min steps):
Values: [{fc_str}]
Peak predicted: {fc_max:.1f} UEs/sessions
Average: {fc_avg:.1f}

RECENT HISTORY (last 3 minutes):
{hist_summary}

SCALING CONSTRAINTS:
- UPF replicas: min=1, max=5
- Each replica handles ~100 concurrent sessions efficiently
- Pre-scaling takes ~45 seconds
- Forecast threshold for pre-scaling: 150 UEs

Return ONLY this JSON:
{{
  "recommendation": "<scale_up|scale_down|maintain>",
  "target_replicas": <integer>,
  "reasoning": "<2-3 sentences>",
  "risk_level": "<low|medium|high>",
  "pre_scale_window": "<when to pre-scale, e.g. 'immediately' or 'in 2h30m'>",
  "cost_impact": "<estimated cost change>",
  "confidence": <0.0-1.0>
}}"""

        raw = self._invoke(prompt, system=system, max_tokens=600)

        if raw.startswith("__BEDROCK_UNAVAILABLE__"):
            plan = {
                "recommendation": "maintain",
                "target_replicas": max(1, round(fc_max / 100)),
                "reasoning": "Bedrock AI unavailable — using heuristic: 1 replica per 100 peak UEs.",
                "risk_level": "medium",
                "pre_scale_window": "immediately" if fc_max > 150 else "scheduled",
                "cost_impact": "unknown",
                "confidence": 0.0,
            }
        else:
            try:
                clean = raw.strip().strip("```json").strip("```").strip()
                plan = json.loads(clean)
            except json.JSONDecodeError:
                plan = {
                    "recommendation": "maintain",
                    "target_replicas": 1,
                    "reasoning": raw[:300],
                    "risk_level": "medium",
                    "pre_scale_window": "immediately",
                    "cost_impact": "unknown",
                    "confidence": 0.5,
                }

        plan["forecast_peak"]   = fc_max
        plan["forecast_avg"]    = fc_avg
        plan["forecast_steps"]  = forecast_data
        plan["generated_at"]    = datetime.now(timezone.utc).isoformat()

        report_md = (
            f"# Capacity Forecast Report — {plan['generated_at']}\n\n"
            f"**Recommendation:** {plan.get('recommendation', 'unknown').upper()}  \n"
            f"**Target replicas:** {plan.get('target_replicas')}  \n"
            f"**Risk level:** {plan.get('risk_level')}  \n"
            f"**Pre-scale window:** {plan.get('pre_scale_window')}\n\n"
            f"## Reasoning\n{plan.get('reasoning', '')}\n\n"
            f"## Forecast Data\nPeak: {fc_max:.1f} | Avg: {fc_avg:.1f}\n"
            f"Steps: [{fc_str}]\n\n"
            f"## Cost Impact\n{plan.get('cost_impact', 'N/A')}\n"
        )
        plan["s3_uri"] = self._save_report(report_md, "capacity-forecasts")

        log.info(f"[BEDROCK] capacity_forecast: {plan.get('recommendation')} → {plan.get('target_replicas')} replicas")
        return plan

    # ─────────────────────────────────────────────────────────────────────────
    def generate_daily_summary(self, daily_metrics: dict) -> dict:
        """
        Generate an end-of-day operations summary. Returns summary dict + s3_uri.

        daily_metrics keys (all optional, defaulting to 0):
          total_anomalies, max_cpu_upf, avg_cpu_upf, max_replicas,
          total_scale_events, total_ue_registrations, uptime_pct,
          bedrock_invocations, sagemaker_invocations
        """
        system = (
            "You are a 5G network operations manager AI. Write concise, "
            "professional end-of-day reports for network engineers. "
            "Output valid JSON only."
        )

        dm = daily_metrics
        prompt = f"""Generate an end-of-day operations summary for the 5G core network.

TODAY'S METRICS:
- Anomalies detected : {dm.get('total_anomalies', 0)}
- Peak UPF CPU       : {dm.get('max_cpu_upf', 0):.1f}%
- Average UPF CPU    : {dm.get('avg_cpu_upf', 0):.1f}%
- Peak UPF replicas  : {dm.get('max_replicas', 1)}
- Scaling events     : {dm.get('total_scale_events', 0)}
- UE registrations   : {dm.get('total_ue_registrations', 0)}
- System uptime      : {dm.get('uptime_pct', 100.0):.2f}%
- Bedrock invocations: {dm.get('bedrock_invocations', 0)}
- SageMaker calls    : {dm.get('sagemaker_invocations', 0)}
- Date               : {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

Return ONLY this JSON:
{{
  "overall_grade": "<A|B|C|D|F>",
  "headline": "<one sentence summary>",
  "highlights": ["<positive 1>", "<positive 2>"],
  "concerns": ["<concern 1>"],
  "tomorrow_focus": ["<action 1>", "<action 2>"],
  "capacity_trend": "<improving|stable|degrading>",
  "ai_assist_value": "<brief note on Bedrock/ML contribution today>"
}}"""

        raw = self._invoke(prompt, system=system, max_tokens=700)

        if raw.startswith("__BEDROCK_UNAVAILABLE__"):
            summary = {
                "overall_grade": "B",
                "headline": f"System operational — {dm.get('total_anomalies', 0)} anomalies, {dm.get('uptime_pct', 100):.2f}% uptime",
                "highlights": [f"Uptime: {dm.get('uptime_pct', 100):.2f}%", f"Peak CPU: {dm.get('max_cpu_upf', 0):.1f}%"],
                "concerns": ["Enable Bedrock model access for AI-generated insights"] if dm.get("total_anomalies", 0) == 0 else [f"{dm.get('total_anomalies')} anomalies detected today"],
                "tomorrow_focus": ["Monitor UPF CPU trends", "Review anomaly patterns"],
                "capacity_trend": "stable",
                "ai_assist_value": "Bedrock AI unavailable — enable model access in AWS Console.",
            }
        else:
            try:
                clean = raw.strip().strip("```json").strip("```").strip()
                summary = json.loads(clean)
            except json.JSONDecodeError:
                summary = {
                    "overall_grade": "B",
                    "headline": "Daily operations completed",
                    "highlights": ["System operational"],
                    "concerns": [],
                    "tomorrow_focus": ["Continue monitoring"],
                    "capacity_trend": "stable",
                    "ai_assist_value": raw[:200],
                }

        summary["date"]           = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary["raw_metrics"]    = dm
        summary["generated_at"]   = datetime.now(timezone.utc).isoformat()

        report_md = (
            f"# Daily Operations Summary — {summary['date']}\n\n"
            f"**Grade:** {summary.get('overall_grade')}  \n"
            f"**Headline:** {summary.get('headline')}\n\n"
            f"## Highlights\n"
            + "\n".join(f"- {h}" for h in summary.get("highlights", []))
            + f"\n\n## Concerns\n"
            + ("\n".join(f"- {c}" for c in summary.get("concerns", [])) or "- None")
            + f"\n\n## Tomorrow's Focus\n"
            + "\n".join(f"- {f}" for f in summary.get("tomorrow_focus", []))
            + f"\n\n## AI Contribution\n{summary.get('ai_assist_value', 'N/A')}\n\n"
            f"## Raw Metrics\n```json\n{json.dumps(dm, indent=2)}\n```\n"
        )
        summary["s3_uri"] = self._save_report(report_md, "daily-summaries")

        log.info(f"[BEDROCK] daily_summary: grade={summary.get('overall_grade')}")
        return summary

    # ─────────────────────────────────────────────────────────────────────────
    def query_network(self, question: str, current_metrics: dict) -> str:
        """
        Answer a natural-language question about the network using live metrics.
        Returns a human-readable string answer.
        """
        system = (
            "You are a helpful 5G network operations assistant. Answer questions "
            "about the network clearly and concisely in plain English. "
            "Limit answers to 3-5 sentences."
        )

        metrics_str = "\n".join(
            f"  {k}: {v}" for k, v in current_metrics.items()
        )

        prompt = f"""Answer this question about the 5G core network.

CURRENT NETWORK METRICS:
{metrics_str}

QUESTION: {question}

Answer in plain English (3-5 sentences). Be specific and use the metric values provided."""

        result = self._invoke(prompt, system=system, max_tokens=400)
        if result.startswith("__BEDROCK_UNAVAILABLE__"):
            return "Bedrock AI unavailable — enable model access in AWS Console to use natural language queries."
        return result

    # ─────────────────────────────────────────────────────────────────────────
    def get_network_health_score(self, metrics: dict) -> dict:
        """
        Compute a 0-100 composite network health score with per-slice breakdown.

        Returns:
          overall_score (0-100), grade (A-F), status (healthy|degraded|critical),
          slice_scores {embb, urllc, mmtc},
          component_scores {upf, amf, connectivity, capacity},
          insights (list[str]), recommendations (list[str])
        """
        # Deterministic component scores (fast, no Bedrock call)
        cpu_upf   = float(metrics.get("cpu_upf_pct", 0.0))
        cpu_amf   = float(metrics.get("cpu_amf_pct", 0.0))
        replicas  = int(metrics.get("upf_replicas", 1))
        restarts  = int(metrics.get("pod_restarts", 0))
        anom_score= float(metrics.get("anomaly_score", 0.0))
        fc_max    = float(metrics.get("forecast_max_ues", 0.0))
        uptime    = float(metrics.get("uptime_pct", 100.0))

        # Component: UPF health (CPU load, replicas)
        upf_score = max(0, 100 - cpu_upf * 1.2 - restarts * 5)

        # Component: AMF health
        amf_score = max(0, 100 - cpu_amf * 1.0)

        # Component: anomaly/stability
        stability_score = max(0, 100 - anom_score * 80)

        # Component: capacity headroom
        capacity_score  = max(0, 100 - max(0, fc_max - 100) * 0.5)

        # Overall weighted composite
        overall = (
            upf_score      * 0.35 +
            amf_score      * 0.20 +
            stability_score* 0.30 +
            capacity_score * 0.15
        )
        overall = min(100.0, max(0.0, overall))

        # Per-slice scores (heuristic: eMBB tracks UPF, URLLC penalises instability more)
        embb_score  = min(100.0, (upf_score   * 0.6 + stability_score * 0.4))
        urllc_score = min(100.0, (stability_score * 0.7 + upf_score * 0.3))
        mmtc_score  = min(100.0, (amf_score   * 0.5 + capacity_score * 0.5))

        # Grade
        if overall >= 90:
            grade, status = "A", "healthy"
        elif overall >= 75:
            grade, status = "B", "healthy"
        elif overall >= 60:
            grade, status = "C", "degraded"
        elif overall >= 40:
            grade, status = "D", "degraded"
        else:
            grade, status = "F", "critical"

        # Quick AI insight (short, use haiku for speed)
        prompt = (
            f"5G core health score: {overall:.0f}/100 (grade {grade}, {status}). "
            f"UPF CPU: {cpu_upf:.1f}%, restarts: {restarts}, anomaly_score: {anom_score:.3f}. "
            f"Give 2 bullet-point insights and 1 recommendation. Be concise."
        )
        ai_text = ""
        try:
            ai_text = self._invoke(prompt, max_tokens=250)
            if ai_text.startswith("__BEDROCK_UNAVAILABLE__"):
                ai_text = "AI insight unavailable — enable Bedrock model access in AWS Console."
        except Exception:
            ai_text = "AI insight unavailable."

        result = {
            "overall_score"   : round(overall, 1),
            "grade"           : grade,
            "status"          : status,
            "slice_scores"    : {
                "embb" : round(embb_score,  1),
                "urllc": round(urllc_score, 1),
                "mmtc" : round(mmtc_score,  1),
            },
            "component_scores": {
                "upf"         : round(upf_score,        1),
                "amf"         : round(amf_score,        1),
                "stability"   : round(stability_score,  1),
                "capacity"    : round(capacity_score,   1),
            },
            "ai_insight"      : ai_text.strip(),
            "timestamp"       : datetime.now(timezone.utc).isoformat(),
        }

        log.info(
            f"[BEDROCK] health_score={overall:.0f}/100 (grade={grade}) "
            f"eMBB={embb_score:.0f} URLLC={urllc_score:.0f} mMTC={mmtc_score:.0f}"
        )
        return result

    # ─────────────────────────────────────────────────────────────────────────
    def predict_maintenance(self, nf_metrics: dict) -> dict:
        """
        Predict maintenance windows for all 14 network functions.

        nf_metrics: dict keyed by NF name → {cpu_pct, restarts, uptime_pct,
                                               error_rate, last_restart_ts}

        Saves predictions to S3 /predictive-alerts/ prefix.
        Returns dict with per-NF predictions + s3_uri.
        """
        system = (
            "You are a 5G network reliability engineer AI. Predict maintenance "
            "needs for network functions based on health indicators. "
            "Output valid JSON only."
        )

        nf_lines = []
        for nf in NETWORK_FUNCTIONS:
            m = nf_metrics.get(nf, {})
            nf_lines.append(
                f"  {nf:8s}: cpu={m.get('cpu_pct', 0.0):5.1f}%  "
                f"restarts={m.get('restarts', 0):3d}  "
                f"uptime={m.get('uptime_pct', 100.0):6.2f}%  "
                f"error_rate={m.get('error_rate', 0.0):.3f}  "
                f"last_restart={m.get('last_restart_ts', 'never')}"
            )

        prompt = f"""Analyse these 14 Open5GS network function health metrics and predict maintenance needs.

NETWORK FUNCTION METRICS:
{chr(10).join(nf_lines)}

For each NF, assess:
- maintenance_urgency: none|low|medium|high|critical
- estimated_hours_to_failure: integer (hours) or null if healthy
- recommended_action: restart|scale|monitor|replace|none
- maintenance_window: "off-peak" | "next 6h" | "immediate" | "scheduled"

Return ONLY this JSON:
{{
  "predictions": {{
    "<nf_name>": {{
      "maintenance_urgency": "<none|low|medium|high|critical>",
      "estimated_hours_to_failure": <integer or null>,
      "recommended_action": "<restart|scale|monitor|replace|none>",
      "maintenance_window": "<off-peak|next 6h|immediate|scheduled>",
      "reasoning": "<one sentence>"
    }}
  }},
  "critical_nfs": ["<nf names needing immediate action>"],
  "next_maintenance_window": "<recommended time>",
  "overall_fleet_health": "<healthy|degraded|critical>"
}}"""

        raw = self._invoke(prompt, system=system, max_tokens=1200)

        if raw.startswith("__BEDROCK_UNAVAILABLE__"):
            log.warning("[BEDROCK] predict_maintenance: model unavailable — using heuristics")
            def _heuristic(nf: str) -> dict:
                m = nf_metrics.get(nf, {})
                cpu = m.get("cpu_pct", 0)
                restarts = m.get("restarts", 0)
                urgency = "high" if restarts > 3 else ("medium" if cpu > 70 else "low" if cpu > 50 else "none")
                return {
                    "maintenance_urgency": urgency,
                    "estimated_hours_to_failure": None,
                    "recommended_action": "monitor",
                    "maintenance_window": "scheduled",
                    "reasoning": f"Heuristic: CPU={cpu:.1f}%, restarts={restarts}",
                }
            predictions = {
                "predictions"             : {nf: _heuristic(nf) for nf in NETWORK_FUNCTIONS},
                "critical_nfs"            : [nf for nf in NETWORK_FUNCTIONS if nf_metrics.get(nf, {}).get("restarts", 0) > 3],
                "next_maintenance_window" : "scheduled",
                "overall_fleet_health"    : "healthy",
            }
        else:
            try:
                clean = raw.strip().strip("```json").strip("```").strip()
                predictions = json.loads(clean)
            except json.JSONDecodeError:
                log.warning("[BEDROCK] predict_maintenance: non-JSON response")
                predictions = {
                    "predictions"             : {nf: {"maintenance_urgency": "none", "recommended_action": "monitor"} for nf in NETWORK_FUNCTIONS},
                    "critical_nfs"            : [],
                    "next_maintenance_window" : "scheduled",
                    "overall_fleet_health"    : "healthy",
                }

        predictions["generated_at"] = datetime.now(timezone.utc).isoformat()
        predictions["nf_metrics"]   = nf_metrics

        # Build markdown report
        rows = []
        for nf in NETWORK_FUNCTIONS:
            p = predictions.get("predictions", {}).get(nf, {})
            rows.append(
                f"| {nf:8s} | {p.get('maintenance_urgency','?'):8s} | "
                f"{p.get('recommended_action','?'):10s} | "
                f"{p.get('maintenance_window','?'):12s} | "
                f"{p.get('reasoning','')} |"
            )

        report_md = (
            f"# Predictive Maintenance Report — {predictions['generated_at']}\n\n"
            f"**Fleet health:** {predictions.get('overall_fleet_health')}  \n"
            f"**Next window:** {predictions.get('next_maintenance_window')}  \n"
            f"**Critical NFs:** {', '.join(predictions.get('critical_nfs', [])) or 'none'}\n\n"
            f"| NF | Urgency | Action | Window | Reasoning |\n"
            f"|---|---|---|---|---|\n"
            + "\n".join(rows)
            + "\n"
        )
        s3_uri = self._save_report(report_md, "predictive-alerts")
        predictions["s3_uri"] = s3_uri

        # Alert for critical NFs
        critical = predictions.get("critical_nfs", [])
        if critical:
            self._send_sns_alert(
                subject=f"Predictive Maintenance — {len(critical)} NF(s) need immediate attention",
                body=(
                    f"Predictive Maintenance Alert\n{'='*50}\n"
                    f"Critical NFs: {', '.join(critical)}\n"
                    f"Fleet health: {predictions.get('overall_fleet_health')}\n\n"
                    f"Full report: {s3_uri}\n"
                ),
            )

        log.info(
            f"[BEDROCK] predict_maintenance: fleet={predictions.get('overall_fleet_health')} "
            f"critical={critical}"
        )
        return predictions

    # ─────────────────────────────────────────────────────────────────────────
    def generate_post_incident_report(self, incident_data: dict) -> dict:
        """
        Generate a structured post-incident report in markdown format.
        Saves to S3 /post-incident-reports/ and sends SNS notification.

        incident_data keys:
          incident_id, start_time, end_time, event_type, severity,
          root_cause_hypothesis, actions_taken (list), metrics_at_onset,
          metrics_at_resolution, affected_ues, bedrock_analyses (list of dicts)
        """
        system = (
            "You are a 5G network post-incident reviewer AI. Write professional, "
            "blameless post-incident reports in markdown that help teams learn "
            "and prevent recurrence. Output valid JSON only."
        )

        actions_taken = incident_data.get("actions_taken", [])
        analyses      = incident_data.get("bedrock_analyses", [])
        analyses_str  = "\n".join(
            f"  Analysis {i+1}: {a.get('root_cause', '')[:200]}"
            for i, a in enumerate(analyses)
        ) if analyses else "  (no Bedrock analyses available)"

        start = incident_data.get("start_time", "unknown")
        end   = incident_data.get("end_time", "unknown")

        # Compute duration
        try:
            dt_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            dt_end   = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration_min = int((dt_end - dt_start).total_seconds() / 60)
        except Exception:
            duration_min = 0

        prompt = f"""Write a post-incident report for this 5G core network incident.

INCIDENT DETAILS:
- Incident ID  : {incident_data.get('incident_id', 'INC-UNKNOWN')}
- Type         : {incident_data.get('event_type', 'unknown')}
- Severity     : {incident_data.get('severity', 'unknown')}
- Start        : {start}
- End          : {end}
- Duration     : {duration_min} minutes
- Affected UEs : {incident_data.get('affected_ues', 0)}
- Root cause hypothesis: {incident_data.get('root_cause_hypothesis', 'under investigation')}

ACTIONS TAKEN:
{chr(10).join(f'  {i+1}. {a}' for i, a in enumerate(actions_taken)) or '  (none recorded)'}

BEDROCK AI ANALYSES DURING INCIDENT:
{analyses_str}

METRICS AT ONSET:
{json.dumps(incident_data.get('metrics_at_onset', {}), indent=2)}

METRICS AT RESOLUTION:
{json.dumps(incident_data.get('metrics_at_resolution', {}), indent=2)}

Return ONLY this JSON:
{{
  "executive_summary": "<3-4 sentence summary for management>",
  "timeline": [
    {{"time": "<relative>", "event": "<what happened>"}}
  ],
  "root_cause": "<detailed root cause analysis>",
  "contributing_factors": ["<factor 1>", "<factor 2>"],
  "impact_summary": "<user and service impact>",
  "what_went_well": ["<positive 1>", "<positive 2>"],
  "what_went_wrong": ["<issue 1>"],
  "corrective_actions": [
    {{"action": "<action>", "owner": "ops-team", "due": "<timeframe>"}}
  ],
  "lessons_learned": ["<lesson 1>", "<lesson 2>"],
  "recurrence_probability": "<low|medium|high>",
  "estimated_cost_impact": "<e.g. $0-5 in extra compute>"
}}"""

        raw = self._invoke(prompt, system=system, max_tokens=1500)

        if raw.startswith("__BEDROCK_UNAVAILABLE__"):
            log.warning("[BEDROCK] post_incident_report: model unavailable — using template")
            report = {
                "executive_summary"      : f"Incident {incident_data.get('incident_id','INC-UNKNOWN')}: {incident_data.get('event_type','unknown')} lasting {duration_min} minutes affecting {incident_data.get('affected_ues',0)} UEs. Automated detection and remediation engaged. Bedrock AI narrative unavailable — enable model access for full PIR.",
                "timeline"               : [
                    {"time": "T+0m",             "event": f"Anomaly detected ({incident_data.get('event_type','unknown')})"},
                    {"time": f"T+{duration_min}m", "event": "Incident resolved"},
                ],
                "root_cause"             : incident_data.get("root_cause_hypothesis", "Under investigation"),
                "contributing_factors"   : ["Automated detection triggered", "Closed-loop engine responded"],
                "impact_summary"         : f"Duration: {duration_min} min, Affected UEs: {incident_data.get('affected_ues', 0)}",
                "what_went_well"         : ["IsolationForest anomaly detection worked", "Automated UPF scaling responded"],
                "what_went_wrong"        : ["Bedrock AI narrative unavailable (enable model access)"],
                "corrective_actions"     : [
                    {"action": "Enable Bedrock model access in AWS Console", "owner": "ops-team", "due": "ASAP"},
                ],
                "lessons_learned"        : ["Enable Bedrock for full AI-powered PIRs"],
                "recurrence_probability" : "medium",
                "estimated_cost_impact"  : "Compute cost for UPF scaling only",
            }
        else:
            try:
                clean = raw.strip().strip("```json").strip("```").strip()
                report = json.loads(clean)
            except json.JSONDecodeError:
                log.warning("[BEDROCK] post_incident_report: non-JSON response")
                report = {
                    "executive_summary"      : raw[:500],
                    "timeline"               : [],
                    "root_cause"             : incident_data.get("root_cause_hypothesis", ""),
                    "contributing_factors"   : [],
                    "impact_summary"         : f"Duration: {duration_min} min",
                    "what_went_well"         : ["Automated detection worked"],
                    "what_went_wrong"        : ["Manual review required"],
                    "corrective_actions"     : [],
                    "lessons_learned"        : ["Improve observability"],
                    "recurrence_probability" : "medium",
                    "estimated_cost_impact"  : "unknown",
                }

        report["incident_id"]  = incident_data.get("incident_id", "INC-UNKNOWN")
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["duration_min"] = duration_min

        # Build full markdown document
        timeline_rows = "\n".join(
            f"| {t.get('time','?')} | {t.get('event','?')} |"
            for t in report.get("timeline", [])
        )

        ca_rows = "\n".join(
            f"| {c.get('action','?')} | {c.get('owner','ops-team')} | {c.get('due','TBD')} |"
            for c in report.get("corrective_actions", [])
        )

        report_md = (
            f"# Post-Incident Report: {report['incident_id']}\n\n"
            f"**Generated:** {report['generated_at']}  \n"
            f"**Severity:** {incident_data.get('severity')}  \n"
            f"**Duration:** {duration_min} minutes  \n"
            f"**Affected UEs:** {incident_data.get('affected_ues', 0)}\n\n"
            f"---\n\n"
            f"## Executive Summary\n{report.get('executive_summary', '')}\n\n"
            f"## Timeline\n| Time | Event |\n|---|---|\n{timeline_rows}\n\n"
            f"## Root Cause\n{report.get('root_cause', '')}\n\n"
            f"## Contributing Factors\n"
            + "\n".join(f"- {f}" for f in report.get("contributing_factors", []))
            + f"\n\n## Impact\n{report.get('impact_summary', '')}\n\n"
            f"## What Went Well\n"
            + "\n".join(f"- {w}" for w in report.get("what_went_well", []))
            + f"\n\n## What Went Wrong\n"
            + "\n".join(f"- {w}" for w in report.get("what_went_wrong", []))
            + f"\n\n## Corrective Actions\n"
            f"| Action | Owner | Due |\n|---|---|---|\n{ca_rows}\n\n"
            f"## Lessons Learned\n"
            + "\n".join(f"- {l}" for l in report.get("lessons_learned", []))
            + f"\n\n## Recurrence Probability\n{report.get('recurrence_probability')}\n\n"
            f"## Estimated Cost Impact\n{report.get('estimated_cost_impact')}\n\n"
            f"---\n*Generated by Claude Bedrock AI (Phase 8.7)*\n"
        )
        s3_uri = self._save_report(report_md, "post-incident-reports")
        report["s3_uri"]    = s3_uri
        report["markdown"]  = report_md

        # Always SNS for post-incident reports
        self._send_sns_alert(
            subject=f"Post-Incident Report: {report['incident_id']} — {incident_data.get('severity', '').upper()}",
            body=(
                f"Post-Incident Report Ready\n{'='*50}\n"
                f"Incident: {report['incident_id']}\n"
                f"Duration: {duration_min} minutes\n"
                f"Severity: {incident_data.get('severity')}\n\n"
                f"Executive Summary:\n{report.get('executive_summary')}\n\n"
                f"Full report: {s3_uri}\n"
            ),
        )

        log.info(f"[BEDROCK] post_incident_report: {report['incident_id']} → {s3_uri}")
        return report

    # ─────────────────────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """Return operational statistics for this advisor instance."""
        return dict(self._stats)


# ── Module-level singleton factory ────────────────────────────────────────────
_advisor_instance: Optional[BedrockNetworkAdvisor] = None


def get_advisor() -> BedrockNetworkAdvisor:
    """Return the module-level advisor singleton (lazy init)."""
    global _advisor_instance
    if _advisor_instance is None:
        _advisor_instance = BedrockNetworkAdvisor()
    return _advisor_instance


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    print("=== BedrockNetworkAdvisor standalone test ===")
    advisor = BedrockNetworkAdvisor()

    # Quick health score (no Bedrock call for scores, only insight)
    print("\n[1] Network health score…")
    health = advisor.get_network_health_score({
        "cpu_upf_pct"    : 35.0,
        "cpu_amf_pct"    : 10.0,
        "upf_replicas"   : 2,
        "pod_restarts"   : 0,
        "anomaly_score"  : 0.15,
        "forecast_max_ues": 80.0,
        "uptime_pct"     : 99.97,
    })
    print(f"  Score: {health['overall_score']}/100 (grade {health['grade']}, {health['status']})")
    print(f"  eMBB={health['slice_scores']['embb']} URLLC={health['slice_scores']['urllc']} mMTC={health['slice_scores']['mmtc']}")

    # NL query
    print("\n[2] Natural language query…")
    answer = advisor.query_network(
        "Is the network healthy enough to onboard 50 more UEs right now?",
        {"cpu_upf_pct": 35.0, "upf_replicas": 2, "anomaly_score": 0.15}
    )
    print(f"  Answer: {answer[:300]}…")

    print(f"\n[stats] {advisor.get_stats()}")
    print("=== Done ===")
