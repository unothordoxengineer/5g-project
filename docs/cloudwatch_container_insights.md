# CloudWatch Container Insights — Phase 8.4

## Overview

AWS CloudWatch Container Insights is enabled on the EKS cluster to provide
full observability for the 5G core network functions (Open5GS NFs, UERANSIM gNB/UEs).

## Setup (completed 2026-05-22)

### EKS Addon

```bash
aws eks create-addon \
  --cluster-name 5g-core-eks \
  --addon-name amazon-cloudwatch-observability \
  --region us-east-1
```

- Addon version: `v5.4.0-eksbuild.1`
- Namespace: `amazon-cloudwatch`
- Status: `ACTIVE`

### IAM Policy

Attached `CloudWatchAgentServerPolicy` to both node group roles:
- `5g-core-workers-eks-node-group-20260521092643988700000015`
- `5g-core-eks-node-group-role`

```bash
aws iam attach-role-policy \
  --role-name <node-group-role> \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
```

## Running Components (`amazon-cloudwatch` namespace)

| Pod | Role |
|-----|------|
| `amazon-cloudwatch-observability-controller-manager-*` | Addon controller |
| `cloudwatch-agent-*` (×3, one per node) | Collects container metrics |
| `fluent-bit-*` (×3, one per node) | Ships container logs to CloudWatch Logs |

## Metrics

- **Namespace:** `ContainerInsights`
- **Total metrics:** 279 cluster-wide, **388 scoped to `open5gs` namespace**
- **Per-pod metrics available for:** `amf`, `gnb`, `ue`, `ue2`, `ue3`, `ausf`, `smf`, `upf`, etc.

### Key metric names

| Metric | Description |
|--------|-------------|
| `pod_status_running` | Pod running count per namespace/deployment |
| `pod_memory_working_set` | Memory usage per pod |
| `container_memory_utilization` | Container memory % vs limit |
| `pod_cpu_utilization` | CPU % per pod |
| `replicas_ready` | Ready replica count (tracks HPA) |

## CloudWatch Console

Navigate to: **CloudWatch → Container Insights → Performance monitoring**

Select:
- **Cluster:** `5g-core-eks`
- **Namespace:** `open5gs`

View per-NF CPU/memory metrics for AMF, SMF, UPF, gNB, UE1/UE2/UE3.

## Log Groups

Container logs are shipped by Fluent Bit to:
- `/aws/containerinsights/5g-core-eks/application` — application logs
- `/aws/containerinsights/5g-core-eks/host` — node-level logs
- `/aws/containerinsights/5g-core-eks/dataplane` — Kubernetes dataplane logs
