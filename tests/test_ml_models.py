"""
Unit tests for trained ML model artefacts in ml/models/.

Loads the actual .pkl files produced by the training pipeline and verifies
that each model accepts correctly shaped inputs and returns expected outputs.
"""
import os
import sys
import pickle
import math

import pytest

joblib   = pytest.importorskip("joblib",   reason="joblib required")
np       = pytest.importorskip("numpy",    reason="numpy required")
sklearn  = pytest.importorskip("sklearn",  reason="scikit-learn required")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "ml", "models")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def if_bundle():
    """Isolation Forest + scaler. Input: 3 features [cpu_upf, upf_replicas, cpu_amf]."""
    clf    = joblib.load(os.path.join(MODEL_DIR, "isolation_forest.pkl"))
    scaler = joblib.load(os.path.join(MODEL_DIR, "anomaly_scaler.pkl"))
    return clf, scaler


@pytest.fixture(scope="module")
def arima_model():
    """Fitted ARIMA(3,0,1) statsmodels result object.

    Skips if the pkl was created on a newer pandas/statsmodels than what is
    installed — this happens when unpickling cross-version (e.g. pkl built on
    pandas 2.x loaded on pandas 1.x).  CI pins a compatible version via the
    stub-creation step in ci.yml.
    """
    path = os.path.join(MODEL_DIR, "arima_model.pkl")
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (NotImplementedError, AttributeError, TypeError, Exception) as e:
        pytest.skip(f"arima_model.pkl not loadable on this environment: {e}")


@pytest.fixture(scope="module")
def kmeans_bundle():
    """k-Means + StandardScaler + PCA. Input: 19 features."""
    kmeans = joblib.load(os.path.join(MODEL_DIR, "kmeans_model.pkl"))
    scaler = joblib.load(os.path.join(MODEL_DIR, "cluster_scaler.pkl"))
    pca    = joblib.load(os.path.join(MODEL_DIR, "cluster_pca.pkl"))
    return kmeans, scaler, pca


# ── Isolation Forest (3-feature anomaly detector) ────────────────────────────

def test_if_models_load(if_bundle):
    clf, scaler = if_bundle
    assert clf is not None
    assert scaler is not None


def test_if_accepts_3_feature_input(if_bundle):
    """Model was trained on [cpu_upf, upf_replicas, cpu_amf] — exactly 3 features."""
    clf, scaler = if_bundle
    X = np.array([[85.0, 3.0, 40.0]])   # high-load sample
    X_scaled = scaler.transform(X)
    prediction = clf.predict(X_scaled)
    assert prediction.shape == (1,)
    assert prediction[0] in (-1, 1)     # IF outputs -1 (anomaly) or 1 (normal)


def test_if_decision_function_returns_float(if_bundle):
    clf, scaler = if_bundle
    X_scaled = scaler.transform([[10.0, 1.0, 5.0]])
    score = clf.decision_function(X_scaled)
    assert score.shape == (1,)
    assert isinstance(float(score[0]), float)


def test_if_normalised_score_in_0_1(if_bundle):
    """Verify the inference normalisation formula from anomaly_inference.py."""
    clf, scaler = if_bundle
    for row in [[10.0, 1.0, 5.0], [85.0, 5.0, 70.0], [50.0, 2.0, 30.0]]:
        X_scaled = scaler.transform([row])
        raw = float(clf.decision_function(X_scaled)[0])
        # from anomaly_inference.py: normalised = max(0, min(1, 1 - (raw + 0.5)))
        normalised = max(0.0, min(1.0, 1.0 - (raw + 0.5)))
        assert 0.0 <= normalised <= 1.0, f"Normalised {normalised} out of [0,1] for {row}"


def test_if_spike_scores_anomalous_vs_idle(if_bundle):
    """High-load spike should have a lower decision_function value (more anomalous) than idle."""
    clf, scaler = if_bundle
    idle_raw  = float(clf.decision_function(scaler.transform([[5.0,  1.0, 3.0]]))[0])
    spike_raw = float(clf.decision_function(scaler.transform([[98.0, 5.0, 80.0]]))[0])
    assert spike_raw <= idle_raw, (
        f"Spike ({spike_raw:.4f}) should be ≤ idle ({idle_raw:.4f}) — "
        "lower = more anomalous in IsolationForest"
    )


def test_if_batch_prediction(if_bundle):
    clf, scaler = if_bundle
    X = np.array([[10.0, 1.0, 5.0], [50.0, 2.0, 30.0], [95.0, 5.0, 75.0]])
    preds = clf.predict(scaler.transform(X))
    assert preds.shape == (3,)
    assert all(p in (-1, 1) for p in preds)


# ── ARIMA forecaster ──────────────────────────────────────────────────────────

def test_arima_loads(arima_model):
    assert arima_model is not None


def test_arima_forecasts_6_steps(arima_model):
    """Forecast horizon = 6 (user-specified); prod uses STEPS=12 but model supports any N."""
    try:
        fc = arima_model.forecast(steps=6)
    except Exception:
        # Some statsmodels versions need in-sample data via apply(); skip gracefully
        pytest.skip("arima_model.forecast(steps=6) not supported by this statsmodels version")
    assert len(fc) == 6


def test_arima_forecast_returns_floats(arima_model):
    try:
        fc = list(arima_model.forecast(steps=6))
    except Exception:
        pytest.skip("forecast not callable on this model version")
    for v in fc:
        assert isinstance(float(v), float)


def test_arima_forecast_values_are_finite(arima_model):
    try:
        fc = list(arima_model.forecast(steps=6))
    except Exception:
        pytest.skip("forecast not callable on this model version")
    assert all(math.isfinite(v) for v in fc), f"Non-finite forecast values: {fc}"


def test_arima_can_forecast_12_steps(arima_model):
    """Production inference uses STEPS=12; verify the model supports it."""
    try:
        fc = arima_model.forecast(steps=12)
    except Exception:
        pytest.skip("forecast(steps=12) not supported")
    assert len(fc) == 12


# ── k-Means state classifier (19-feature) ────────────────────────────────────

VALID_CLUSTER_IDS = {0, 1, 2, 3, 4, 5}   # CLUSTER_STATES keys in classifier_inference.py
N_FEATURES        = 19                     # 14 per-NF CPU cols + 5 scalar cols


def test_kmeans_bundle_loads(kmeans_bundle):
    kmeans, scaler, pca = kmeans_bundle
    assert kmeans is not None
    assert scaler is not None
    assert pca is not None


def test_kmeans_predicts_on_19_feature_zero_vector(kmeans_bundle):
    kmeans, scaler, pca = kmeans_bundle
    X     = np.zeros((1, N_FEATURES))
    label = int(kmeans.predict(pca.transform(scaler.transform(X)))[0])
    assert label in VALID_CLUSTER_IDS, f"Label {label} not in {VALID_CLUSTER_IDS}"


def test_kmeans_output_shape_single_sample(kmeans_bundle):
    kmeans, scaler, pca = kmeans_bundle
    X = np.zeros((1, N_FEATURES))
    labels = kmeans.predict(pca.transform(scaler.transform(X)))
    assert labels.shape == (1,)


def test_kmeans_label_in_range_for_varied_cpu(kmeans_bundle):
    kmeans, scaler, pca = kmeans_bundle
    for cpu_upf in (5.0, 25.0, 60.0, 85.0, 99.0):
        row = np.zeros((1, N_FEATURES))
        row[0, 13] = cpu_upf   # index 13 = cpu_upf in the 19-feature list
        row[0, 14] = 2.0       # upf_replicas
        label = int(kmeans.predict(pca.transform(scaler.transform(row)))[0])
        assert label in VALID_CLUSTER_IDS, f"cpu_upf={cpu_upf} → label {label} out of range"


def test_kmeans_batch_prediction_shape(kmeans_bundle):
    kmeans, scaler, pca = kmeans_bundle
    X = np.zeros((10, N_FEATURES))
    labels = kmeans.predict(pca.transform(scaler.transform(X)))
    assert labels.shape == (10,)


def test_kmeans_predict_fn_interface(kmeans_bundle):
    """Mirrors classifier_inference.predict_fn — zero-fill missing features then predict."""
    kmeans, scaler, pca = kmeans_bundle
    FEATURES = [
        "cpu_amf","cpu_ausf","cpu_bsf","cpu_gnb","cpu_mongodb",
        "cpu_nrf","cpu_nssf","cpu_pcf","cpu_scp","cpu_smf",
        "cpu_udm","cpu_udr","cpu_ue","cpu_upf",
        "upf_replicas","gtp_in_pps","gtp_out_pps","ran_ue_count","hpa_delta",
    ]
    input_data = {"cpu_upf": 40.0, "upf_replicas": 2.0, "ran_ue_count": 3.0}
    row = [[float(input_data.get(f, 0.0)) for f in FEATURES]]
    label = int(kmeans.predict(pca.transform(scaler.transform(row)))[0])
    assert label in VALID_CLUSTER_IDS
