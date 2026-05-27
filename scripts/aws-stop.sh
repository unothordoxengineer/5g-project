#!/bin/bash
# =============================================================================
# aws-stop.sh — Emergency cost-stop for 5G core AWS resources
# Scales EKS to 0, deletes NAT gateways, removes CloudWatch Insights
#
# Remaining fixed costs while stopped:
#   EKS control plane:  ~$2.40/day  ($0.10/hr)
#   2× EIP (reserved):  ~$0.22/day  ($0.005/hr each, if kept)
#   EBS volumes:        ~$0.10/day  (5 GiB PV + storage)
#   AMP workspace:      ~$0.00/day  (free tier if no ingestion)
#   ALB (Grafana):      ~$0.19/day  ($0.008/hr)
#   ────────────────────────────────
#   TOTAL STOPPED:      ~$2.91/day
# =============================================================================
set -e

CLUSTER=5g-core-eks
NODEGROUP=5g-core-workers-20260521093630186200000022
REGION=us-east-1

echo "=== AWS 5G Core STOP script ==="
echo "Timestamp: $(date -u)"
echo ""

# ── 1. Scale EKS nodes to 0 ─────────────────────────────────────────────────
echo "[1/4] Scaling EKS nodes to 0..."
aws eks update-nodegroup-config \
  --cluster-name $CLUSTER \
  --nodegroup-name $NODEGROUP \
  --scaling-config minSize=0,maxSize=6,desiredSize=0 \
  --region $REGION \
  --query 'update.{id:id,status:status}' \
  --output table
echo "      Nodes scaling to 0 (~3 min). Saves ~$3.00/day (3× t3.medium)"

# ── 2. Delete NAT gateways ───────────────────────────────────────────────────
echo ""
echo "[2/4] Deleting NAT gateways..."
NAT_IDS=$(aws ec2 describe-nat-gateways --region $REGION \
  --filter Name=state,Values=available \
  --query 'NatGateways[].NatGatewayId' --output text)

if [ -z "$NAT_IDS" ]; then
  echo "      No active NAT gateways found (already deleted)."
else
  for NAT_ID in $NAT_IDS; do
    aws ec2 delete-nat-gateway --nat-gateway-id $NAT_ID --region $REGION \
      --query 'NatGatewayId' --output text
    echo "      Deleted: $NAT_ID"
  done
  echo "      Saves ~\$2.16/day (2× NAT gateways at \$0.045/hr each)"
  # Remove from Terraform state so aws-start.sh can recreate cleanly
  TF_DIR="$(cd "$(dirname "$0")/../terraform" && pwd)"
  (cd "$TF_DIR" && terraform state rm 'aws_nat_gateway.main[0]' 'aws_nat_gateway.main[1]' 2>/dev/null && \
    echo "      Terraform state cleaned up (NAT GW entries removed)") || true
fi

# ── 3. Disable CloudWatch Container Insights ─────────────────────────────────
echo ""
echo "[3/4] Disabling CloudWatch Container Insights addon..."
if aws eks describe-addon --cluster-name $CLUSTER --addon-name amazon-cloudwatch-observability \
   --region $REGION --query 'addon.status' --output text 2>/dev/null | grep -qE "ACTIVE|CREATING"; then
  aws eks delete-addon --cluster-name $CLUSTER \
    --addon-name amazon-cloudwatch-observability \
    --region $REGION --query 'addon.status' --output text
  echo "      Deleted. Saves ~\$1.78/day (CloudWatch metrics ingestion)"
else
  echo "      Already disabled."
fi

# ── 4. Delete Grafana ALB Ingress (optional — saves $0.19/day) ──────────────
echo ""
echo "[4/4] Checking Grafana Ingress ALB..."
if kubectl get ingress grafana -n monitoring &>/dev/null 2>&1; then
  kubectl delete ingress grafana -n monitoring 2>&1 && \
    echo "      Grafana ALB ingress deleted. Saves ~\$0.19/day" || \
    echo "      Could not delete (kubectl not connected — nodes already at 0)"
else
  echo "      Grafana ingress not found (already deleted)."
fi

echo ""
echo "=== STOP COMPLETE ==="
echo ""
echo "Cost summary while stopped:"
echo "  EKS control plane : ~\$2.40/day (unavoidable)"
echo "  EBS volumes       : ~\$0.10/day"
echo "  AMP workspace     : ~\$0.00/day (no ingestion)"
echo "  ─────────────────────────────"
echo "  TOTAL             : ~\$2.50/day"
echo ""
echo "To resume: bash scripts/aws-start.sh"
