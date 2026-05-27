FROM python:3.11-slim

LABEL description="5G Core ML Inference Container — sklearn 1.8.0 BYOC"
LABEL version="1.1.0"

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

# SageMaker BYOC: container is started with `docker run <image> serve`
# The 'serve' executable must be in PATH and must start the inference server on port 8080
RUN printf '#!/bin/bash\ncd /\nexec gunicorn --bind 0.0.0.0:8080 --workers 1 --worker-class sync --timeout 120 serve:app\n' \
    > /usr/local/bin/serve && chmod +x /usr/local/bin/serve

WORKDIR /
EXPOSE 8080

ENV SM_MODEL_DIR=/opt/ml/model
ENV PYTHONUNBUFFERED=1

# Default CMD (used when running locally without the SageMaker 'serve' command)
CMD ["serve"]
