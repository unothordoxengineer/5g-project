#!/bin/bash
# Setup IP forwarding, NAT masquerade, and pf route-to for Open5GS UPF on macOS.
#
# The core problem on a single macOS host:
#   fix-ue-routes.sh adds "8.8.8.8 → utun8" so that host pings go through the
#   5G GTP tunnel.  But UPF also writes decapsulated uplink packets to utun6,
#   and the kernel routes those packets via the same "8.8.8.8 → utun8" host
#   route, creating a forwarding loop.
#
#   Fix: use pf "route-to" on utun6 to force UPF uplink packets out en0
#   directly, bypassing the routing table.  The NAT rule then rewrites the
#   source from 10.45.x.x to the en0 IP as normal.
#
# Run with sudo: sudo bash setup-upf-nat.sh

set -e

EGRESS_IF="en0"
UE_SUBNET="10.45.0.0/16"

echo "[1/4] Enabling IP forwarding..."
sysctl -w net.inet.ip.forwarding=1

echo "[2/4] Auto-detecting UPF TUN and default gateway..."
# UPF TUN always gets 10.45.0.1 — find whichever utunN has that IP
UPF_TUN=""
for iface in $(ifconfig -l); do
    [[ "$iface" != utun* ]] && continue
    ip=$(ifconfig "$iface" 2>/dev/null | awk '/inet /{print $2}')
    if [[ "$ip" == "10.45.0.1" ]]; then
        UPF_TUN="$iface"
        break
    fi
done
if [[ -z "$UPF_TUN" ]]; then
    echo "ERROR: No UPF TUN found (looking for utunN with 10.45.0.1). Is UPF running?"
    exit 1
fi
echo "  UPF TUN: ${UPF_TUN}"
GW=$(netstat -rn -f inet | awk '/^default/{print $2; exit}')
if [[ -z "$GW" ]]; then
  echo "ERROR: No default IPv4 gateway found. Is Wi-Fi (en0) connected?"
  exit 1
fi
echo "  Gateway: ${GW}"

echo "[3/4] Adding UE subnet route via UPF TUN..."
# Open5GS UPF on macOS creates the TUN with a /32 (local==peer), so the OS
# does NOT auto-create a 10.45.0.0/16 subnet route.  Without it, deNAT'd
# reply packets (dst=10.45.x.x) have no route to UPF and are dropped by the
# kernel — the GTP downlink path never fires.
route delete -net 10.45.0.0/16 2>/dev/null || true
route add -net 10.45.0.0/16 -interface "${UPF_TUN}"
echo "  10.45.0.0/16 → ${UPF_TUN}"

echo "[4/5] Writing pf rules..."
cat > /tmp/5g-nat.conf << EOF
# pf rule order on macOS: translation THEN filtering.
# macOS pf uses "last matching rule wins"; add 'quick' on specific rules so
# they take effect immediately without being overridden by 'pass all'.

# 1. NAT: rewrite source from 10.45.x.x to en0 IP when leaving en0.
nat on ${EGRESS_IF} from ${UE_SUBNET} to any -> (${EGRESS_IF})

# 2. Force UPF uplink (utun6 → internet) out en0, bypassing the routing table.
#    'quick' stops rule evaluation here so 'pass all' cannot override route-to.
pass in quick on ${UPF_TUN} route-to (${EGRESS_IF} ${GW}) from ${UE_SUBNET} to any

pass all
EOF

echo "[5/5] Loading pf rules (pfctl)..."
pfctl -e 2>/dev/null || true          # enable pf if not already enabled
pfctl -f /tmp/5g-nat.conf

echo ""
echo "Data-plane setup complete."
echo "  IP forwarding : enabled"
echo "  route-to      : ${UPF_TUN} UE traffic → ${EGRESS_IF} via ${GW}"
echo "  NAT           : ${UE_SUBNET} → ${EGRESS_IF}"
echo ""
echo "Now run fix-ue-routes.sh, then ping 8.8.8.8."
