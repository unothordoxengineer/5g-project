#!/bin/sh
# UE container entrypoint — starts nr-ue then adds default route via uesimtun0
# so UE traffic is routed through the 5G data plane by default.

# Start UERANSIM UE in background
/usr/local/bin/nr-ue -c /etc/ueransim/nr-ue.yaml &
UE_PID=$!

# Wait for uesimtun0 to appear (created by nr-ue after PDU session setup)
echo "[ue-entrypoint] waiting for uesimtun0..."
for i in $(seq 1 30); do
    if ip link show uesimtun0 > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ip link show uesimtun0 > /dev/null 2>&1; then
    # Add default route via uesimtun0 (metric 50 beats eth0 default at metric 100)
    # This ensures all traffic uses the 5G data plane
    ip route add default dev uesimtun0 metric 50 2>/dev/null || true
    echo "[ue-entrypoint] uesimtun0 up, default route via 5G tunnel added"
    ip addr show uesimtun0 | grep 'inet '
else
    echo "[ue-entrypoint] WARNING: uesimtun0 did not appear within 30s"
fi

# Wait for UE process
wait $UE_PID
