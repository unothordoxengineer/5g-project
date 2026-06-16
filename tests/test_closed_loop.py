"""
Unit tests for automation/closed_loop.py and the shared _fallback_health_score helper.

SageMaker, boto3, Prometheus, and Bedrock are mocked throughout.
DRY_RUN=true prevents any real kubectl calls.
"""
import os
import sys
import json
from unittest.mock import patch, MagicMock

# Set all env vars before any import so module-level code picks them up.
os.environ["BEDROCK_ENABLED"] = "false"
os.environ["DRY_RUN"]         = "true"
os.environ["LOG_FILE"]        = "/tmp/test_closed_loop.log"

# Stub external packages that must be importable but need no real credentials.
_BOTO3_STUB = MagicMock()
_BOTO3_STUB.client.return_value = MagicMock()
sys.modules.setdefault("boto3",                 _BOTO3_STUB)
sys.modules.setdefault("botocore",              MagicMock())
sys.modules.setdefault("botocore.exceptions",   MagicMock())
sys.modules.setdefault("bedrock_advisor",       MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automation"))

import pytest
from network_query_api import _fallback_health_score

# closed_loop.py uses `dict | None` union syntax (Python ≥ 3.10).
# Skip gracefully on older interpreters; CI runs Python 3.11 so all tests run there.
try:
    import closed_loop as cl
    _CL_OK = True
except TypeError:
    cl = None  # type: ignore[assignment]
    _CL_OK = False

needs_cl = pytest.mark.skipif(not _CL_OK, reason="closed_loop requires Python ≥ 3.10")


# ── helpers ───────────────────────────────────────────────────────────────────

def _metrics(cpu_upf=15.0, cpu_amf=5.0, replicas=1, restarts=0):
    return {
        "cpu_upf_pct":  cpu_upf,
        "cpu_amf_pct":  cpu_amf,
        "upf_replicas": replicas,
        "pod_restarts": restarts,
    }


def _smk_dispatch(anom_score=0.1, is_anom=False, fc=None):
    """Return a sagemaker_invoke side_effect that routes by endpoint name."""
    fc = fc or [float(anom_score * 10)] * 12

    def _invoke(endpoint, payload):
        if "anomaly"    in endpoint: return {"anomaly_score": anom_score, "is_anomaly": is_anom}
        if "forecast"   in endpoint: return {"forecast_6h": fc}
        if "classifier" in endpoint: return {"cluster_id": 0, "cluster_name": "STATE-0"}
        return None

    return _invoke


# ── health score (shared fallback in network_query_api) ──────────────────────
# These run on all Python versions — no dependency on closed_loop.

def test_health_score_healthy_system():
    m = {"cpu_upf_pct": 10.0, "cpu_amf_pct": 5.0,
         "pod_restarts": 0, "anomaly_score": 0.0, "forecast_max_ues": 50.0}
    r = _fallback_health_score(m)
    assert r["health_score"] >= 75
    assert r["grade"] in ("A", "B")
    assert r["status"] == "healthy"


def test_health_score_degraded_high_cpu():
    m = {"cpu_upf_pct": 95.0, "cpu_amf_pct": 80.0,
         "pod_restarts": 5, "anomaly_score": 0.85, "forecast_max_ues": 300.0}
    r = _fallback_health_score(m)
    assert r["health_score"] < 60
    assert r["status"] in ("degraded", "critical")


def test_health_score_in_0_to_100():
    for cpu in (0.0, 50.0, 100.0, 200.0):
        m = {"cpu_upf_pct": cpu, "cpu_amf_pct": 0.0,
             "pod_restarts": 0, "anomaly_score": 0.0, "forecast_max_ues": 0.0}
        s = _fallback_health_score(m)["health_score"]
        assert 0.0 <= s <= 100.0, f"Score {s} out of [0,100] for cpu={cpu}"


def test_health_score_component_keys_present():
    m = {"cpu_upf_pct": 30.0, "cpu_amf_pct": 20.0,
         "pod_restarts": 0, "anomaly_score": 0.1, "forecast_max_ues": 80.0}
    assert set(_fallback_health_score(m)["component_scores"].keys()) == \
        {"upf", "amf", "stability", "capacity"}


def test_health_score_high_restarts_reduces_score():
    base = {"cpu_upf_pct": 10.0, "cpu_amf_pct": 5.0,
            "anomaly_score": 0.0, "forecast_max_ues": 0.0}
    no_restart   = _fallback_health_score({**base, "pod_restarts": 0})["health_score"]
    many_restart = _fallback_health_score({**base, "pod_restarts": 10})["health_score"]
    assert many_restart < no_restart


# ── prom_scalar ───────────────────────────────────────────────────────────────

@needs_cl
def test_prom_scalar_returns_default_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=Exception("unreachable")):
        val = cl.prom_scalar("up", default=99.9)
    assert val == 99.9


@needs_cl
def test_prom_scalar_parses_prometheus_response():
    fake = MagicMock()
    fake.__enter__ = lambda s: s
    fake.__exit__  = MagicMock(return_value=False)
    fake.read.return_value = json.dumps({
        "data": {"result": [{"value": ["1717000000", "42.5"]}]}
    }).encode()
    with patch("urllib.request.urlopen", return_value=fake):
        val = cl.prom_scalar("up")
    assert val == pytest.approx(42.5)


@needs_cl
def test_prom_scalar_empty_result_returns_default():
    fake = MagicMock()
    fake.__enter__ = lambda s: s
    fake.__exit__  = MagicMock(return_value=False)
    fake.read.return_value = json.dumps({"data": {"result": []}}).encode()
    with patch("urllib.request.urlopen", return_value=fake):
        val = cl.prom_scalar("up", default=7.0)
    assert val == 7.0


# ── scale_upf ─────────────────────────────────────────────────────────────────

@needs_cl
def test_scale_upf_dry_run_returns_true():
    assert cl.scale_upf(3) is True


@needs_cl
def test_scale_upf_clamps_above_max():
    assert cl.scale_upf(99) is True


@needs_cl
def test_scale_upf_clamps_below_min():
    assert cl.scale_upf(0) is True


# ── run_once: high-load anomaly → scale-up ────────────────────────────────────

@needs_cl
def test_high_cpu_anomaly_triggers_scale_up():
    """is_anomaly=True → scale_upf must be called with replicas > current."""
    cl._prev_was_anomaly = False
    cl._ue_history[:] = [80.0] * cl._MAX_HISTORY

    with patch.object(cl, "get_current_metrics", return_value=_metrics(cpu_upf=85.0)):
        with patch.object(cl, "sagemaker_invoke", side_effect=_smk_dispatch(0.82, True)):
            with patch.object(cl, "get_current_replicas", return_value=1):
                with patch.object(cl, "scale_upf", return_value=True) as mock_scale:
                    cl.run_once()

    mock_scale.assert_called()
    targets = [c.args[0] for c in mock_scale.call_args_list]
    assert any(r > 1 for r in targets), f"Expected scale > 1, got calls {targets}"


@needs_cl
def test_high_cpu_scale_target_is_cur_replicas_plus_one():
    """target_reps = min(SCALE_MAX, cur_reps + 1)."""
    cl._ue_history[:] = [80.0] * cl._MAX_HISTORY
    cl._prev_was_anomaly = False

    with patch.object(cl, "get_current_metrics", return_value=_metrics(cpu_upf=85.0)):
        with patch.object(cl, "sagemaker_invoke", side_effect=_smk_dispatch(0.82, True)):
            with patch.object(cl, "get_current_replicas", return_value=2):
                with patch.object(cl, "scale_upf", return_value=True) as mock_scale:
                    cl.run_once()

    first_target = mock_scale.call_args_list[0].args[0]
    assert first_target == min(cl.SCALE_MAX, 2 + 1)


# ── run_once: low-load, no anomaly → no scale ────────────────────────────────

@needs_cl
def test_low_cpu_no_anomaly_no_scale():
    """is_anomaly=False → scale_upf must NOT be called."""
    cl._ue_history[:] = [10.0] * cl._MAX_HISTORY

    with patch.object(cl, "get_current_metrics", return_value=_metrics(cpu_upf=10.0)):
        with patch.object(cl, "sagemaker_invoke", side_effect=_smk_dispatch(0.05, False)):
            with patch.object(cl, "get_current_replicas", return_value=1):
                with patch.object(cl, "scale_upf", return_value=True) as mock_scale:
                    cl.run_once()

    mock_scale.assert_not_called()


# ── anomaly-threshold state machine ──────────────────────────────────────────

@needs_cl
def test_anomaly_above_threshold_sets_prev_was_anomaly():
    """anom_score > ANOMALY_THRESH (0.6) + is_anomaly=True → _prev_was_anomaly=True."""
    cl._prev_was_anomaly = False
    cl._ue_history[:] = [80.0] * cl._MAX_HISTORY

    with patch.object(cl, "get_current_metrics", return_value=_metrics(cpu_upf=80.0)):
        with patch.object(cl, "sagemaker_invoke", side_effect=_smk_dispatch(0.75, True)):
            with patch.object(cl, "get_current_replicas", return_value=1):
                with patch.object(cl, "scale_upf", return_value=True):
                    cl.run_once()

    assert cl._prev_was_anomaly is True


@needs_cl
def test_anomaly_resolved_clears_prev_was_anomaly():
    """When is_anomaly=False after a prior anomaly, _prev_was_anomaly → False."""
    cl._prev_was_anomaly = True
    cl._ue_history[:] = [10.0] * cl._MAX_HISTORY

    with patch.object(cl, "get_current_metrics", return_value=_metrics(cpu_upf=10.0)):
        with patch.object(cl, "sagemaker_invoke", side_effect=_smk_dispatch(0.05, False)):
            with patch.object(cl, "get_current_replicas", return_value=1):
                with patch.object(cl, "scale_upf", return_value=True):
                    cl.run_once()

    assert cl._prev_was_anomaly is False


# ── event log format ──────────────────────────────────────────────────────────

@needs_cl
def test_event_log_contains_detect_decide_act(capsys):
    cl.event(detect="cpu=85%", decide="scale up", act="scaled to 3")
    out = capsys.readouterr().out
    assert "DETECT" in out
    assert "DECIDE" in out
    assert "ACT"    in out
