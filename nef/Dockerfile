# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="5G NEF API" \
      org.opencontainers.image.description="5G Network Exposure Function — external API layer" \
      org.opencontainers.image.version="1.0.0"

# Non-root user for security
RUN useradd -r -u 1001 -g root nef

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/

# The container runs as non-root; port 8080 is non-privileged
RUN chown -R nef:root /app
USER nef

EXPOSE 8080

# Uvicorn: 1 worker per container (scale via Kubernetes replicas)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
