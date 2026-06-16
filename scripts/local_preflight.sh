#!/usr/bin/env bash
# local_preflight.sh — Pre-flight health check for kind-based 5G SA Core demo
#
# Usage:
#   bash scripts/local_preflight.sh
#
# Checks:
#   1. Docker daemon is running
#   2. kubectl binary is available
#   3. kind cluster 'open5gs' exists
#   4. kubectl context is set to kind-open5gs (auto-switches if not)
#   5. open5gs namespace exists
#   6. All 15 expected pods are Running + Ready
#   7. No pods are crash-looping (restart count > 2)
#   8. Prometheus / Grafana pods are running (monitoring namespace)
#   9. network-query-api pod is running
#
# Exits with code 0 if all hard checks pass, non-zero otherwise.

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

# ── Helpers ───────────────────────────────────────────────────────────────────
header() { echo -e "\n${BOLD}${BLUE}── $1 ──────────────────────────────────────────────${NC}"; }
pass()   { echo -e "  ${GREEN}✔ PASS${NC}  $1"; }
warn()   { echo -e "  ${YELLOW}⚠ WARN${NC}  $1"; WARNINGS=$((WARNINGS + 1)); }
fail()   { echo -e "  ${RED}✗ FAIL${NC}  $1"; ERRORS=$((ERRORS + 1)); }
fix()    { echo -e "          ${YELLOW}→${NC} $1"; }

echo -e "\n${BOLD}5G SA Core — Local Demo Pre-flight Check${NC}"
echo -e "$(date '+%Y-%m-%d %H:%M:%S')\n"

# ─── 1. Docker ───────────────────────────────────────────────────────────────
header "1 · Docker daemon"
if docker info &>/dev/null; then
    DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
    pass "Docker is running (server v${DOCKER_VER})"
else
    fail "Docker daemon is not running"
    fix "Open Docker Desktop from /Applications, wait for the whale icon to stop animating, then re-run."
    echo -e "\n${RED}${BOLD}Cannot continue without Docker.${NC}\n"
    exit 1
fi

# ─── 2. kubectl ──────────────────────────────────────────────────────────────
header "2 · kubectl"
if command -v kubectl &>/dev/null; then
    KUBE_VER=$(kubectl version --client -o json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['clientVersion']['gitVersion'])" 2>/dev/null || echo "unknown")
    pass "kubectl found (${KUBE_VER})"
else
    fail "kubectl not found in PATH"
    fix "brew install kubectl"
    exit 1
fi

# ─── 3. kind CLI + cluster ───────────────────────────────────────────────────
header "3 · kind cluster 'open5gs'"
CLUSTER="open5gs"
EXPECTED_CTX="kind-${CLUSTER}"

if ! command -v kind &>/dev/null; then
    fail "kind not found in PATH"
    fix "brew install kind"
    ERRORS=$((ERRORS + 1))
elif kind get clusters 2>/dev/null | grep -q "^${CLUSTER}$"; then
    pass "kind cluster '${CLUSTER}' exists"
else
    fail "kind cluster '${CLUSTER}' does not exist"
    fix "kind create cluster --name ${CLUSTER} --config k8s/kind-config.yaml"
    fix "Then deploy: kubectl apply -f k8s/manifests/ -n open5gs"
    echo -e "\n${RED}${BOLD}Cluster missing — remaining checks skipped.${NC}\n"
    exit 1
fi

# ─── 4. kubectl context ──────────────────────────────────────────────────────
header "4 · kubectl context"
CURRENT_CTX=$(kubectl config current-context 2>/dev/null || echo "none")
if [[ "$CURRENT_CTX" == "$EXPECTED_CTX" ]]; then
    pass "Context already set to '${EXPECTED_CTX}'"
else
    warn "Context is '${CURRENT_CTX}' — switching to '${EXPECTED_CTX}'"
    if kubectl config use-context "$EXPECTED_CTX" &>/dev/null; then
        pass "Switched context to '${EXPECTED_CTX}'"
        WARNINGS=$((WARNINGS - 1))   # auto-fixed, not a real warning
    else
        fail "Cannot switch to context '${EXPECTED_CTX}'"
        fix "kubectl config use-context ${EXPECTED_CTX}"
    fi
fi

# ─── 5. open5gs namespace ────────────────────────────────────────────────────
header "5 · Namespace 'open5gs'"
NS="open5gs"
if kubectl get namespace "$NS" &>/dev/null; then
    pass "Namespace '${NS}' exists"
else
    fail "Namespace '${NS}' not found"
    fix "kubectl apply -f k8s/manifests/00-namespace.yaml"
    echo -e "\n${RED}${BOLD}Namespace missing — pod checks skipped.${NC}\n"
    exit 1
fi

# ─── 6. Expected pods Running + Ready ────────────────────────────────────────
header "6 · Pod health — namespace: ${NS}"

# Core NFs + RAN simulator + WebUI (ue2/ue3 are optional)
EXPECTED_APPS=(mongodb nrf scp udr udm ausf bsf nssf pcf amf smf upf gnb ue webui)

# Build status map: app → "phase|ready"
declare -A POD_STATUS
while IFS=$'\t' read -r app phase ready; do
    [[ -z "$app" ]] && continue
    POD_STATUS["$app"]="${phase}|${ready}"
done < <(kubectl get pods -n "$NS" \
    -o custom-columns=\
'APP:.metadata.labels.app,PHASE:.status.phase,READY:.status.conditions[?(@.type=="Ready")].status' \
    --no-headers 2>/dev/null | awk '{print $1"\t"$2"\t"$3}')

for app in "${EXPECTED_APPS[@]}"; do
    entry="${POD_STATUS[$app]:-MISSING|Unknown}"
    phase="${entry%%|*}"
    ready="${entry##*|}"
    case "$phase" in
        Running)
            if [[ "$ready" == "True" ]]; then
                pass "${app}"
            else
                warn "${app} — Running but not yet Ready"
                fix "kubectl wait -n ${NS} pod -l app=${app} --for=condition=Ready --timeout=120s"
            fi
            ;;
        Pending)
            fail "${app} — Pending (may be scheduling or pulling image)"
            fix "kubectl describe pod -n ${NS} -l app=${app}  # check Events section"
            ;;
        MISSING)
            fail "${app} — no pod found"
            fix "kubectl apply -f k8s/manifests/  && sleep 60"
            ;;
        *)
            fail "${app} — phase=${phase}"
            fix "kubectl logs -n ${NS} -l app=${app} --previous  # if crash-looping"
            fix "kubectl describe pod -n ${NS} -l app=${app}     # check Events"
            ;;
    esac
done

# ─── 7. Crash-loop detection ─────────────────────────────────────────────────
header "7 · Crash-loop detection"
# Parse RESTARTS column (column 4 in 'kubectl get pods' default output)
CRASH_PODS=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null \
    | awk '$4+0 > 2 { print $1, "restarts=" $4 }' || true)

if [[ -z "$CRASH_PODS" ]]; then
    pass "No crash-looping pods (all restart counts ≤ 2)"
else
    while IFS= read -r entry; do
        pod_name=$(awk '{print $1}' <<< "$entry")
        fail "Crash-looping: ${entry}"
        fix "kubectl logs    -n ${NS} ${pod_name} --previous"
        fix "kubectl describe pod -n ${NS} ${pod_name}   # look at Events and Exit Code"
    done <<< "$CRASH_PODS"
fi

# ─── 8. Monitoring (Prometheus + Grafana) ────────────────────────────────────
header "8 · Monitoring — namespace: monitoring"
MON_NS="monitoring"
if ! kubectl get namespace "$MON_NS" &>/dev/null; then
    warn "Namespace '${MON_NS}' not found — Grafana dashboard will be unavailable"
    fix "kubectl create namespace monitoring"
    fix "helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \\"
    fix "  -n monitoring -f k8s/monitoring/kube-prometheus-values.yaml"
else
    PROM_COUNT=$(kubectl get pods -n "$MON_NS" \
        -l "app.kubernetes.io/name=prometheus" \
        --no-headers 2>/dev/null | grep -c "Running" || true)
    GRAF_COUNT=$(kubectl get pods -n "$MON_NS" \
        -l "app.kubernetes.io/name=grafana" \
        --no-headers 2>/dev/null | grep -c "Running" || true)

    if [[ "$PROM_COUNT" -gt 0 ]]; then
        pass "Prometheus running (${PROM_COUNT} pod(s))"
    else
        warn "Prometheus not Running in '${MON_NS}'"
        fix "helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \\"
        fix "  -n monitoring -f k8s/monitoring/kube-prometheus-values.yaml"
    fi

    if [[ "$GRAF_COUNT" -gt 0 ]]; then
        pass "Grafana running (${GRAF_COUNT} pod(s))"
    else
        warn "Grafana not Running in '${MON_NS}'"
        fix "helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \\"
        fix "  -n monitoring -f k8s/monitoring/kube-prometheus-values.yaml"
    fi
fi

# ─── 9. Network Query API ────────────────────────────────────────────────────
header "9 · Network Query API"
QUERYAPI_COUNT=$(kubectl get pods -n "$NS" \
    -l "app=network-query-api" \
    --no-headers 2>/dev/null | grep -c "Running" || true)
if [[ "$QUERYAPI_COUNT" -gt 0 ]]; then
    pass "network-query-api pod is Running"
else
    warn "network-query-api pod not found (will use local Flask fallback)"
    fix "kubectl apply -f k8s/serving/network-query-api.yaml"
    fix "# OR run locally in a terminal tab:"
    fix "cd automation && BEDROCK_ENABLED=false python network_query_api.py"
fi

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}ALL CHECKS PASSED — cluster ready for demo ✓${NC}"
elif [[ $ERRORS -eq 0 ]]; then
    echo -e "  ${YELLOW}${BOLD}PASSED with ${WARNINGS} warning(s) — demo may proceed${NC}"
else
    echo -e "  ${RED}${BOLD}${ERRORS} FAILED  ${WARNINGS} warnings — fix above before demo${NC}"
fi
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo ""

# ─── PORT-FORWARD CHEAT SHEET ────────────────────────────────────────────────
if [[ $ERRORS -eq 0 ]]; then
    echo -e "${BOLD}Port-forward commands — open one terminal tab per line:${NC}"
    echo ""
    echo "  # Grafana → http://localhost:3000   login: admin / prom-operator"
    echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &"
    echo ""
    echo "  # Prometheus → http://localhost:9090"
    echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &"
    echo ""
    echo "  # WebUI → http://localhost:9999   login: admin / 1423"
    echo "  kubectl port-forward -n open5gs svc/webui 9999:9999 &"
    echo ""
    echo "  # Network Query API → http://localhost:8080"
    echo "  kubectl port-forward -n open5gs svc/network-query-api 8080:8080 &"
    echo "  # (NodePort 30808 also available on the kind node IP)"
    echo ""
    echo -e "${BOLD}Verify API is up:${NC}"
    echo "  curl -s http://localhost:8080/health | python3 -m json.tool"
    echo ""
fi

exit $ERRORS
