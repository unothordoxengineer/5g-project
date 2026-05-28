FROM python:3.11-slim

LABEL description="5G Core Closed-Loop Automation Engine — Phase 8.7 (SageMaker + Bedrock)"
LABEL version="3.0.0"

WORKDIR /app

# Install Python dependencies:
#   boto3  — SageMaker runtime + Bedrock runtime + SNS + S3
RUN pip install --no-cache-dir boto3==1.34.69

# Install kubectl (linux/amd64 for EKS t3.medium nodes)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -LO "https://dl.k8s.io/release/$(curl -LS https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copy both engine modules
COPY closed_loop.py .
COPY bedrock_advisor.py .

ENV PYTHONUNBUFFERED=1
ENV LOG_FILE=/logs/closed_loop.log
ENV AWS_REGION=us-east-1
ENV BEDROCK_REGION=us-east-1
ENV BEDROCK_ENABLED=true
ENV BEDROCK_PRIMARY_MODEL=us.anthropic.claude-sonnet-4-6
ENV BEDROCK_FALLBACK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
ENV S3_BUCKET=5g-core-ml-models-749534910877
ENV SNS_TOPIC_ARN=arn:aws:sns:us-east-1:749534910877:5g-core-network-alerts

RUN mkdir -p /logs

CMD ["python3", "closed_loop.py"]
