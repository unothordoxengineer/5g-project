# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Nigel Kadzunga <nigelkadzinga91@gmail.com>"
LABEL description="5G Core ML Serving API — Phase 7"
LABEL version="1.0.0"

WORKDIR /app

COPY --from=builder /install /usr/local
COPY api.py .

# Embed models at build time (self-contained for kind/demo deployment).
# In production (EKS), override MODEL_DIR to point to a mounted PVC/EFS.
COPY models/ /models/

ENV MODEL_DIR=/models
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /models
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
