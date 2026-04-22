#!/bin/bash
# Fix 5G UE data-plane routing on macOS
#
# Detects TUN interfaces dynamically:
#   UPF TUN  = utunN with IP 10.45.0.1  (Open5GS UPF always gets .1)
#   UE  TUN  = utunN with any other 10.45.x.x address
#
# Run AFTER nr-ue has printed "TUN interface[utunN, 10.45.x.x] is up"
# Usage: sudo bash fix-ue-routes.sh [test_destination]

TEST_DST="${1:-8.8.8.8}"

# ── Auto-detect UPF TUN (always 10.45.0.1) ───────────────────
UPF_IFACE=""
for iface in $(ifconfig -l); do
    [[ "$iface" != utun* ]] && continue
    ip=$(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
    if [[ "$ip" == "10.45.0.1" ]]; then
        UPF_IFACE="$iface"
        break
    fi
done

if [[ -z "$UPF_IFACE" ]]; then
    echo "ERROR: No UPF TUN found (looking for utunN with 10.45.0.1). Is UPF running?"
    exit 1
fi
echo "Detected UPF TUN: ${UPF_IFACE} (10.45.0.1)"

# ── Auto-detect UE TUN (10.45.x.x but NOT 10.45.0.1) ─────────
UE_IFACE=""
UE_IP=""
for iface in $(ifconfig -l); do
    [[ "$iface" != utun* ]] && continue
    [[ "$iface" == "$UPF_IFACE" ]] && continue        # skip UPF TUN
    ip=$(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
    if [[ "$ip" == 10.45.* ]]; then
        UE_IFACE="$iface"
        UE_IP="$ip"
    fi
done

if [[ -z "$UE_IFACE" ]]; then
    echo "ERROR: No UE TUN found (looking for utunN with 10.45.x.x, excluding ${UPF_IFACE})."
    echo "Make sure nr-ue is running and PDU session is established before running this script."
    exit 1
fi

echo "Detected UE  TUN: ${UE_IFACE} (${UE_IP})"
echo ""

echo "[1/4] Removing direct host route ${UE_IP} via ${UE_IFACE} (if present)..."
route delete -host "${UE_IP}" 2>/dev/null && echo "  deleted" || echo "  (not present)"

echo "[2/4] Removing /31 P2P subnet routes via ${UE_IFACE} (if present)..."
# macOS stores the /31 under the masked network address.
MASKED_NET=$(python3 -c "
import ipaddress
net = ipaddress.ip_interface('${UE_IP}/31').network
print(str(net))
" 2>/dev/null || echo "")
route delete -net "${UE_IP}/31"   2>/dev/null || true
if [[ -n "$MASKED_NET" && "$MASKED_NET" != "${UE_IP}/31" ]]; then
    route delete -net "$MASKED_NET" 2>/dev/null || true
fi
# Nuke any remaining 10.45 routes via the UE TUN
netstat -rn -f inet | awk -v iface="${UE_IFACE}" '$NF==iface && /^10\.45/' \
    | awk '{print $1}' | while read dst; do
    route delete -net "$dst" 2>/dev/null || true
    echo "  cleared $dst via ${UE_IFACE}"
done

echo "[3/4] Adding route: ${TEST_DST} → ${UE_IFACE} (GTP tunnel outbound)..."
route delete -host "${TEST_DST}" 2>/dev/null || true
route add -host "${TEST_DST}" -interface "${UE_IFACE}"

echo ""
echo "[4/4] Routing table (10.45 + ${TEST_DST} entries):"
netstat -rn -f inet | grep -E "10\.45|${TEST_DST//./\\.}"

echo ""
echo "Data plane path:"
echo "  OUT: ping → ${UE_IFACE}(${UE_IP}) → nr-ue GTP → gNB → UPF → en0 NAT → ${TEST_DST}"
echo "  IN:  ${TEST_DST} → en0 deNAT → ${UPF_IFACE}(UPF) → GTP downlink → nr-ue → ${UE_IFACE} → ping"
echo ""
echo "Run:  ping ${TEST_DST} -c 5"
