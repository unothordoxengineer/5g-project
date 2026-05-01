# Terraform — Phase 8 AWS Infrastructure

Complete Infrastructure-as-Code for the Cloud-Native 5G SA Core AWS migration.

## What gets created

| File | Resources |
|------|-----------|
| `vpc.tf` | VPC, 2 public + 2 private subnets across 2 AZs, NAT GW × 2, route tables, EKS node SG |
| `ecr.tf` | 15 ECR repositories (14 NF images + serving API), lifecycle policies, pull permissions |
| `iam.tf` | EKS cluster role, EKS node group role, SageMaker execution role, GitHub Actions OIDC role, Cluster Autoscaler IRSA, EBS CSI IRSA, AWS LBC IRSA |
| `eks.tf` | EKS 1.30 cluster, managed node group (3× t3.medium), EBS CSI add-on, gp3 StorageClass, Cluster Autoscaler Helm chart, AWS Load Balancer Controller |
| `sagemaker.tf` | 3× SageMaker endpoints (IF, ARIMA, k-Means), endpoint auto-scaling 1→3 instances |
| `monitoring.tf` | AMP workspace, alerting rules, AMG workspace (Grafana 10.4), CloudWatch Container Insights |
| `outputs.tf` | All endpoint URLs, ECR URLs, kubectl config command, deployment summary |

---

## Prerequisites

```bash
# 1. Install tools
brew install terraform awscli eksctl

# 2. Configure AWS credentials
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: us-east-1

# 3. Verify credentials
aws sts get-caller-identity
```

---

## Deploy

### Step 1 — Initialise providers

```bash
cd ~/5g-project/terraform
terraform init
```

### Step 2 — Review what will be created

```bash
terraform plan -out=tfplan
```

### Step 3 — Apply (creates all AWS resources ~15 min)

```bash
terraform apply tfplan
```

### Step 4 — Configure kubectl

```bash
# Terraform prints this command at the end; also available as output:
aws eks update-kubeconfig --name 5g-core-eks --region us-east-1
kubectl get nodes
```

### Step 5 — Push Docker images to ECR

```bash
# Login
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com

# Tag and push (example: ML serving API)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"

docker tag 5g-serving-api:latest ${REGISTRY}/5g-core/5g-serving-api:latest
docker push ${REGISTRY}/5g-core/5g-serving-api:latest
```

### Step 6 — Deploy Kubernetes manifests

```bash
cd ~/5g-project

# Update image references from kind-local to ECR
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"

sed -i "s|image: 5g-serving-api:latest|image: ${REGISTRY}/5g-core/5g-serving-api:latest|g" \
  k8s/serving/serving-deployment.yaml
sed -i "s|imagePullPolicy: Never|imagePullPolicy: Always|g" \
  k8s/serving/serving-deployment.yaml

kubectl apply -f k8s/serving/serving-deployment.yaml
kubectl apply -f k8s/serving/closed-loop-deployment.yaml
```

### Step 7 — Verify

```bash
# EKS nodes
kubectl get nodes

# Pods
kubectl get pods -n open5gs

# ML serving API
kubectl get svc -n open5gs ml-serving-api
# Use the EXTERNAL-IP (ALB) or NodePort

# SageMaker endpoints
aws sagemaker list-endpoints --region us-east-1

# Test anomaly endpoint via SageMaker
aws sagemaker-runtime invoke-endpoint \
  --endpoint-name 5g-core-anomaly-detector \
  --content-type application/json \
  --body '{"cpu_upf":95.0,"upf_replicas":5,"cpu_amf":40.0}' \
  --region us-east-1 /tmp/out.json && cat /tmp/out.json
```

---

## Useful outputs

```bash
# View all outputs
terraform output

# Individual outputs
terraform output eks_cluster_endpoint
terraform output ecr_repository_urls
terraform output amp_workspace_endpoint
terraform output amg_workspace_url
terraform output configure_kubectl
```

---

## Tear down

```bash
# Delete all AWS resources (irreversible — confirm when prompted)
terraform destroy
```

> **Cost note:** Running 3× t3.medium nodes + 2 NAT GWs + 3 SageMaker ml.t2.medium endpoints costs ~$10–15/day. Destroy when not in use.

---

## Variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `aws_region` | `us-east-1` | AWS region |
| `environment` | `dev` | dev / staging / prod |
| `cluster_name` | `5g-core-eks` | EKS cluster name |
| `kubernetes_version` | `1.30` | Kubernetes version |
| `node_instance_type` | `t3.medium` | EC2 instance type for workers |
| `node_group_desired` | `3` | Desired worker node count |
| `node_group_min` | `1` | Min worker nodes (autoscaler) |
| `node_group_max` | `6` | Max worker nodes (autoscaler) |
| `sagemaker_instance_type` | `ml.t2.medium` | SageMaker inference instance |
| `sagemaker_model_bucket` | `` | S3 bucket for model artifacts |
| `amp_retention_days` | `30` | AMP metrics retention |

Override any variable:
```bash
terraform apply \
  -var="aws_region=eu-west-1" \
  -var="node_instance_type=t3.large" \
  -var="node_group_desired=4"
```

---

## Architecture

```
AWS Account
├── VPC 10.0.0.0/16
│   ├── Public subnets (AZ-a, AZ-b)  ← ALB, NAT GW
│   └── Private subnets (AZ-a, AZ-b) ← EKS nodes, SageMaker
│
├── EKS Cluster (5g-core-eks, k8s 1.30)
│   ├── Node Group: 3× t3.medium
│   ├── Add-ons: CoreDNS, kube-proxy, VPC CNI, EBS CSI
│   ├── open5gs namespace → 14 NF pods + HPA on UPF
│   └── Cluster Autoscaler → scales 1–6 nodes
│
├── ECR → 15 repositories
│
├── SageMaker
│   ├── anomaly-detector endpoint (Isolation Forest)
│   ├── load-forecaster endpoint (ARIMA 3,0,1)
│   └── state-classifier endpoint (k-Means k=2)
│
└── Monitoring
    ├── AMP workspace ← Prometheus remote_write from EKS
    └── AMG workspace (Grafana 10.4) ← AMP data source
```
