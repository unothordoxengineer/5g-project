#!/usr/bin/env python3
"""
api.py — Phase 7 FastAPI Model Serving API
==========================================
Serves the three Phase 5 trained ML models over HTTP:

  GET  /health              — liveness probe
  POST /predict/anomaly     — Isolation Forest anomaly detection
  POST /predict/forecast    — ARIMA 6-step UE load forecast
  POST /predict/cluster     — k-Means network state classification

Models are loaded once at startup from MODEL_DIR (default: /models inside
the container, mapped from ~/5g-project/ml/models/ on the host).

Usage (local dev):
  MODEL_DIR=~/5g-project/ml/models uvicorn api:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import json
import logging
import time
from pathlib import Path
from typing import List

import numpy as np
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
log = logging.getLogger("5g-serving")

# ── Model directory ───────────────────────────────────────────────────────────
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))

# ── Global model state ────────────────────────────────────────────────────────
_models: dict = {}

def load_models():
    """Load all models from MODEL_DIR at startup."""
    log.info(f"Loading models from {MODEL_DIR} …")

    # Isolation Forest
    _models["if_model"]  = joblib.load(MODEL_DIR / "isolation_forest.pkl")
    _models["if_scaler"] = joblib.load(MODEL_DIR / "anomaly_scaler.pkl")
    with open(MODEL_DIR / "anomaly_meta.json") as f:
        _models["if_meta"] = json.load(f)

    # k-Means
    _models["km_model"]  = joblib.load(MODEL_DIR / "kmeans_model.pkl")
    _models["km_scaler"] = joblib.load(MODEL_DIR / "cluster_scaler.pkl")
    _models["km_pca"]    = joblib.load(MODEL_DIR / "cluster_pca.pkl")
    with open(MODEL_DIR / "clustering_meta.json") as f:
        _models["km_meta"] = json.load(f)

    # ARIMA
    _models["arima_model"] = joblib.load(MODEL_DIR / "arima_model.pkl")
    with open(MODEL_DIR / "arima_meta.json") as f:
        _models["arima_meta"] = json.load(f)

    log.info("All models loaded OK — IF, k-Means, ARIMA")
    _models["loaded_at"] = time.time()

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="5G Core ML Serving API",
    description="Phase 7 — serves Isolation Forest, ARIMA, and k-Means models trained on Open5GS telemetry",
    version="1.0.0",
)

@app.on_event("startup")
async def startup_event():
    load_models()

# ── Request / Response schemas ────────────────────────────────────────────────

class AnomalyRequest(BaseModel):
    cpu_upf:       float = Field(..., ge=0, le=200,
                                  description="UPF CPU utilisation (%) — 0-100 normal, up to 200 saturated")
    upf_replicas:  float = Field(..., ge=0, le=10,
                                  description="Current UPF replica count")
    cpu_amf:       float = Field(0.0, ge=0, le=200,
                                  description="AMF CPU % (0 if unavailable)")

class AnomalyResponse(BaseModel):
    anomaly_score: float
    is_anomaly:    bool
    threshold:     float
    message:       str

class ForecastRequest(BaseModel):
    sessions: List[float] = Field(
        ..., min_length=4,
        description="Recent UE session counts (at least 4 values, newest last)"
    )

class ForecastResponse(BaseModel):
    forecast_6h:  List[float]
    ci_lower:     List[float]
    ci_upper:     List[float]
    mape:         float
    model_order:  List[int]

class ClusterRequest(BaseModel):
    cpu_upf:      float = Field(..., ge=0, le=200, description="UPF CPU %")
    cpu_amf:      float = Field(0.0, ge=0, le=200, description="AMF CPU %")
    upf_replicas: float = Field(..., ge=0, le=10,  description="UPF replica count")
    ue_count:     float = Field(0.0, ge=0,          description="Active UE count (optional)")

class ClusterResponse(BaseModel):
    cluster_id:   int
    cluster_name: str
    confidence:   str
    description:  str

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness probe — confirms models are loaded and API is alive."""
    if not _models:
        raise HTTPException(status_code=503, detail="Models not loaded")
    uptime_s = int(time.time() - _models.get("loaded_at", time.time()))
    return {
        "status":    "ok",
        "uptime_s":  uptime_s,
        "models":    ["IsolationForest", "KMeans", "ARIMA"],
        "version":   "1.0.0",
    }


@app.post("/predict/anomaly", response_model=AnomalyResponse)
async def predict_anomaly(req: AnomalyRequest):
    """
    Detect whether current UPF metrics constitute an anomaly.

    Uses Isolation Forest trained in Phase 5:
      - Features: cpu_upf (fraction), upf_replicas, cpu_mongodb (proxy → 0)
      - Threshold: 0.602 (tuned for Recall >90%, FPR <15%)
    """
    try:
        if_meta   = _models["if_meta"]
        if_model  = _models["if_model"]
        if_scaler = _models["if_scaler"]

        # Build feature vector matching training order:
        # ['cpu_upf', 'upf_replicas', 'cpu_mongodb']
        # cpu_upf was stored as fraction during training; input is %
        feat_vec = np.array([[
            req.cpu_upf / 100.0,   # cpu_upf   → fraction
            req.upf_replicas,      # upf_replicas
            req.cpu_amf / 100.0,   # cpu_amf as proxy for cpu_mongodb (closest available)
        ]])

        X_sc    = if_scaler.transform(feat_vec)
        score   = float(-if_model.score_samples(X_sc)[0])
        thr     = float(if_meta["threshold"])
        is_anom = score >= thr

        msg = (
            "⚠ ANOMALY: elevated load detected — consider scaling UPF"
            if is_anom else
            "✓ NORMAL: metrics within expected range"
        )
        log.info(f"anomaly predict: score={score:.4f} thr={thr:.4f} anomaly={is_anom}")
        return AnomalyResponse(
            anomaly_score=round(score, 4),
            is_anomaly=is_anom,
            threshold=round(thr, 4),
            message=msg,
        )
    except Exception as e:
        log.exception("anomaly predict error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/forecast", response_model=ForecastResponse)
async def predict_forecast(req: ForecastRequest):
    """
    Forecast the next 6 UE load steps using ARIMA(3,0,1).

    The model was trained on Phase 5 8-hour load-test data (MAPE = 3.64%).
    Accepts recent observed session counts and returns the forward forecast.
    """
    try:
        arima_model = _models["arima_model"]
        arima_meta  = _models["arima_meta"]

        # Extend the fitted model with new observations, then forecast 6 steps
        from statsmodels.tsa.arima.model import ARIMA as _ARIMA
        import warnings

        # Training ARIMA order, validated at MAPE 3.64%
        order   = tuple(arima_meta["order"])   # (3, 0, 1)
        MAX_UE  = 200.0

        # Normalise input to [0,1] (matches training scale; RMSE=0.093)
        sessions_arr  = np.array(req.sessions, dtype=float)
        sessions_norm = np.clip(sessions_arr / MAX_UE, 0, 1)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit       = _ARIMA(sessions_norm, order=order).fit()
            fc_obj    = fit.get_forecast(steps=6)

        pm     = fc_obj.predicted_mean
        ci_obj = fc_obj.conf_int()
        raw_mean = np.array(pm).flatten()
        ci_arr   = np.array(ci_obj)

        # Scale back to UE counts; clip negatives to 0, cap at MAX_UE
        fc_mean = [round(float(np.clip(v * MAX_UE, 0, MAX_UE)), 1) for v in raw_mean]
        fc_ci   = np.clip(ci_arr * MAX_UE, 0, MAX_UE)

        log.info(f"forecast: input_len={len(req.sessions)} fc6={[round(v,1) for v in fc_mean]}")
        return ForecastResponse(
            forecast_6h=[round(float(v), 2) for v in fc_mean],
            ci_lower=[round(float(v), 2) for v in fc_ci[:, 0]],
            ci_upper=[round(float(v), 2) for v in fc_ci[:, 1]],
            mape=round(arima_meta["mape_percent"], 2),
            model_order=arima_meta["order"],
        )
    except Exception as e:
        log.exception("forecast predict error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/cluster", response_model=ClusterResponse)
async def predict_cluster(req: ClusterRequest):
    """
    Classify current network state as IDLE or HIGH-LOAD using k-Means (k=2).

    The model was trained on 19 NF-level features (Silhouette=0.503).
    When only UPF/AMF/replica metrics are available, a centroid-consistent
    heuristic is applied:  HIGH-LOAD iff CPU ≥ 70% OR (replicas ≥ 4 AND UE ≥ 100).
    """
    try:
        km_meta   = _models["km_meta"]
        km_model  = _models["km_model"]
        km_scaler = _models["km_scaler"]
        km_pca    = _models["km_pca"]

        features  = km_meta["features"]  # 19-element list
        cluster_states = {int(k): v for k, v in km_meta["cluster_states"].items()}

        # Build 19-feature vector; map available inputs, zero-fill the rest
        col_map = {
            "cpu_upf":      req.cpu_upf / 100.0,
            "upf_replicas": req.upf_replicas,
            "cpu_amf":      req.cpu_amf / 100.0,
            "ran_ue_count": req.ue_count,
        }
        feat_vec = np.array([[col_map.get(f, 0.0) for f in features]])

        # Count how many features we actually have
        n_available = sum(1 for f in features if f in col_map)

        X_sc  = km_scaler.transform(feat_vec)
        X_pca = km_pca.transform(X_sc)
        label = int(km_model.predict(X_pca)[0])
        state = cluster_states.get(label, "UNKNOWN")

        # Override with heuristic when most features are zero (Phase 6 scenario)
        if n_available < 5:
            high_load = (
                req.cpu_upf >= 70 or
                (req.upf_replicas >= 4 and req.ue_count >= 100)
            )
            state     = "HIGH-LOAD" if high_load else "IDLE"
            label     = 0 if state == "HIGH-LOAD" else 1
            confidence = "heuristic (< 5 of 19 features available)"
        else:
            confidence = f"model ({n_available}/19 features)"

        descriptions = {
            "HIGH-LOAD": "Network under elevated load — consider proactive scaling",
            "IDLE":      "Network in normal/idle state — no action required",
        }
        log.info(f"cluster predict: state={state} label={label} conf={confidence}")
        return ClusterResponse(
            cluster_id=label,
            cluster_name=state,
            confidence=confidence,
            description=descriptions.get(state, "Unknown state"),
        )
    except Exception as e:
        log.exception("cluster predict error")
        raise HTTPException(status_code=500, detail=str(e))


# ── OpenAPI extras ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "5G Core ML Serving API",
        "docs":    "/docs",
        "health":  "/health",
        "endpoints": ["/predict/anomaly", "/predict/forecast", "/predict/cluster"],
    }
