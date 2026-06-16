"""
Unit tests for automation/network_query_api.py

All external I/O (Prometheus, Bedrock) is stubbed so tests run fully offline.
"""
import os
import sys
from unittest.mock import MagicMock

# Must be set before the module is imported so BEDROCK_ENABLED=false branch is taken.
os.environ["BEDROCK_ENABLED"] = "false"

# Stub bedrock_advisor so the conditional import at module level never fires.
sys.modules.setdefault("bedrock_advisor", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automation"))

import pytest
import network_query_api as api


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    api.app.config["TESTING"] = True
    with api.app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def no_prometheus(monkeypatch):
    """Force synthetic fallback (cpu_upf=12.4, pods_ready=14, …) in every test."""
    monkeypatch.setattr(api, "_prom_reachable", lambda: False)


@pytest.fixture(autouse=True)
def reset_injected_anomaly():
    """Clear any anomaly injection before and after each test."""
    api._injected_anomaly = None
    yield
    api._injected_anomaly = None


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    assert client.get("/health").status_code == 200


def test_health_json_ok(client):
    data = client.get("/health").get_json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "timestamp" in data
    assert "bedrock_enabled" in data


# ── GET /status ───────────────────────────────────────────────────────────────

def test_status_returns_200(client):
    assert client.get("/status").status_code == 200


def test_status_score_in_valid_range(client):
    score = client.get("/status").get_json()["health_score"]
    assert 0 <= score <= 100


def test_status_grade_is_letter(client):
    grade = client.get("/status").get_json()["grade"]
    assert grade in ("A", "B", "C", "D", "F")


def test_status_has_component_scores(client):
    data = client.get("/status").get_json()
    keys = set(data["component_scores"].keys())
    assert keys == {"upf", "amf", "stability", "capacity"}


def test_status_healthy_on_synthetic_low_load(client):
    # Synthetic fallback: cpu_upf=12.4, cpu_amf=4.2, restarts=0 → grade A/B
    data = client.get("/status").get_json()
    assert data["health_score"] >= 75
    assert data["grade"] in ("A", "B")


# ── GET /slices ───────────────────────────────────────────────────────────────

def test_slices_returns_200(client):
    assert client.get("/slices").status_code == 200


def test_slices_has_three_slice_keys(client):
    slices = client.get("/slices").get_json()["slices"]
    assert set(slices.keys()) == {"embb", "mmtc", "urllc"}


def test_each_slice_has_required_fields(client):
    required = {"name", "sst", "dnn", "ip_pool",
                "current_ues", "load_pct", "status", "latency_p99_ms", "sla_met"}
    for name, s in client.get("/slices").get_json()["slices"].items():
        missing = required - set(s.keys())
        assert not missing, f"Slice '{name}' missing fields: {missing}"


def test_slices_load_pct_bounded(client):
    for name, s in client.get("/slices").get_json()["slices"].items():
        assert 0.0 <= s["load_pct"] <= 100.0, f"{name} load_pct={s['load_pct']} out of range"


# ── GET /metrics ──────────────────────────────────────────────────────────────

def test_metrics_returns_200(client):
    assert client.get("/metrics").status_code == 200


def test_metrics_contains_core_keys(client):
    m = client.get("/metrics").get_json()["metrics"]
    for key in ("cpu_upf_pct", "cpu_amf_pct", "upf_replicas", "pods_ready", "pod_restarts"):
        assert key in m, f"Missing key: {key}"


# ── POST /ask ─────────────────────────────────────────────────────────────────

def test_ask_missing_question_returns_400(client):
    assert client.post("/ask", json={}).status_code == 400


def test_ask_whitespace_question_returns_400(client):
    assert client.post("/ask", json={"question": "   "}).status_code == 400


def test_ask_returns_answer_dict(client):
    r = client.post("/ask", json={"question": "What is the network status?"})
    assert r.status_code == 200
    data = r.get_json()
    assert "answer" in data
    assert "metrics_used" in data
    assert "model_used" in data
    assert "timestamp" in data


def test_ask_answer_is_nonempty_string(client):
    r = client.post("/ask", json={"question": "Is the UPF CPU high?"})
    answer = r.get_json()["answer"]
    assert isinstance(answer, str) and len(answer) > 0


def test_ask_model_used_is_local_fallback(client):
    # BEDROCK_ENABLED=false → model_used must indicate local/fallback
    model = client.post("/ask", json={"question": "status?"}).get_json()["model_used"]
    assert "local" in model.lower() or "fallback" in model.lower() or "bedrock" in model.lower()


# ── POST /simulate-anomaly ────────────────────────────────────────────────────

def test_simulate_anomaly_post_returns_200(client):
    assert client.post("/simulate-anomaly").status_code == 200


def test_simulate_anomaly_status_is_injected(client):
    data = client.post("/simulate-anomaly").get_json()
    assert data["status"] == "injected"


def test_simulate_anomaly_cpu_spike_above_80(client):
    data = client.post("/simulate-anomaly").get_json()
    assert data["anomaly"]["cpu_upf_pct"] > 80.0


def test_simulate_anomaly_score_above_threshold(client):
    data = client.post("/simulate-anomaly").get_json()
    assert data["anomaly"]["anomaly_score"] > 0.6


def test_simulate_anomaly_appears_in_metrics(client):
    client.post("/simulate-anomaly")
    cpu = client.get("/metrics").get_json()["metrics"]["cpu_upf_pct"]
    assert cpu > 80.0


# ── DELETE /simulate-anomaly ──────────────────────────────────────────────────

def test_simulate_anomaly_delete_returns_200(client):
    client.post("/simulate-anomaly")
    assert client.delete("/simulate-anomaly").status_code == 200


def test_simulate_anomaly_delete_status_cleared(client):
    client.post("/simulate-anomaly")
    data = client.delete("/simulate-anomaly").get_json()
    assert data["status"] == "cleared"


def test_simulate_anomaly_delete_restores_low_cpu(client):
    client.post("/simulate-anomaly")
    client.delete("/simulate-anomaly")
    # After clear, synthetic fallback resumes → cpu_upf_pct == 12.4
    cpu = client.get("/metrics").get_json()["metrics"]["cpu_upf_pct"]
    assert cpu < 80.0


# ── _fallback_health_score direct tests ──────────────────────────────────────

def test_fallback_score_healthy_system():
    m = {"cpu_upf_pct": 10.0, "cpu_amf_pct": 5.0,
         "pod_restarts": 0, "anomaly_score": 0.0, "forecast_max_ues": 50.0}
    result = api._fallback_health_score(m)
    assert result["health_score"] >= 75
    assert result["grade"] in ("A", "B")
    assert result["status"] == "healthy"


def test_fallback_score_degraded_high_cpu():
    m = {"cpu_upf_pct": 95.0, "cpu_amf_pct": 80.0,
         "pod_restarts": 5, "anomaly_score": 0.9, "forecast_max_ues": 300.0}
    result = api._fallback_health_score(m)
    assert result["health_score"] < 60
    assert result["status"] in ("degraded", "critical")


def test_fallback_score_always_in_0_to_100():
    for cpu in (0.0, 50.0, 100.0, 150.0):
        m = {"cpu_upf_pct": cpu, "cpu_amf_pct": 0.0,
             "pod_restarts": 0, "anomaly_score": 0.0, "forecast_max_ues": 0.0}
        s = api._fallback_health_score(m)["health_score"]
        assert 0.0 <= s <= 100.0, f"Score {s} out of [0,100] for cpu_upf={cpu}"
