# Phase 8.6 — SageMaker ML Endpoints

## Overview

Three trained ML models are deployed as SageMaker real-time inference endpoints.
The closed-loop engine calls them via boto3 `sagemaker-runtime` using IRSA (no static credentials).

```
closed-loop pod (open5gs ns)
  │  boto3 sagemaker-runtime  [IRSA — 5g-core-closed-loop-sa-role]
  ├─► anomaly-detector-endpoint    → IsolationForest → is_anomaly + score
  ├─► traffic-forecaster-endpoint  → ARIMA(2,1,1)    → forecast_6h [12 steps]
  └─► state-classifier-endpoint   → KMeans+PCA      → cluster_id + cluster_name
```

## AWS Resources

| Resource | Name / ARN |
|---|---|
| IAM execution role | `arn:aws:iam::749534910877:role/5g-core-sagemaker-role` |
| S3 model bucket | `s3://5g-core-ml-models-749534910877` |
| Container image | `683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3` |
| Instance type | `ml.t2.medium` (1 per endpoint) |
| Region | `us-east-1` |

## Endpoints

| Endpoint | Model | Instance | Cost |
|---|---|---|---|
| `anomaly-detector-endpoint` | IsolationForest + scaler | ml.t2.medium | ~$0.065/hr |
| `traffic-forecaster-endpoint` | ARIMA(2,1,1) | ml.t2.medium | ~$0.065/hr |
| `state-classifier-endpoint` | KMeans k=6 + PCA(5) | ml.t2.medium | ~$0.065/hr |

**Total while running: ~$0.195/hr. Delete endpoints after stress tests.**

## Model S3 Paths

```
s3://5g-core-ml-models-749534910877/
├── models/anomaly/model.tar.gz      (520K)
├── models/forecaster/model.tar.gz   (4.0M)
└── models/classifier/model.tar.gz   (8.0K)
```

Each archive contains `inference.py` + model pickle files.
Inference scripts live at `ml/inference/`.

## Inference Schemas

### Anomaly Detector

```json
// Request
{"cpu_upf": 45.2, "upf_replicas": 2, "cpu_amf": 12.5}

// Response
{"is_anomaly": false, "anomaly_score": 0.2341}
```

### Traffic Forecaster

```json
// Request
{"sessions": [45.2, 47.1, 44.8, 50.3, 49.1, 48.7, 52.4, 51.0, 53.2, 50.8, 49.5, 51.3]}

// Response
{"forecast_6h": [51.8, 52.3, 53.1, 54.0, 53.5, 52.9, 51.7, 50.8, 50.2, 49.9, 49.5, 50.1]}
```

### State Classifier

```json
// Request (only known features needed; rest default to 0.0)
{"cpu_upf": 45.2, "cpu_amf": 12.5, "upf_replicas": 2, "ue_count": 0.0}

// Response
{"cluster_id": 0, "cluster_name": "STATE-0"}
```

Cluster states (from clustering_meta.json):
| Cluster ID | State Name | Description |
|---|---|---|
| 0 | STATE-0 | Baseline (3719 samples — most common) |
| 1 | STATE-4 | Moderate load (3588 samples) |
| 3 | STATE-2 | Medium-high load (2287 samples) |
| 2 | STATE-1 | High load (270 samples) |
| 4 | STATE-5 | Very high load (132 samples) |
| 5 | STATE-3 | Peak/anomalous (84 samples) |

## IRSA Setup

The closed-loop pod's ServiceAccount is annotated with:

```yaml
eks.amazonaws.com/role-arn: "arn:aws:iam::749534910877:role/5g-core-closed-loop-sa-role"
```

The role trust policy allows:
- Principal: OIDC provider `oidc.eks.us-east-1.amazonaws.com/id/38EB6671F7DB57BD52A5935A64ADFA71`
- Subject: `system:serviceaccount:open5gs:closed-loop-sa`

The inline policy grants only `sagemaker:InvokeEndpoint` on the 3 endpoint ARNs.

## Cost Management

```bash
# Delete all 3 endpoints (run immediately after stress tests)
for ep in anomaly-detector-endpoint traffic-forecaster-endpoint state-classifier-endpoint; do
  aws sagemaker delete-endpoint --endpoint-name $ep --region us-east-1
  echo "Deleted: $ep"
done

# Recreate when needed
aws sagemaker create-endpoint --endpoint-name anomaly-detector-endpoint \
  --endpoint-config-name anomaly-detector-config --region us-east-1
# ... (endpoint configs are retained, no need to re-create)
```

## Closed-Loop Engine

The engine (`automation/closed_loop.py`) now uses `boto3.client('sagemaker-runtime')`.
Docker image: `749534910877.dkr.ecr.us-east-1.amazonaws.com/5g-core/closed-loop:latest`

Key env vars in the Kubernetes deployment:
```
ANOMALY_ENDPOINT    = anomaly-detector-endpoint
FORECAST_ENDPOINT   = traffic-forecaster-endpoint
CLASSIFIER_ENDPOINT = state-classifier-endpoint
AWS_REGION          = us-east-1
```
