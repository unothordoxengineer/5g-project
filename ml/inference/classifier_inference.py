"""
inference.py — Network State Classifier (KMeans + PCA)
SageMaker sklearn container entry point.

Input (JSON):  {"cpu_upf": float, "cpu_amf": float,
                "upf_replicas": float, "ue_count": float,
                ... any subset of the 39 training features ...}
Output (JSON): {"cluster_id": int, "cluster_name": str}
"""

import os
import json
import joblib
import numpy as np


# Must match clustering_meta.json order exactly
FEATURES = [
    "cpu_amf","cpu_ausf","cpu_bsf","cpu_gnb","cpu_mongodb",
    "cpu_nrf","cpu_nssf","cpu_pcf","cpu_scp","cpu_smf",
    "cpu_udm","cpu_udr","cpu_ue","cpu_upf",
    "mem_amf","mem_ausf","mem_bsf","mem_gnb","mem_mongodb",
    "mem_nrf","mem_nssf","mem_pcf","mem_scp","mem_smf",
    "mem_udm","mem_udr","mem_ue","mem_upf",
    "upf_replicas","gtp_in_pps","gtp_out_pps","ran_ue_count",
    "cpu_amf_roll5m","cpu_amf_roll5std",
    "cpu_ausf_roll5m","cpu_ausf_roll5std",
    "cpu_bsf_roll5m","cpu_bsf_roll5std",
    "hpa_delta",
]

CLUSTER_STATES = {
    0: "STATE-0",
    2: "STATE-1",
    3: "STATE-2",
    5: "STATE-3",
    1: "STATE-4",
    4: "STATE-5",
}


def model_fn(model_dir):
    kmeans = joblib.load(os.path.join(model_dir, "kmeans_model.pkl"))
    scaler = joblib.load(os.path.join(model_dir, "cluster_scaler.pkl"))
    pca    = joblib.load(os.path.join(model_dir, "cluster_pca.pkl"))
    return {"kmeans": kmeans, "scaler": scaler, "pca": pca}


def input_fn(request_body, content_type="application/json"):
    if content_type == "application/json":
        return json.loads(request_body)
    raise ValueError(f"Unsupported content type: {content_type}")


def predict_fn(input_data, model):
    kmeans = model["kmeans"]
    scaler = model["scaler"]
    pca    = model["pca"]

    # Build feature vector; zero-fill missing features
    row = [[float(input_data.get(f, 0.0)) for f in FEATURES]]
    X   = scaler.transform(row)
    X   = pca.transform(X)
    cluster_id = int(kmeans.predict(X)[0])
    cluster_name = CLUSTER_STATES.get(cluster_id, f"STATE-{cluster_id}")

    return {"cluster_id": cluster_id, "cluster_name": cluster_name}


def output_fn(prediction, accept="application/json"):
    return json.dumps(prediction), "application/json"
