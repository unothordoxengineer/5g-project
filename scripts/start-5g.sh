#!/bin/bash
# ============================================================
# start-5g.sh — Open5GS 5G SA Core + UERANSIM gNB startup
# Starts ALL NFs in correct dependency order, waits for each
# to register with NRF before moving to the next tier.
#
# Usage:
#   sudo bash ~/5g-project/scripts/start-5g.sh
#
# After this script completes, start the UE in a NEW terminal:
#   cd ~/5g-project/UERANSIM
#   sudo ./build/nr-ue -c config/open5gs-ue.yaml
#
# Then once PDU session is up, run the data-plane setup:
#   sudo bash ~/5g-project/scripts/setup-upf-nat.sh
#   sudo bash ~/5g-project/scripts/fix-ue-routes.sh
#   ping 8.8.8.8 -c 5
# ============================================================

set -uo pipefail

OPEN5GS_DIR="$HOME/5g-project/open5gs"
UERANSIM_DIR="$HOME/5g-project/UERANSIM"
LOG_DIR="$OPEN5GS_DIR/install/var/log/open5gs"
CFG_DIR="$OPEN5GS_DIR/build/configs/open5gs"
BIN_DIR="$OPEN5GS_DIR/build/src"

# ── colours ─────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[5G]${NC}  $*"; }
info() { echo -e "${CYAN}[  ]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
err()  { echo -e "${RED}[EE]${NC}  $*"; }

# ── root check ──────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "This script must be run with sudo (needed for UPF)."
  err "Run:  sudo bash ~/5g-project/scripts/start-5g.sh"
  exit 1
fi

# ── stop existing processes ──────────────────────────────────
log "Stopping any running NFs, gNB, and UE processes..."
for proc in open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd \
            open5gs-ausfd open5gs-bsfd open5gs-nssfd open5gs-pcfd \
            open5gs-amfd open5gs-smfd open5gs-upfd nr-gnb nr-ue; do
  pkill -f "$proc" 2>/dev/null && echo "  killed $proc" || true
done
sleep 2

# ── clear stale MongoDB state ────────────────────────────────
# Stale PDU sessions from previous runs cause SMF/UPF conflicts.
# NRF state is in-memory (killed above), but sessions persist in DB.
# Also reset subscriber SQN so AUSF authentication doesn't fail on
# sequence number mismatch after hard restarts.
log "Clearing stale sessions and resetting subscriber SQN..."
mongosh --quiet open5gs --eval '
  var r = db.sessions.deleteMany({});
  print("  Deleted " + r.deletedCount + " stale session(s)");
  var s = db.subscribers.updateMany({}, {$set: {"security.sqn": NumberLong("0")}});
  print("  Reset SQN for " + s.modifiedCount + " subscriber(s)");
' 2>/dev/null || warn "mongosh not found or MongoDB not running — skipping DB cleanup"

# ── log rotation ─────────────────────────────────────────────
log "Rotating logs..."
mkdir -p "$LOG_DIR"
for nf in nrf scp udr udm ausf bsf nssf pcf amf smf upf; do
  > "$LOG_DIR/${nf}.log"   # truncate
done
> /tmp/gnb.log

# ── helper: start NF and wait for NRF registration ──────────
# usage: start_nf <display_name> <nf_short> <binary_subpath>
start_nf() {
  local name="$1" nf="$2" binpath="$3"
  local logfile="$LOG_DIR/${nf}.log"
  local binary="$BIN_DIR/${binpath}"
  local config="$CFG_DIR/${nf}.yaml"

  info "Starting ${name}..."

  # Run as the actual user (not root) for non-UPF NFs
  # UPF is called directly since it needs root
  if [[ "$nf" == "upf" ]]; then
    "$binary" -c "$config" >> "$logfile" 2>&1 &
  else
    sudo -u "$SUDO_USER" "$binary" -c "$config" >> "$logfile" 2>&1 &
  fi
  local pid=$!

  # Wait for NRF registration confirmation in log (up to 15s)
  local waited=0
  while [[ $waited -lt 15 ]]; do
    if grep -q "NF registered\|initialize.*done\|pfcp_server\|ngap_server" "$logfile" 2>/dev/null; then
      log "${name} ready (PID ${pid})"
      return 0
    fi
    sleep 1
    ((waited++))
  done
  warn "${name} started but NRF registration not confirmed within 15s — continuing"
}

# ── TIER 1: NRF + SCP (everything else depends on these) ────
log "════════════════════════════════════════"
log "Tier 1: NRF + SCP"
log "════════════════════════════════════════"
start_nf "NRF" "nrf" "nrf/open5gs-nrfd"
sleep 1
start_nf "SCP" "scp" "scp/open5gs-scpd"
sleep 1

# ── TIER 2: Data layer ───────────────────────────────────────
log "════════════════════════════════════════"
log "Tier 2: UDR → UDM"
log "════════════════════════════════════════"
start_nf "UDR" "udr" "udr/open5gs-udrd"
sleep 1
start_nf "UDM" "udm" "udm/open5gs-udmd"
sleep 1

# ── TIER 3: Auth ─────────────────────────────────────────────
log "════════════════════════════════════════"
log "Tier 3: AUSF"
log "════════════════════════════════════════"
start_nf "AUSF" "ausf" "ausf/open5gs-ausfd"
sleep 1

# ── TIER 4: Policy/Binding ───────────────────────────────────
log "════════════════════════════════════════"
log "Tier 4: BSF → NSSF → PCF"
log "════════════════════════════════════════"
start_nf "BSF"  "bsf"  "bsf/open5gs-bsfd"
sleep 1
start_nf "NSSF" "nssf" "nssf/open5gs-nssfd"
sleep 1
start_nf "PCF"  "pcf"  "pcf/open5gs-pcfd"
sleep 2

# ── TIER 5: Session + Mobility ───────────────────────────────
log "════════════════════════════════════════"
log "Tier 5: SMF → AMF"
log "════════════════════════════════════════"
start_nf "SMF" "smf" "smf/open5gs-smfd"
sleep 2
start_nf "AMF" "amf" "amf/open5gs-amfd"
sleep 2

# ── TIER 6: UPF (root) ───────────────────────────────────────
log "════════════════════════════════════════"
log "Tier 6: UPF (root)"
log "════════════════════════════════════════"
start_nf "UPF" "upf" "upf/open5gs-upfd"
sleep 3

# ── TIER 7: gNB ──────────────────────────────────────────────
log "════════════════════════════════════════"
log "Tier 7: gNB"
log "════════════════════════════════════════"
info "Starting gNB..."
sudo -u "$SUDO_USER" "$UERANSIM_DIR/build/nr-gnb" \
  -c "$UERANSIM_DIR/config/open5gs-gnb.yaml" \
  >> /tmp/gnb.log 2>&1 &
GNB_PID=$!

# Wait for NG Setup to succeed
log "Waiting for gNB NG Setup with AMF..."
waited=0
while [[ $waited -lt 20 ]]; do
  if grep -q "NG Setup procedure is successful\|NGSetupResponse" /tmp/gnb.log 2>/dev/null; then
    log "gNB connected to AMF! (PID ${GNB_PID})"
    break
  fi
  sleep 1
  ((waited++))
done
if [[ $waited -ge 20 ]]; then
  warn "gNB did not complete NG Setup within 20s. Check /tmp/gnb.log"
fi

# ── STATUS SUMMARY ───────────────────────────────────────────
echo ""
log "════════════════════════════════════════"
log "5G SA Core Status"
log "════════════════════════════════════════"
ALL_OK=true
for nf in nrf scp udr udm ausf bsf nssf pcf amf smf upf; do
  if pgrep -f "open5gs-${nf}d" > /dev/null 2>&1; then
    pid=$(pgrep -f "open5gs-${nf}d" | head -1)
    echo -e "  ${GREEN}✓${NC} ${nf} (PID ${pid})"
  else
    echo -e "  ${RED}✗${NC} ${nf} — NOT RUNNING"
    ALL_OK=false
  fi
done
if pgrep -f "nr-gnb" > /dev/null 2>&1; then
  echo -e "  ${GREEN}✓${NC} gNB (PID $(pgrep -f nr-gnb | head -1))"
else
  echo -e "  ${RED}✗${NC} gNB — NOT RUNNING"
  ALL_OK=false
fi

echo ""
if $ALL_OK; then
  log "All NFs running. Core is ready."
else
  warn "Some NFs failed to start. Check logs in: $LOG_DIR"
fi

echo ""
log "════════════════════════════════════════"
log "Next steps:"
log "════════════════════════════════════════"
log "1) Open a NEW terminal and run the UE:"
log "     cd ~/5g-project/UERANSIM"
log "     sudo ./build/nr-ue -c config/open5gs-ue.yaml"
log ""
log "2) Wait for: 'TUN interface[utunN, 10.45.x.x] is up'"
log ""
log "3) In ANOTHER terminal, set up data plane:"
log "     sudo bash ~/5g-project/scripts/setup-upf-nat.sh"
log "     sudo bash ~/5g-project/scripts/fix-ue-routes.sh"
log "     ping 8.8.8.8 -c 5"
log "════════════════════════════════════════"
