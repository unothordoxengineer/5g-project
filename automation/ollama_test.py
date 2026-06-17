#!/usr/bin/env python3
"""
ollama_test.py — Standalone proof-of-concept for local LLM inference via Ollama.

Sends a hardcoded sample network status (same JSON shape as /status returns)
to the local Ollama server and prints the model's plain-English response.

NOT wired into the running API or any Kubernetes service.
Run manually: python3 automation/ollama_test.py
"""

import json
import urllib.request

OLLAMA_URL = "http://localhost:11434"
MODEL      = "llama3.2:1b"

SYSTEM_PROMPT = (
    "You are an expert 5G core network operations assistant for an Open5GS "
    "Cloud-Native 5G Standalone core running on Kubernetes. "
    "Answer operator questions concisely in 2-3 sentences. Be technical and specific."
)

# Static sample — same shape as what /status returns in network_query_api.py
SAMPLE_STATUS = {
    "overall_score": 78,
    "grade": "B",
    "status": "healthy",
    "cpu_upf_pct": 42.5,
    "cpu_amf_pct": 8.1,
    "upf_replicas": 2,
    "ue_count": 7,
    "pods_ready": 14,
    "pod_restarts": 1,
    "anomaly_score": 0.23,
    "gtp_throughput_bps": 204800,
    "slice_scores": {"embb": 81, "urllc": 88, "mmtc": 65},
}

QUESTIONS = [
    "Why is the UPF running at 2 replicas right now?",
    "Is the URLLC slice meeting its latency SLA?",
    "Should I be concerned about the anomaly score?",
]


def ask(question: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Current 5G core status: {json.dumps(SAMPLE_STATUS)}\n\n"
                    f"Operator question: {question}"
                ),
            },
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 200},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        return result["message"]["content"].strip()


def main():
    print(f"Model : {MODEL}")
    print(f"Server: {OLLAMA_URL}")
    print(f"Status: {json.dumps(SAMPLE_STATUS, indent=2)}\n")
    print("=" * 60)

    for q in QUESTIONS:
        print(f"\nQ: {q}")
        print(f"A: {ask(q)}")
        print("-" * 60)


if __name__ == "__main__":
    main()
