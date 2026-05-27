FROM python:3.11-slim

LABEL description="5G Core ML Inference Container — sklearn 1.8.0 BYOC"
LABEL version="1.0.0"

# Install exact versions matching the training environment (sklearn 1.8.0)
RUN pip install --no-cache-dir \
    scikit-learn==1.8.0 \
    joblib \
    numpy \
    scipy \
    statsmodels \
    flask==3.0.3 \
    gunicorn==22.0.0

COPY serve.py /serve.py

WORKDIR /
EXPOSE 8080

ENV SM_MODEL_DIR=/opt/ml/model
ENV PYTHONUNBUFFERED=1

# gunicorn: 1 worker (model is loaded once), 60s timeout for cold starts
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--worker-class", "sync", \
     "--timeout", "120", \
     "--preload", \
     "serve:app"]
