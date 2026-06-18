#!/usr/bin/env python3
"""
ollama_query_ui.py — Standalone local web UI for querying the Ollama model.

Run with: python3 automation/ollama_query_ui.py
Serves on:  http://localhost:5050

NOT connected to any Kubernetes service or Docker container.
Reuses OllamaAdvisor from ollama_advisor.py for prompt logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify, render_template_string
from ollama_advisor import OllamaAdvisor, _SYSTEM_PROMPT

app = Flask(__name__)
advisor = OllamaAdvisor(url="http://localhost:11434", model="llama3.2:1b")

# Same static sample used in ollama_test.py
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

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>5G Core — Local LLM Query</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
          padding: 32px; width: 680px; max-width: 96vw; }
  h1   { font-size: 1.25rem; font-weight: 600; color: #f8fafc; margin-bottom: 4px; }
  .sub { font-size: 0.8rem; color: #64748b; margin-bottom: 24px; }
  .badge { display:inline-block; background:#0f3460; color:#38bdf8;
           font-size:0.7rem; font-weight:600; padding:2px 8px;
           border-radius:4px; margin-left:8px; vertical-align:middle; }
  label  { display: block; font-size: 0.8rem; color: #94a3b8;
           font-weight: 500; margin-bottom: 6px; }
  input  { width: 100%; padding: 10px 14px; background: #0f172a;
           border: 1px solid #334155; border-radius: 8px; color: #f1f5f9;
           font-size: 0.95rem; outline: none; }
  input:focus { border-color: #38bdf8; }
  button { margin-top: 14px; width: 100%; padding: 11px;
           background: #0ea5e9; border: none; border-radius: 8px;
           color: #fff; font-size: 0.95rem; font-weight: 600;
           cursor: pointer; transition: background 0.2s; }
  button:hover    { background: #0284c7; }
  button:disabled { background: #1e40af; cursor: wait; }
  .answer { margin-top: 24px; padding: 16px; background: #0f172a;
            border: 1px solid #334155; border-radius: 8px;
            font-size: 0.9rem; line-height: 1.65; color: #cbd5e1;
            min-height: 80px; white-space: pre-wrap; display: none; }
  .answer.visible { display: block; }
  .spinner { display: inline-block; width: 14px; height: 14px;
             border: 2px solid #fff; border-top-color: transparent;
             border-radius: 50%; animation: spin 0.7s linear infinite;
             vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status-grid { display: grid; grid-template-columns: repeat(3, 1fr);
                 gap: 10px; margin-bottom: 24px; }
  .stat { background: #0f172a; border: 1px solid #334155; border-radius: 8px;
          padding: 10px 14px; }
  .stat .label { font-size: 0.7rem; color: #64748b; text-transform: uppercase;
                 letter-spacing: 0.05em; }
  .stat .value { font-size: 1.1rem; font-weight: 600; color: #38bdf8;
                 margin-top: 2px; }
  .examples { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .ex-btn { padding: 6px 12px; background: #1e293b; border: 1px solid #334155;
            border-radius: 20px; color: #94a3b8; font-size: 0.78rem;
            cursor: pointer; transition: border-color 0.15s, color 0.15s; }
  .ex-btn:hover { border-color: #38bdf8; color: #e2e8f0; }
</style>
</head>
<body>
<div class="card">
  <h1>5G Core Network Query <span class="badge">llama3.2:1b · local</span></h1>
  <p class="sub">Powered by Ollama on localhost — no cloud, no Kubernetes</p>

  <div class="status-grid">
    <div class="stat">
      <div class="label">Health Score</div>
      <div class="value">{{ status.overall_score }}/100 {{ status.grade }}</div>
    </div>
    <div class="stat">
      <div class="label">UPF CPU</div>
      <div class="value">{{ status.cpu_upf_pct }}%</div>
    </div>
    <div class="stat">
      <div class="label">UPF Replicas</div>
      <div class="value">{{ status.upf_replicas }}</div>
    </div>
    <div class="stat">
      <div class="label">UEs</div>
      <div class="value">{{ status.ue_count }}</div>
    </div>
    <div class="stat">
      <div class="label">Anomaly Score</div>
      <div class="value">{{ status.anomaly_score }}</div>
    </div>
    <div class="stat">
      <div class="label">Pods Ready</div>
      <div class="value">{{ status.pods_ready }}/14</div>
    </div>
  </div>

  <div class="examples">
    <button class="ex-btn" onclick="preset('What is the current network health?')">What is the current network health?</button>
    <button class="ex-btn" onclick="preset('Is the URLLC slice meeting its SLA?')">Is the URLLC slice meeting its SLA?</button>
    <button class="ex-btn" onclick="preset('Should I scale up UPF replicas?')">Should I scale up UPF replicas?</button>
    <button class="ex-btn" onclick="preset('Is the current anomaly score a concern?')">Is the current anomaly score a concern?</button>
  </div>
  <label for="q">Ask a question about the network</label>
  <input id="q" type="text" placeholder="e.g. Why is the UPF at 2 replicas?" autofocus>
  <button id="btn" onclick="ask()">Ask</button>
  <div id="answer" class="answer"></div>
</div>

<script>
function preset(q) {
  document.getElementById('q').value = q;
  ask();
}

async function ask() {
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const btn = document.getElementById('btn');
  const box = document.getElementById('answer');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Thinking…';
  box.textContent = '';
  box.classList.remove('visible');

  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})
    });
    const data = await res.json();
    box.textContent = data.answer || data.error || 'No response.';
  } catch(e) {
    box.textContent = 'Error: ' + e.message;
  }

  box.classList.add('visible');
  btn.disabled = false;
  btn.textContent = 'Ask';
}

document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') ask();
});
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML, status=SAMPLE_STATUS)


@app.route("/ask", methods=["POST"])
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Missing question"}), 400
    try:
        answer = advisor.query_network(question, SAMPLE_STATUS)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 503


if __name__ == "__main__":
    print("5G Core Local LLM Query UI")
    print(f"  Model : {advisor.model}")
    print(f"  Ollama: {advisor.url}")
    print("  URL   : http://localhost:5050")
    print()
    app.run(host="0.0.0.0", port=5050, debug=False)
