FROM python:3.11-slim

LABEL description="5G Core Closed-Loop Automation Engine — Phase 7"
LABEL version="1.0.0"

WORKDIR /app

# Install kubectl
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -LO "https://dl.k8s.io/release/$(curl -LS https://dl.k8s.io/release/stable.txt)/bin/linux/arm64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY closed_loop.py .

ENV PYTHONUNBUFFERED=1
ENV LOG_FILE=/logs/closed_loop.log

RUN mkdir -p /logs

CMD ["python3", "closed_loop.py"]
