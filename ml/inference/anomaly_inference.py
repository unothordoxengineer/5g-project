"""
inference.py — Anomaly Detector (IsolationForest)
SageMaker sklearn container entry point.

Input (JSON):  {"cpu_upf": float, "upf_replicas": float, "cpu_amf": float}
Output (JSON): {"is_anomaly": bool, "anomaly_score": float}
"""

import os
import json
import joblib
import numpy as np

THRESHOLD = 0.5848932259184929   # from anomaly_meta.json
FEATURES  = ["cpu_upf", "upf_replicas", "cpu_amf"]


def model_fn(model_dir):
    """Load IsolationForest + scaler from model_dir."""
    clf    = joblib.load(os.path.join(model_dir, "isolation_forest.pkl"))
    scaler = joblib.load(os.path.join(model_dir, "anomaly_scaler.pkl"))
    return {"clf": clf, "scaler": scaler}


def input_fn(request_body, content_type="application/json"):
    """Deserialize request body."""
    if content_type == "application/json":
        return json.loads(request_body)
    raise ValueError(f"Unsupported content type: {content_type}")


def predict_fn(input_data, model):
    """Run anomaly detection; return score and flag."""
    clf    = model["clf"]
    scaler = model["scaler"]

    row = [[input_data.get(f, 0.0) for f in FEATURES]]
    X   = scaler.transform(row)

    # IsolationForest.decision_function: higher = more normal (negative = anomaly)
    raw_score    = float(clf.decision_function(X)[0])
    # Normalise to [0,1] anomaly score: 0=normal, 1=highly anomalous
    anomaly_score = max(0.0, min(1.0, 1.0 - (raw_score + 0.5)))
    is_anomaly    = anomaly_score >= THRESHOLD

    return {"is_anomaly": bool(is_anomaly), "anomaly_score": round(anomaly_score, 4)}


def output_fn(prediction, accept="application/json"):
    """Serialise prediction to JSON."""
    return json.dumps(prediction), "application/json"
