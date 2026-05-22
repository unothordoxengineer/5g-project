#!/usr/bin/env bash
# =============================================================================
# build-nef.sh — Build and deploy the 5G NEF (Network Exposure Function)
#
# Usage (from project root):
#   bash scripts/build-nef.sh
#
# What it does:
#   1. Build the 5g-nef:latest Docker image
#   2. Load it into the KinD cluster (imagePullPolicy: Never)
#   3. Apply K8s manifests (NetworkPolicies + Deployment + Services)
#   4. Wait for the NEF pod to become ready
#   5. Run smoke tests (health, auth, ue-status)
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEF_DIR="$PROJECT_ROOT/nef"
K8S_NEF_DIR="$PROJECT_ROOT/k8s/nef"
CLUSTER_NAME="open5gs"
IMAGE_NAME="5g-nef:latest"

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $*"; }
fail() { echo "[$(date '+%H:%M:%S')] ❌ $*" >&2; exit 1; }

# ── 1. Build Docker image ─────────────────────────────────────────────────────
log "Building $IMAGE_NAME from $NEF_DIR ..."
docker build -t "$IMAGE_NAME" "$NEF_DIR" || fail "Docker build failed"
ok "Docker image built: $IMAGE_NAME"

# ── 2. Load into KinD ─────────────────────────────────────────────────────────
log "Loading image into KinD cluster '$CLUSTER_NAME' ..."
kind load docker-image "$IMAGE_NAME" --name "$CLUSTER_NAME" || fail "kind load failed"
ok "Image loaded into KinD"

# ── 3. Apply updated NetworkPolicies (adds NEF rules to AMF/PCF/SMF/MongoDB) ─
log "Applying updated NetworkPolicies ..."
kubectl apply -f "$PROJECT_ROOT/k8s/security/network-policies.yaml" || fail "network-policies apply failed"
ok "NetworkPolicies applied"

# ── 4. Apply NEF-specific NetworkPolicies ─────────────────────────────────────
log "Applying NEF NetworkPolicies ..."
kubectl apply -f "$K8S_NEF_DIR/nef-network-policy.yaml" || fail "nef-network-policy apply failed"
ok "NEF NetworkPolicies applied"

# ── 5. Deploy NEF ─────────────────────────────────────────────────────────────
log "Deploying NEF (ConfigMap, Secret, Deployment, Services) ..."
kubectl apply -f "$K8S_NEF_DIR/nef-deployment.yaml" || fail "nef-deployment apply failed"
ok "NEF manifests applied"

# ── 6. Wait for pod ready ─────────────────────────────────────────────────────
log "Waiting for NEF pod to become Ready (timeout 120s) ..."
kubectl rollout status deployment/nef -n open5gs --timeout=120s || fail "NEF deployment timed out"
ok "NEF pod is Ready"

NEF_POD=$(kubectl get pod -n open5gs -l app=nef -o jsonpath='{.items[0].metadata.name}')
log "Pod: $NEF_POD"

# ── 7. Smoke tests ────────────────────────────────────────────────────────────
log "Running smoke tests ..."

# Health check
HEALTH=$(kubectl exec -n open5gs "$NEF_POD" -- \
  bash -c 'curl -s http://localhost:8080/health' 2>/dev/null)
echo "$HEALTH" | grep -q '"status":"ok"' && ok "Health check passed" || \
  { log "Health response: $HEALTH"; fail "Health check failed"; }

# Auth — get JWT token
log "Testing OAuth2 token issuance ..."
TOKEN_RESP=$(kubectl exec -n open5gs "$NEF_POD" -- \
  bash -c 'curl -s -X POST http://localhost:8080/auth/token \
    -d "grant_type=client_credentials&client_id=demo-app&client_secret=demo-secret-2026"' 2>/dev/null)
ACCESS_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || true)
if [ -n "$ACCESS_TOKEN" ]; then
  ok "JWT token obtained (${#ACCESS_TOKEN} chars)"
else
  log "Token response: $TOKEN_RESP"
  fail "Token issuance failed"
fi

# UE status (will query MongoDB — may return 404 if IMSI not found, that's OK)
log "Testing GET /ue-status/999700000000001 ..."
STATUS_CODE=$(kubectl exec -n open5gs "$NEF_POD" -- \
  bash -c "curl -s -o /dev/null -w '%{http_code}' \
    -H 'Authorization: Bearer $ACCESS_TOKEN' \
    http://localhost:8080/ue-status/999700000000001" 2>/dev/null)
if [[ "$STATUS_CODE" == "200" || "$STATUS_CODE" == "404" ]]; then
  ok "UE status endpoint reachable (HTTP $STATUS_CODE)"
else
  fail "UE status endpoint returned unexpected HTTP $STATUS_CODE"
fi

# Subscribe
log "Testing POST /subscribe ..."
SUB_CODE=$(kubectl exec -n open5gs "$NEF_POD" -- \
  bash -c "curl -s -o /dev/null -w '%{http_code}' \
    -X POST http://localhost:8080/subscribe \
    -H 'Authorization: Bearer $ACCESS_TOKEN' \
    -H 'Content-Type: application/json' \
    -d '{\"event_types\":[\"UE_ATTACH\",\"UE_DETACH\"],\"callback_url\":\"http://example.com/hook\"}'" 2>/dev/null)
[[ "$SUB_CODE" == "201" ]] && ok "Subscribe endpoint reachable (HTTP $SUB_CODE)" || \
  fail "Subscribe endpoint returned HTTP $SUB_CODE"

# QoS Policy
log "Testing POST /qos-policy ..."
QOS_CODE=$(kubectl exec -n open5gs "$NEF_POD" -- \
  bash -c "curl -s -o /dev/null -w '%{http_code}' \
    -X POST http://localhost:8080/qos-policy \
    -H 'Authorization: Bearer $ACCESS_TOKEN' \
    -H 'Content-Type: application/json' \
    -d '{\"imsi\":\"999700000000001\",\"apn\":\"internet\",\"flows\":[{\"qos_class\":\"NON_GBR_DEFAULT\",\"priority\":5}]}'" 2>/dev/null)
[[ "$QOS_CODE" == "202" ]] && ok "QoS policy endpoint reachable (HTTP $QOS_CODE)" || \
  fail "QoS policy endpoint returned HTTP $QOS_CODE"

# ── 8. Port-forward for manual testing ───────────────────────────────────────
NEF_NODE_PORT=30880
log ""
ok "NEF deployed and all smoke tests passed!"
log ""
log "  NodePort: http://localhost:$NEF_NODE_PORT (requires kubectl port-forward or direct node access)"
log "  Swagger docs: http://localhost:8080/docs (inside pod)"
log ""
log "  To port-forward NEF for local testing:"
log "    kubectl port-forward -n open5gs svc/nef-external 8880:80"
log ""
log "  Quick API test:"
log "    TOKEN=\$(curl -s -X POST http://localhost:8880/auth/token \\"
log "      -d 'grant_type=client_credentials&client_id=demo-app&client_secret=demo-secret-2026' \\"
log "      | python3 -c \"import sys,json; print(json.load(sys.stdin)['access_token'])\")"
log ""
log "    curl -s -H \"Authorization: Bearer \$TOKEN\" \\"
log "      http://localhost:8880/ue-status/999700000000001 | python3 -m json.tool"
log ""
log "    curl -s -X POST -H \"Authorization: Bearer \$TOKEN\" \\"
log "      -H 'Content-Type: application/json' http://localhost:8880/subscribe \\"
log "      -d '{\"event_types\":[\"UE_ATTACH\"],\"callback_url\":\"http://localhost:9999/hook\"}'"
