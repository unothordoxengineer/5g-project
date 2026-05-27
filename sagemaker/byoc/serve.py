#!/usr/bin/env python3
"""
serve.py — SageMaker BYOC inference server (sklearn 1.8.0 compatible)

Implements the SageMaker real-time endpoint container interface:
  GET  /ping        → 200 OK (health check)
  POST /invocations → prediction JSON

SageMaker extracts model.tar.gz to SM_MODEL_DIR (/opt/ml/model).
inference.py is co-located there and is imported dynamically.
"""
import os
import sys
import json
import logging

import flask

MODEL_DIR = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
sys.path.insert(0, MODEL_DIR)          # so `import inference` finds inference.py

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = flask.Flask(__name__)
_model = None          # cached model object


def _get_model():
    """Load model on first call; cache thereafter."""
    global _model
    if _model is None:
        from inference import model_fn          # loaded from MODEL_DIR
        log.info("Loading model from %s", MODEL_DIR)
        _model = model_fn(MODEL_DIR)
        log.info("Model loaded successfully")
    return _model


@app.route("/ping", methods=["GET"])
def ping():
    """SageMaker health check — must return 200 for endpoint to go InService."""
    try:
        _get_model()
        return flask.Response(response="OK\n", status=200, mimetype="text/plain")
    except Exception as exc:
        log.exception("Health check failed")
        return flask.Response(response=str(exc), status=500, mimetype="text/plain")


@app.route("/invocations", methods=["POST"])
def invocations():
    """Run a single synchronous inference request."""
    try:
        content_type = flask.request.content_type or "application/json"
        body = flask.request.get_data(as_text=True)

        # Import once (model-specific) — Python caches the module
        from inference import input_fn, predict_fn, output_fn

        model = _get_model()
        input_data = input_fn(body, content_type)
        prediction = predict_fn(input_data, model)
        response_body, accept = output_fn(prediction, "application/json")

        return flask.Response(
            response=response_body,
            status=200,
            mimetype="application/json",
        )
    except Exception as exc:
        log.exception("Invocation error")
        return flask.Response(
            response=json.dumps({"error": str(exc)}),
            status=500,
            mimetype="application/json",
        )


# ── Gunicorn entrypoint ──────────────────────────────────────────────────────
# Workers call this on startup (worker_init hook not needed — lazy load on /ping)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log.info("Starting dev server on port %d", port)
    _get_model()          # eager load before serving
    app.run(host="0.0.0.0", port=port)
