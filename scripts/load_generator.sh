#!/bin/bash
# =============================================================================
# load_generator.sh — Open5GS Phase 4 Load Test
#
# Drives traffic through the 5G data plane (uesimtun0) using iperf3 parallel
# streams to simulate increasing UE load and trigger UPF HPA autoscaling.
#
# Phases:
#   A — Baseline    (10 min): 2 parallel streams, ~10 Mbps
#   B — Moderate    (15 min): 20 parallel streams, ~100 Mbps
#   C — High load   (15 min): max streams targeting UPF CPU >70% → HPA fires
#   D — Recovery    (10 min): back to 2 streams, observe scale-down
#
# Requirements:
#   - UE pod must be running with uesimtun0 interface up
#   - iperf3 available in the UE container (or use kubectl exec)
#   - Prometheus port-forward running on localhost:9090 (for phase logging)
#
# Output: ~/5g-project/data/raw/load_phases.csv
# =============================================================================

set -euo pipefail

NAMESPACE="open5gs"
UE_POD=$(kubectl get pod -n "$NAMESPACE" -l app=ue --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
DATA_DIR="$HOME/5g-project/data/raw"
LOG_CSV="$DATA_DIR/load_phases.csv"
IPERF_SERVER="10.45.0.1"   # UPF N3 IP (reachable via uesimtun0)
IPERF_DURATION=30           # seconds per iperf3 run

mkdir -p "$DATA_DIR"

# ---- helpers ----------------------------------------------------------------
log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] $*"; }

csv_header() {
  echo "timestamp,load_phase,parallel_streams,iperf_bandwidth_mbps,upf_replicas,note" > "$LOG_CSV"
  log "CSV log: $LOG_CSV"
}

# Append one CSV row
log_csv() {
  local phase="$1" streams="$2" bw="$3" replicas="$4" note="${5:-}"
  echo "$(date '+%Y-%m-%dT%H:%M:%S'),$phase,$streams,$bw,$replicas,$note" >> "$LOG_CSV"
}

# Get current UPF replica count via kubectl
upf_replicas() {
  kubectl get hpa -n "$NAMESPACE" upf-hpa --no-headers 2>/dev/null \
    | awk '{print $6}' || echo "?"
}

# Run iperf3 inside the UE pod, return bandwidth in Mbps
run_iperf() {
  local streams="$1"
  kubectl exec -n "$NAMESPACE" "$UE_POD" -- \
    iperf3 -c "$IPERF_SERVER" -t "$IPERF_DURATION" -P "$streams" -J 2>/dev/null \
    | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    bps = d['end']['sum_received']['bits_per_second']
    print(f'{bps/1e6:.2f}')
except Exception:
    print('0')
" 2>/dev/null || echo "0"
}

# Fallback: simple bandwidth without iperf3 (ping flood via tun)
run_ping_load() {
  local count="$1"
  kubectl exec -n "$NAMESPACE" "$UE_POD" -- \
    ping -I uesimtun0 -c "$count" -i 0.01 -q 8.8.8.8 2>/dev/null | tail -1 || true
}

# ---- preflight --------------------------------------------------------------
if [ -z "$UE_POD" ]; then
  log "ERROR: No UE pod found in namespace $NAMESPACE. Is the UE running?"
  exit 1
fi
log "UE pod: $UE_POD"

# Check uesimtun0 is up
if ! kubectl exec -n "$NAMESPACE" "$UE_POD" -- ip link show uesimtun0 &>/dev/null; then
  log "ERROR: uesimtun0 not found in UE pod. PDU session not established?"
  exit 1
fi
log "uesimtun0 is up in UE pod"

# Check iperf3 availability; fall back to ping if missing
IPERF_AVAILABLE=true
if ! kubectl exec -n "$NAMESPACE" "$UE_POD" -- which iperf3 &>/dev/null; then
  log "WARNING: iperf3 not found in UE pod — using ping flood as load generator"
  IPERF_AVAILABLE=false
fi

csv_header
log "Starting load test. Total duration: ~50 minutes"
log "================================================"

# ---- Phase A: Baseline (10 min, 2 streams) ----------------------------------
PHASE="A_baseline"
STREAMS=2
PHASE_DURATION=600  # 10 min
log "Phase A — Baseline: $STREAMS streams for ${PHASE_DURATION}s"
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_start"

phase_end=$((SECONDS + PHASE_DURATION))
while [ $SECONDS -lt $phase_end ]; do
  if $IPERF_AVAILABLE; then
    BW=$(run_iperf "$STREAMS")
  else
    run_ping_load 300 &>/dev/null &
    BW="ping_load"
  fi
  REPLICAS=$(upf_replicas)
  log "  Phase A | streams=$STREAMS | bw=${BW}Mbps | upf_replicas=$REPLICAS"
  log_csv "$PHASE" "$STREAMS" "$BW" "$REPLICAS"
  sleep $((IPERF_DURATION + 5))
done
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_end"

# ---- Phase B: Moderate (15 min, 20 streams) ---------------------------------
PHASE="B_moderate"
STREAMS=20
PHASE_DURATION=900  # 15 min
log "Phase B — Moderate: $STREAMS streams for ${PHASE_DURATION}s"
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_start"

phase_end=$((SECONDS + PHASE_DURATION))
while [ $SECONDS -lt $phase_end ]; do
  if $IPERF_AVAILABLE; then
    BW=$(run_iperf "$STREAMS")
  else
    run_ping_load 3000 &>/dev/null &
    BW="ping_load"
  fi
  REPLICAS=$(upf_replicas)
  log "  Phase B | streams=$STREAMS | bw=${BW}Mbps | upf_replicas=$REPLICAS"
  log_csv "$PHASE" "$STREAMS" "$BW" "$REPLICAS"
  sleep $((IPERF_DURATION + 5))
done
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_end"

# ---- Phase C: High load (15 min, 64 streams) — target UPF CPU >70% ----------
PHASE="C_high"
STREAMS=64
PHASE_DURATION=900  # 15 min
log "Phase C — High load: $STREAMS streams for ${PHASE_DURATION}s (targeting UPF CPU >70% → HPA)"
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_start"

phase_end=$((SECONDS + PHASE_DURATION))
hpa_fired=false
while [ $SECONDS -lt $phase_end ]; do
  if $IPERF_AVAILABLE; then
    BW=$(run_iperf "$STREAMS")
  else
    # Run multiple background ping floods to saturate CPU
    for i in $(seq 1 8); do run_ping_load 5000 &>/dev/null & done
    BW="ping_load_x8"
  fi
  REPLICAS=$(upf_replicas)
  log "  Phase C | streams=$STREAMS | bw=${BW}Mbps | upf_replicas=$REPLICAS"
  log_csv "$PHASE" "$STREAMS" "$BW" "$REPLICAS"

  # Detect HPA scale-up
  if [ "$REPLICAS" != "1" ] && [ "$REPLICAS" != "?" ] && ! $hpa_fired; then
    log "  *** HPA SCALE-UP DETECTED: replicas=$REPLICAS ***"
    log_csv "$PHASE" "$STREAMS" "$BW" "$REPLICAS" "hpa_scale_up"
    hpa_fired=true
  fi
  sleep $((IPERF_DURATION + 5))
done
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_end"

# ---- Phase D: Recovery (10 min, 2 streams) ----------------------------------
PHASE="D_recovery"
STREAMS=2
PHASE_DURATION=600  # 10 min
log "Phase D — Recovery: $STREAMS streams for ${PHASE_DURATION}s (waiting for HPA scale-down)"
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_start"

phase_end=$((SECONDS + PHASE_DURATION))
while [ $SECONDS -lt $phase_end ]; do
  if $IPERF_AVAILABLE; then
    BW=$(run_iperf "$STREAMS")
  else
    run_ping_load 300 &>/dev/null &
    BW="ping_load"
  fi
  REPLICAS=$(upf_replicas)
  log "  Phase D | streams=$STREAMS | bw=${BW}Mbps | upf_replicas=$REPLICAS"
  log_csv "$PHASE" "$STREAMS" "$BW" "$REPLICAS"
  sleep $((IPERF_DURATION + 5))
done
log_csv "$PHASE" "$STREAMS" "N/A" "$(upf_replicas)" "phase_end"

# ---- Done -------------------------------------------------------------------
log "================================================"
log "Load test complete. CSV written to: $LOG_CSV"
log "Lines in CSV: $(wc -l < "$LOG_CSV")"
log ""
log "To verify HPA events:"
log "  kubectl describe hpa upf-hpa -n open5gs"
log "  kubectl get events -n open5gs --sort-by=.lastTimestamp | grep -i scale"
