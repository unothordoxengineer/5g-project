#!/bin/bash
# restart-ran.sh — Kill gNB + UE, clear stale contexts, restart gNB
# Run with sudo. Then start nr-ue separately in its own terminal.
#
# Usage:  sudo bash ~/5g-project/scripts/restart-ran.sh

set -uo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[RAN]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }

UERANSIM_DIR="$HOME/5g-project/UERANSIM"

# ── 1. Kill UE and gNB ───────────────────────────────────────
log "Killing nr-ue and nr-gnb (clears all stale UE/RRC contexts)..."
pkill -9 -f "nr-ue"  2>/dev/null && log "  nr-ue killed"  || log "  nr-ue not running"
pkill -9 -f "nr-gnb" 2>/dev/null && log "  nr-gnb killed" || log "  nr-gnb not running"
sleep 2

# ── 2. Clear stale TUN routes left behind by old nr-ue ──────
log "Cleaning up stale UE TUN routes..."
# Remove any leftover 8.8.8.8 or 10.45.x host routes via utun7/utun8/utun9
for utun in utun7 utun8 utun9 utun10; do
  ip=$(ifconfig "$utun" 2>/dev/null | awk '/inet /{print $2}')
  if [[ -n "$ip" && "$ip" != "10.45.0.1" ]]; then
    route delete -host "$ip"    2>/dev/null || true
    route delete -host 8.8.8.8  2>/dev/null || true
    log "  Cleared routes for $utun ($ip)"
  fi
done

# ── 3. Rotate gNB log ────────────────────────────────────────
log "Rotating gNB log..."
> /tmp/gnb.log

# ── 4. Start gNB fresh ──────────────────────────────────────
log "Starting gNB..."
sudo -u "$SUDO_USER" "$UERANSIM_DIR/build/nr-gnb" \
  -c "$UERANSIM_DIR/config/open5gs-gnb.yaml" \
  >> /tmp/gnb.log 2>&1 &
GNB_PID=$!

# ── 5. Wait for NG Setup ─────────────────────────────────────
log "Waiting for gNB NG Setup with AMF (up to 15s)..."
for i in $(seq 1 15); do
  if grep -q "NG Setup procedure is successful" /tmp/gnb.log 2>/dev/null; then
    log "gNB connected to AMF! (PID $GNB_PID)"
    break
  fi
  sleep 1
done
if ! grep -q "NG Setup procedure is successful" /tmp/gnb.log 2>/dev/null; then
  warn "NG Setup not confirmed. Check AMF is running: ps aux | grep open5gs-amf"
fi

# ── 6. Instructions ──────────────────────────────────────────
echo ""
log "═══════════════════════════════════════════"
log "gNB ready. Now do these steps IN ORDER:"
log "═══════════════════════════════════════════"
log ""
log "STEP 1 — Start UE in a NEW terminal:"
log "  cd ~/5g-project/UERANSIM"
log "  sudo ./build/nr-ue -c config/open5gs-ue.yaml"
log ""
log "STEP 2 — Wait for BOTH of these in the UE terminal:"
log "  [nas] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]"
log "  [app] TUN interface[utunN, 10.45.x.x] is up"
log ""
log "STEP 3 — Verify gNB got the GTP data plane:"
log "  grep 'PDU session resource' /tmp/gnb.log"
log "  (Must show 'PDU session resource(s) setup for UE[N] count[1]')"
log ""
log "STEP 4 — Only if STEP 3 confirms GTP path, set up NAT + routes:"
log "  sudo bash ~/5g-project/scripts/setup-upf-nat.sh"
log "  sudo bash ~/5g-project/scripts/fix-ue-routes.sh"
log "  ping 8.8.8.8 -c 5"
log "═══════════════════════════════════════════"
