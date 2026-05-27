"""
inference.py — Traffic Forecaster (ARIMA)
SageMaker sklearn container entry point.

Input (JSON):  {"sessions": [list of floats, min 6 values]}
Output (JSON): {"forecast_6h": [list of floats, 12 values]}
"""

import os
import json
import pickle
import numpy as np


STEPS = 12   # 12 × 30 s = 6 min in live loop; represents "6h" token in closed_loop


def model_fn(model_dir):
    """Load fitted ARIMA model."""
    with open(os.path.join(model_dir, "arima_model.pkl"), "rb") as f:
        model = pickle.load(f)
    return model


def input_fn(request_body, content_type="application/json"):
    if content_type == "application/json":
        return json.loads(request_body)
    raise ValueError(f"Unsupported content type: {content_type}")


def predict_fn(input_data, model):
    """Produce STEPS-ahead forecast.

    Strategy: use the model's apply() to attach new observations, then forecast.
    Falls back to plain model.forecast() if apply fails (e.g. shape mismatch).
    """
    sessions = input_data.get("sessions", [])
    if not sessions:
        return {"forecast_6h": [0.0] * STEPS}

    sessions = [float(v) for v in sessions]

    try:
        # Refit on new observations for a live estimate
        updated = model.apply(sessions)
        fc = updated.forecast(steps=STEPS)
    except Exception:
        try:
            fc = model.forecast(steps=STEPS)
        except Exception:
            fc = [float(sessions[-1])] * STEPS

    fc_list = [round(float(v), 2) for v in fc]
    return {"forecast_6h": fc_list}


def output_fn(prediction, accept="application/json"):
    return json.dumps(prediction), "application/json"
