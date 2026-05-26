# Phase 8.5 — AWS Monitoring: AMP + Grafana

## Overview

All 5G core metrics flow from Open5GS pods → Prometheus → AWS Managed Prometheus (AMP)
and are visualised in Grafana with 4 live dashboards.

## Architecture

```
Open5GS pods (open5gs ns)
    │  container_cpu, container_memory, kube_pod_*
    ▼
Prometheus (monitoring/prometheus-prometheus-prometheus-0)
    │  scrapeInterval: 15s  │  22 active targets (all up=1)
    │
    ├─► local queries (port 9090) ──► Grafana (datasource uid=AMP)
    │
    └─► remote_write SigV4 ──────► AMP workspace ws-6f6aefa7-9c99-423a-afc3-65ef0832f154
                                     us-east-1  │  217 MB written
```

## AWS Managed Prometheus (AMP)

| Field | Value |
|---|---|
| Workspace ID | `ws-6f6aefa7-9c99-423a-afc3-65ef0832f154` |
| Region | `us-east-1` |
| Remote-write URL | `https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-6f6aefa7.../api/v1/remote_write` |
| Auth | IRSA SigV4 — `5g-core-prometheus-amp-role` |
| IAM role ARN | `arn:aws:iam::749534910877:role/5g-core-prometheus-amp-role` |
| Samples written | 5.3 M (as of 2026-05-26) |
| Bytes written | 217 MB |

### IRSA Setup

The Prometheus service account (`monitoring/prometheus`) is annotated with the AMP role:

```yaml
eks.amazonaws.com/role-arn: "arn:aws:iam::749534910877:role/5g-core-prometheus-amp-role"
```

The pod uses `AWS_WEB_IDENTITY_TOKEN_FILE` to sign remote_write requests with SigV4 — no static credentials needed.

## Grafana

| Field | Value |
|---|---|
| External URL | `http://k8s-monitori-grafana-aeaf182df5-1554284079.us-east-1.elb.amazonaws.com` |
| Admin credentials | `admin / admin` |
| Ingress | ALB internet-facing (AWS LB Controller) |
| Datasource | `AMP` → `http://prometheus-prometheus.monitoring.svc.cluster.local:9090` |

### Dashboards

| # | Title | UID | Key Panels |
|---|---|---|---|
| 1 | NF CPU & Memory | `nf-cpu-memory` | CPU rate timeseries, memory working set, CPU % limit bargauge |
| 2 | UE Sessions & Slices | `ue-sessions` | UE readiness, NF readiness, per-UE throughput, per-slice throughput |
| 3 | HPA Autoscaling | `autoscaling` | Current/max replicas stat, HPA history, UPF CPU usage |
| 4 | GTP-U Throughput | `throughput` | UPF GTP-U, gNB N3, per-slice DL, cluster total |

All dashboards source from the `AMP` datasource (uid: `AMP`).

## IAM Fixes Applied During Cluster Recovery (2026-05-25/26)

During a cluster crash recovery, three IAM gaps were discovered and fixed:

### 1. Node Role — EKS Authenticator ec2:DescribeInstances
**Problem:** EKS aws-iam-authenticator resolves `{{EC2PrivateDNSName}}` template by calling `ec2:DescribeInstances` using the **cluster role** (not node role). The cluster role lacked this permission.

**Fix:** Added inline policy `eks-authenticator-describe-instances` to cluster role `5g-core-eks-cluster-20260521092607545600000001`:
```json
{"Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*"}
```

### 2. Node Role — EKS Worker + CNI Policies
**Problem:** Node role `5g-core-workers-eks-node-group-20260521092643988700000015` was missing:
- `AmazonEKSWorkerNodePolicy` — required for kubelet EC2 metadata API calls
- `AmazonEKS_CNI_Policy` — required for aws-node (VPC CNI) to manage ENIs

**Fix:**
```bash
aws iam attach-role-policy --role-name 5g-core-workers-eks-node-group-20260521092643988700000015 \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
aws iam attach-role-policy --role-name 5g-core-workers-eks-node-group-20260521092643988700000015 \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
```

### 3. Launch Template — Missing Cluster Security Group
**Problem:** Launch template `lt-05dc0687379a2dee3` v1 only had node SGs; cluster SG `sg-083a44190aedbf71a` was missing. Without it, kubelet can't reach the EKS private API endpoint.

**Fix:** Created v2 (then v4 without IamInstanceProfile) adding `sg-083a44190aedbf71a`.

### 4. Cloud Provider Taint
**Problem:** New nodes had `node.cloudprovider.kubernetes.io/uninitialized: true` NoSchedule taint that the EKS CCM didn't remove automatically.

**Fix:**
```bash
kubectl taint node <node> node.cloudprovider.kubernetes.io/uninitialized:NoSchedule-
```

## Verified Live Metrics (2026-05-26)

```
container_cpu_usage_seconds_total{namespace="open5gs"}: 16 series (all 16 NFs)
container_memory_working_set_bytes{namespace="open5gs"}: 16 series
kube_pod_status_ready{namespace="open5gs", condition="true"}: 16 (all 1.0)
kube_horizontalpodautoscaler_status_current_replicas: 1
prometheus_remote_storage_bytes_total: 217,876,625 bytes → AMP
up (all targets): 22/22
```

Network slice traffic test:
```
UE1 (eMBB SST=1):  3/3 pings → 8.8.8.8  0% loss  avg 1.3ms
UE2 (mMTC SST=2):  3/3 pings → 8.8.8.8  0% loss  avg 1.4ms
UE3 (URLLC SST=3): 3/3 pings → 8.8.8.8  0% loss  avg 1.3ms
```
