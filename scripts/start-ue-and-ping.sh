#!/bin/bash
# ============================================================
# start-ue-and-ping.sh — Atomic UE start + data-plane + ping
#
# Kills any running nr-ue, starts a fresh one, waits for the
# PDU session TUN interface to appear, then immediately runs
# the NAT/routing setup and pings 8.8.8.8 — no manual steps.
#
# Prerequisites:
#   • 5G core + gNB already running (start-5g.sh)
#   • Run with sudo: sudo bash ~/5g-project/scripts/start-ue-and-ping.sh
# ============================================================

set -uo pipefail

UERANSIM_DIR="$HOME/5g-project/UERANSIM"
SCRIPTS_DIR="$HOME/5g-project/scripts"
UE_LOG="/tmp/ue.log"
TEST_DST="8.8.8.8"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[UE ]${NC}  $*"; }
info() { echo -e "${CYAN}[   ]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!! ]${NC}  $*"; }
err()  { echo -e "${RED}[EE ]${NC}  $*"; exit 1; }

# ── root check ──────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "Run with sudo: sudo bash $0"
fi

# ── kill any existing nr-ue ──────────────────────────────────
log "Stopping any running nr-ue..."
pkill -f nr-ue 2>/dev/null && echo "  killed nr-ue" || echo "  (not running)"
sleep 1

# ── clear stale UE log ───────────────────────────────────────
> "$UE_LOG"

# ── start nr-ue in background ────────────────────────────────
log "Starting nr-ue..."
"$UERANSIM_DIR/build/nr-ue" \
    -c "$UERANSIM_DIR/config/open5gs-ue.yaml" \
    >> "$UE_LOG" 2>&1 &
UE_PID=$!
log "nr-ue started (PID $UE_PID), log: $UE_LOG"

# ── wait for PDU session TUN interface ───────────────────────
log "Waiting for UE TUN interface (utunN with 10.45.x.x)..."
TIMEOUT=60
elapsed=0
UE_IFACE=""
UE_IP=""

while [[ $elapsed -lt $TIMEOUT ]]; do
    # Check if nr-ue died
    if ! kill -0 "$UE_PID" 2>/dev/null; then
        err "nr-ue process died unexpectedly. Check $UE_LOG"
    fi

    # Find UPF TUN first (always 10.45.0.1)
    UPF_IFACE=""
    for iface in $(ifconfig -l 2>/dev/null); do
        [[ "$iface" != utun* ]] && continue
        ip=$(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
        if [[ "$ip" == "10.45.0.1" ]]; then
            UPF_IFACE="$iface"
            break
        fi
    done

    # Find UE TUN (any 10.45.x.x except 10.45.0.1)
    for iface in $(ifconfig -l 2>/dev/null); do
        [[ "$iface" != utun* ]] && continue
        [[ "$iface" == "$UPF_IFACE" ]] && continue
        ip=$(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
        if [[ "$ip" == 10.45.* ]]; then
            UE_IFACE="$iface"
            UE_IP="$ip"
            break
        fi
    done

    if [[ -n "$UE_IFACE" ]]; then
        log "UE TUN is up: ${UE_IFACE} (${UE_IP})"
        break
    fi

    sleep 1
    ((elapsed++))
    if (( elapsed % 5 == 0 )); then
        info "  Still waiting... (${elapsed}s)"
        # Show last relevant log line
        grep -E "PDU|TUN|error|Error|fail" "$UE_LOG" 2>/dev/null | tail -3 || true
    fi
done

if [[ -z "$UE_IFACE" ]]; then
    err "UE TUN did not appear within ${TIMEOUT}s. Tail of $UE_LOG:"
fi

# ── brief pause to let gNB log PDU session resource ─────────
sleep 2

# ── confirm gNB accepted PDU session ─────────────────────────
log "Checking gNB for PDU session resource setup..."
if grep -q "PDU session resource\|PDUSessionResourceSetup" /tmp/gnb.log 2>/dev/null; then
    log "  gNB PDU session resource setup confirmed."
else
    warn "  gNB PDU session resource not found in /tmp/gnb.log — proceeding anyway."
    tail -5 /tmp/gnb.log 2>/dev/null || true
fi

# ── data plane setup ─────────────────────────────────────────
echo ""
log "════════════════════════════════════════"
log "Running setup-upf-nat.sh..."
log "════════════════════════════════════════"
bash "$SCRIPTS_DIR/setup-upf-nat.sh"

echo ""
log "════════════════════════════════════════"
log "Running fix-ue-routes.sh..."
log "════════════════════════════════════════"
bash "$SCRIPTS_DIR/fix-ue-routes.sh" "$TEST_DST"

# ── ping test ────────────────────────────────────────────────
echo ""
log "════════════════════════════════════════"
log "Ping test: ${TEST_DST} via 5G GTP tunnel"
log "════════════════════════════════════════"
echo ""

# Bind ping to UE IP so packets enter the correct TUN
ping -S "$UE_IP" -c 5 -W 3000 "$TEST_DST"
PING_RC=$?

echo ""
if [[ $PING_RC -eq 0 ]]; then
    log "SUCCESS — ping to ${TEST_DST} via 5G GTP tunnel PASSED!"
    log "Phase 1 complete: end-to-end data plane verified."
else
    warn "Ping returned exit code ${PING_RC} (packet loss or timeout)."
    echo ""
    info "Diagnostic — routing table (10.45 + ${TEST_DST}):"
    netstat -rn -f inet | grep -E "10\.45|${TEST_DST//./\\.}" || true
    echo ""
    info "Last 10 lines of UE log:"
    tail -10 "$UE_LOG" 2>/dev/null || true
    echo ""
    info "Last 10 lines of gNB log:"
    tail -10 /tmp/gnb.log 2>/dev/null || true
fi

exit $PING_RC
