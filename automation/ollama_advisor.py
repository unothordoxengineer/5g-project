"""
ollama_advisor.py — Local LLM backend via Ollama for Open5GS Network Query API.

Drop-in replacement for bedrock_advisor when AWS Bedrock is unavailable.
Calls the Ollama REST API running natively on the host (Metal GPU on M1)
reachable from kind pods via host.docker.internal:11434.
"""

import json
import logging
import urllib.request
import urllib.error
import os

log = logging.getLogger(__name__)

OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3.5:mini")

_SYSTEM_PROMPT = """You are an expert 5G core network operations assistant for the Open5GS \
Cloud-Native 5G Standalone (SA) core deployed on Kubernetes.

Network Functions in this deployment:
- AMF: UE registration and mobility management (SBI on port 80)
- SMF: PDU session management, communicates with UPF via PFCP (port 8805)
- UPF: user-plane packet forwarding, GTP-U on N3/N9 (port 2152), scales 1-5 replicas via HPA
- NRF: service discovery for all NFs
- PCF/AUSF/UDM/UDR/BSF/NSSF/SCP: policy, auth, subscriber data
- gNB + UE: simulated by UERANSIM; GTP-U tunnel established on successful PDU session

Scaling: UPF HPA triggers at 70% CPU (0.35 cores of 500m limit).
Anomaly detection: IsolationForest ML model; score 0.0=normal, alert threshold=0.60.
Network slices: eMBB (high-throughput video), URLLC (<1ms latency), mMTC (IoT devices).

Answer operator questions concisely in 2-4 sentences. Be technical and specific. \
Do not mention AWS Bedrock or cloud services. If the metrics show a problem, say so directly."""


class OllamaAdvisor:
    def __init__(self, url: str = OLLAMA_URL, model: str = OLLAMA_MODEL):
        self.url   = url.rstrip("/")
        self.model = model
        log.info(f"OllamaAdvisor ready: {self.url}  model={self.model}")

    def _chat(self, user_message: str, timeout: int = 45) -> str:
        payload = json.dumps({
            "model":    self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            "stream":  False,
            "options": {"temperature": 0.2, "num_predict": 250},
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result["message"]["content"].strip()

    def query_network(self, question: str, metrics: dict) -> str:
        metrics_str = ", ".join(
            f"{k}={v}" for k, v in metrics.items() if k != "timestamp"
        )
        prompt = f"Current 5G core metrics: {metrics_str}\n\nOperator question: {question}"
        return self._chat(prompt)

    def get_network_health_score(self, metrics: dict) -> dict:
        metrics_str = ", ".join(
            f"{k}={v}" for k, v in metrics.items() if k != "timestamp"
        )
        prompt = (
            f"Current 5G core metrics: {metrics_str}\n\n"
            "Reply with ONLY valid JSON — no markdown, no explanation:\n"
            '{"overall_score":<0-100>,"grade":"<A/B/C/D/F>","status":"<healthy|degraded|critical>",'
            '"slice_scores":{"embb":<0-100>,"urllc":<0-100>,"mmtc":<0-100>}}'
        )
        raw = self._chat(prompt, timeout=20)
        start, end = raw.find("{"), raw.rfind("}") + 1
        d = json.loads(raw[start:end])
        score = float(d.get("overall_score", 75))
        ss    = d.get("slice_scores", {})
        return {
            "overall_score": score,
            "health_score":  score,
            "grade":         d.get("grade",  "B"),
            "status":        d.get("status", "healthy"),
            "slice_scores":  {
                "embb":  float(ss.get("embb",  80)),
                "urllc": float(ss.get("urllc", 85)),
                "mmtc":  float(ss.get("mmtc",  75)),
            },
            "bedrock_used": False,
        }


def get_advisor() -> OllamaAdvisor:
    advisor = OllamaAdvisor()
    req = urllib.request.Request(f"{advisor.url}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()
    return advisor
