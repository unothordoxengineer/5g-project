#!/bin/bash
# =============================================================================
# aws-start.sh — Full Phase 8 restart for 5G Core on EKS
#
# What this does (in order):
#   1.  Re-create NAT Gateways via Terraform
#   1b. Fix private subnet route tables → new NAT GW IDs
#   2.  Scale EKS nodes to 3
#   3.  Wait for all 3 nodes Ready
#   4.  Remove cloud-provider uninitialized taints
#   5.  Restart / wait for open5gs pods
#   6.  Re-enable EKS control-plane logging
#   7.  (Optional) Re-enable CloudWatch Container Insights addon
#   8.  Restore Grafana ALB Ingress
#   9.  Verify UE registration (ping 8.8.8.8 through 5G core)
#   10. Print estimated cost/hour breakdown
#
# Usage:
#   ./aws-start.sh                  # restart without CloudWatch (saves ~$0.02/hr)
#   ./aws-start.sh --with-cloudwatch # also re-enable Container Insights addon
# =============================================================================
set -e

CLUSTER=5g-core-eks
NODEGROUP=5g-core-workers-20260521093630186200000022
REGION=us-east-1
TF_DIR="$(cd "$(dirname "$0")/../terraform" && pwd)"
WITH_CW=false

for arg in "$@"; do
  [ "$arg" = "--with-cloudwatch" ] && WITH_CW=true
done

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          AWS 5G Core — Phase 8 Full Restart                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "Timestamp  : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Cluster    : $CLUSTER"
echo "Nodegroup  : $NODEGROUP"
echo "CloudWatch : $( [ "$WITH_CW" = true ] && echo 'ENABLED (--with-cloudwatch)' || echo 'SKIPPED (pass --with-cloudwatch to enable)' )"
echo ""

# ── 1. Re-create NAT Gateways via Terraform ───────────────────────────────────
echo "[1/10] Re-creating NAT Gateways via Terraform..."
echo "       (NAT gateways were deleted during shutdown — Terraform recreates them)"
cd "$TF_DIR"
terraform state rm 'aws_nat_gateway.main[0]' 'aws_nat_gateway.main[1]' 2>/dev/null || true
terraform apply \
  -target='aws_nat_gateway.main[0]' \
  -target='aws_nat_gateway.main[1]' \
  -auto-approve 2>&1 | tail -6
echo "       NAT Gateways created."
cd - >/dev/null

# ── 1b. Fix private subnet route tables ───────────────────────────────────────
echo ""
echo "[1b/10] Fixing private subnet route tables → new NAT GW IDs..."

# Wait up to 60 s for NAT GWs to reach 'available'
echo "        Waiting for NAT GWs to become available..."
for i in $(seq 1 12); do
  NAT_COUNT=$(aws ec2 describe-nat-gateways \
    --filter "Name=state,Values=available" \
    --query 'length(NatGateways)' --output text --region "$REGION" 2>/dev/null || echo 0)
  [ "$NAT_COUNT" -ge 2 ] && break
  sleep 5
done

# us-east-1a — public subnet subnet-06e81ed8f65e1b44b
NAT_1A=$(aws ec2 describe-nat-gateways \
  --filter "Name=subnet-id,Values=subnet-06e81ed8f65e1b44b" "Name=state,Values=available" \
  --query 'NatGateways[0].NatGatewayId' --output text --region "$REGION" 2>/dev/null)

# us-east-1b — public subnet subnet-0e5ccd8928c0e674a
NAT_1B=$(aws ec2 describe-nat-gateways \
  --filter "Name=subnet-id,Values=subnet-0e5ccd8928c0e674a" "Name=state,Values=available" \
  --query 'NatGateways[0].NatGatewayId' --output text --region "$REGION" 2>/dev/null)

if [ -n "$NAT_1A" ] && [ "$NAT_1A" != "None" ]; then
  aws ec2 replace-route \
    --route-table-id rtb-0adb38539192fd36f \
    --destination-cidr-block 0.0.0.0/0 \
    --nat-gateway-id "$NAT_1A" --region "$REGION"
  echo "        rtb-0adb38539192fd36f (us-east-1a) → $NAT_1A"
  (cd "$TF_DIR" && terraform import 'aws_nat_gateway.main[0]' "$NAT_1A" 2>/dev/null) || true
else
  echo "        WARNING: No available NAT GW found for us-east-1a"
fi

if [ -n "$NAT_1B" ] && [ "$NAT_1B" != "None" ]; then
  aws ec2 replace-route \
    --route-table-id rtb-0a8fb46bbffbaee89 \
    --destination-cidr-block 0.0.0.0/0 \
    --nat-gateway-id "$NAT_1B" --region "$REGION"
  echo "        rtb-0a8fb46bbffbaee89 (us-east-1b) → $NAT_1B"
  (cd "$TF_DIR" && terraform import 'aws_nat_gateway.main[1]' "$NAT_1B" 2>/dev/null) || true
else
  echo "        WARNING: No available NAT GW found for us-east-1b"
fi

# ── 2. Scale EKS nodes to 3 ────────────────────────────────────────────────────
echo ""
echo "[2/10] Scaling EKS nodes to 3..."
aws eks update-nodegroup-config \
  --cluster-name "$CLUSTER" \
  --nodegroup-name "$NODEGROUP" \
  --scaling-config minSize=1,maxSize=6,desiredSize=3 \
  --region "$REGION" \
  --query 'update.{id:id,status:status}' \
  --output table

# ── 3. Wait for nodes Ready ────────────────────────────────────────────────────
echo ""
echo "[3/10] Waiting for 3 nodes to become Ready (up to 10 min)..."
READY=0
ATTEMPTS=0
while [ "$READY" -lt 3 ] && [ "$ATTEMPTS" -lt 40 ]; do
  sleep 15
  READY=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || true)
  ATTEMPTS=$((ATTEMPTS + 1))
  echo "        Nodes ready: $READY/3  (attempt $ATTEMPTS/40)"
done
if [ "$READY" -lt 3 ]; then
  echo "        WARNING: Only $READY/3 nodes ready after 10 min — continuing anyway"
else
  echo "        All 3 nodes Ready!"
fi

# ── 4. Remove cloud-provider uninitialized taints ─────────────────────────────
echo ""
echo "[4/10] Removing cloud-provider uninitialized taints..."
for node in $(kubectl get nodes -o name 2>/dev/null); do
  kubectl taint node "$node" \
    node.cloudprovider.kubernetes.io/uninitialized:NoSchedule- 2>/dev/null && \
    echo "        Untainted: $node" || true
done

# ── 5. Wait for open5gs pods ──────────────────────────────────────────────────
echo ""
echo "[5/10] Waiting for open5gs pods to be Running (up to 5 min)..."
kubectl wait --for=condition=Ready pod --all -n open5gs --timeout=300s 2>&1 || {
  echo "        Timeout — restarting deployments..."
  kubectl rollout restart deployment -n open5gs 2>/dev/null || true
  sleep 30
}

RUNNING=$(kubectl get pods -n open5gs --no-headers 2>/dev/null | grep -c "1/1" || true)
TOTAL=$(kubectl get pods -n open5gs --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "        open5gs: $RUNNING/$TOTAL Running"

# Also restart closed-loop automation pod
echo "        Restarting closed-loop automation..."
kubectl rollout restart deployment/closed-loop-engine -n open5gs 2>/dev/null && \
  echo "        closed-loop-engine restarted." || true

# ── 6. Re-enable EKS control-plane logging ────────────────────────────────────
echo ""
echo "[6/10] Re-enabling EKS control-plane logging..."
aws eks update-cluster-config --name "$CLUSTER" --region "$REGION" \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}' \
  --query 'update.{id:id,status:status}' --output table 2>&1 || \
  echo "        (logging already enabled)"

# ── 7. Optionally re-enable CloudWatch Container Insights ─────────────────────
echo ""
if [ "$WITH_CW" = true ]; then
  echo "[7/10] Re-enabling CloudWatch Container Insights addon..."
  aws eks create-addon \
    --cluster-name "$CLUSTER" \
    --addon-name amazon-cloudwatch-observability \
    --region "$REGION" \
    --query 'addon.status' --output text 2>&1 || echo "        (already enabled)"
else
  echo "[7/10] CloudWatch Container Insights SKIPPED (re-run with --with-cloudwatch to enable)"
fi

# ── 8. Restore Grafana ALB Ingress ────────────────────────────────────────────
echo ""
echo "[8/10] Restoring Grafana ALB Ingress..."
cat <<'INGRESS_EOF' | kubectl apply -f - 2>&1
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
INGRESS_EOF

# ── 9. Verify UE registration ─────────────────────────────────────────────────
echo ""
echo "[9/10] Verifying UE registration (ping 8.8.8.8 through 5G core)..."
UE_POD=$(kubectl get pod -n open5gs -l app=ueransim-ue \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | head -1)

if [ -n "$UE_POD" ]; then
  echo "        UE pod: $UE_POD"
  PING_OUT=$(kubectl exec -n open5gs "$UE_POD" -- ping -c 4 -W 3 8.8.8.8 2>&1 || true)
  echo "$PING_OUT" | tail -5
  if echo "$PING_OUT" | grep -q "4 received\|3 received\|2 received\|1 received"; then
    echo "        ✅ UE REGISTERED — data plane working"
  else
    echo "        ⚠️  UE ping failed — check AMF/UPF logs:"
    echo "           kubectl logs -n open5gs deploy/open5gs-amf --tail=30"
    echo "           kubectl logs -n open5gs deploy/open5gs-upf --tail=30"
  fi
else
  echo "        ⚠️  No UERANSIM UE pod found — verify pod labels"
fi

# ── 10. Print cost/hour breakdown ─────────────────────────────────────────────
echo ""
echo "[10/10] Estimated cost while running:"

NAT_COUNT=$(aws ec2 describe-nat-gateways \
  --filter "Name=state,Values=available" \
  --query 'length(NatGateways)' --output text --region "$REGION" 2>/dev/null || echo 0)
NODE_COUNT=3

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         RUNNING COST ESTIMATE (us-east-1)                ║"
echo "╠═══════════════════════════════════════════════════════════╣"
printf "║  EKS Control Plane           \$0.10/hr                   ║\n"
printf "║  EC2 t3.medium × %d            \$0.12/hr (×%d = \$%.2f/hr)  ║\n" \
  "$NODE_COUNT" "$NODE_COUNT" "$(echo "$NODE_COUNT * 0.0416" | bc 2>/dev/null || echo 0.12)"
printf "║  NAT Gateway × %d             \$0.04/hr each              ║\n" "$NAT_COUNT"
printf "║  NAT data transfer           ~\$0.01/hr (est.)            ║\n"
if [ "$WITH_CW" = true ]; then
  printf "║  CloudWatch Insights         ~\$0.02/hr                   ║\n"
fi
echo "╠═══════════════════════════════════════════════════════════╣"
TOTAL_PER_HR="0.10 + 3*0.0416 + $NAT_COUNT*0.045 + 0.01"
echo "║  TOTAL (approx)              ~\$0.30–0.40/hr              ║"
echo "║                              ~\$7.00–9.60/day             ║"
echo "╚═══════════════════════════════════════════════════════════╝"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                START COMPLETE                            ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "Useful commands:"
echo "  kubectl get pods -n open5gs                    # pod health"
echo "  kubectl get pods -n monitoring                  # Grafana"
echo "  kubectl logs -n open5gs deploy/closed-loop-engine --tail=50"
echo ""
echo "Grafana (ALB provisioning ~2 min):"
echo "  kubectl get ingress grafana -n monitoring"
echo ""
echo "Port-forward alternative:"
echo "  kubectl port-forward svc/grafana 3000:80 -n monitoring"
echo "  open http://localhost:3000  (admin/admin)"
echo ""
echo "When done — run shutdown to stop billing:"
echo "  cd $(dirname "$0") && ./aws-stop.sh"
