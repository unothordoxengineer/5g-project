FROM python:3.11-slim

LABEL description="5G Core Closed-Loop Automation Engine — Phase 8.6 (SageMaker)"
LABEL version="2.0.0"

WORKDIR /app

# Install boto3 for SageMaker runtime invocations
RUN pip install --no-cache-dir boto3==1.34.69

# Install kubectl (linux/amd64 for EKS t3.medium nodes)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -LO "https://dl.k8s.io/release/$(curl -LS https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY closed_loop.py .

ENV PYTHONUNBUFFERED=1
ENV LOG_FILE=/logs/closed_loop.log
ENV AWS_REGION=us-east-1

RUN mkdir -p /logs

CMD ["python3", "closed_loop.py"]
