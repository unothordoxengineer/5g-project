#!/bin/bash
# =============================================================================
# aws-start.sh — Resume 5G core AWS resources
# Re-creates NAT gateways via Terraform, scales EKS back to 3 nodes,
# re-enables CloudWatch Insights, waits for all pods to be Ready
# =============================================================================
set -e

CLUSTER=5g-core-eks
NODEGROUP=5g-core-workers-20260521093630186200000022
REGION=us-east-1
TF_DIR="$(cd "$(dirname "$0")/../terraform" && pwd)"

echo "=== AWS 5G Core START script ==="
echo "Timestamp: $(date -u)"
echo ""

# ── 1. Re-create NAT gateways via Terraform ──────────────────────────────────
echo "[1/6] Re-creating NAT gateways via Terraform..."
echo "      (NAT gateways were deleted to save cost — Terraform recreates them)"
cd "$TF_DIR"
terraform apply -target=aws_nat_gateway.nat -auto-approve 2>&1 | tail -5
echo "      NAT gateways ready."
cd - >/dev/null

# ── 2. Scale EKS nodes back to 3 ────────────────────────────────────────────
echo ""
echo "[2/6] Scaling EKS nodes to 3..."
aws eks update-nodegroup-config \
  --cluster-name $CLUSTER \
  --nodegroup-name $NODEGROUP \
  --scaling-config minSize=1,maxSize=6,desiredSize=3 \
  --region $REGION \
  --query 'update.{id:id,status:status}' \
  --output table

# ── 3. Wait for nodes to be Ready ────────────────────────────────────────────
echo ""
echo "[3/6] Waiting for 3 nodes to become Ready..."
READY=0
while [ $READY -lt 3 ]; do
  sleep 15
  READY=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
  echo "      Nodes ready: $READY/3"
done
echo "      All 3 nodes Ready!"

# ── 4. Remove cloud-provider uninitialized taint if present ─────────────────
echo ""
echo "[4/6] Removing cloud-provider uninitialized taints..."
for node in $(kubectl get nodes -o name); do
  kubectl taint node "$node" node.cloudprovider.kubernetes.io/uninitialized:NoSchedule- 2>/dev/null && \
    echo "      Untainted: $node" || true
done

# ── 5. Restart pods (they were in Pending while nodes were at 0) ─────────────
echo ""
echo "[5/6] Waiting for open5gs pods to be Running..."
kubectl wait --for=condition=Ready pod --all -n open5gs --timeout=300s 2>&1 || \
  kubectl rollout restart deployment -n open5gs

RUNNING=$(kubectl get pods -n open5gs --no-headers 2>/dev/null | grep -c "1/1" || echo 0)
TOTAL=$(kubectl get pods -n open5gs --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "      open5gs: $RUNNING/$TOTAL Running"

# ── 6. Re-enable CloudWatch Container Insights ───────────────────────────────
echo ""
echo "[6/6] Re-enabling CloudWatch Container Insights..."
aws eks create-addon \
  --cluster-name $CLUSTER \
  --addon-name amazon-cloudwatch-observability \
  --region $REGION \
  --query 'addon.status' --output text 2>&1 || echo "      (already enabled)"

# ── Restore Grafana ALB Ingress ──────────────────────────────────────────────
cat <<EOF | kubectl apply -f - 2>&1
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}]'
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: grafana
                port:
                  number: 80
EOF

echo ""
echo "=== START COMPLETE ==="
echo ""
echo "Cluster ready. Next steps:"
echo "  1. Verify pods:   kubectl get pods -n open5gs"
echo "  2. Run traffic:   kubectl exec -n open5gs deploy/ue -- ping -c 5 8.8.8.8"
echo ""
echo "  Grafana (ALB provisioning ~2 min):"
echo "    kubectl get ingress grafana -n monitoring"
echo ""
echo "  Or port-forward:"
echo "    kubectl port-forward svc/grafana 3000:80 -n monitoring"
echo "    open http://localhost:3000  (admin/admin)"
