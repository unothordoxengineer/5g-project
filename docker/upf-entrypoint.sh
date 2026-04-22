#!/bin/sh
# UPF container entrypoint — starts open5gs-upfd then configures ogstun + NAT

# Start UPF daemon in background
exec /usr/local/bin/open5gs-upfd -c /etc/open5gs/upf.yaml &
UPF_PID=$!

# Wait for ogstun to appear (UPF creates it on startup)
for i in $(seq 1 30); do
    if ip link show ogstun > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Configure the tun interface
ip link set ogstun up
ip addr add 10.45.0.1/16 dev ogstun 2>/dev/null || true
ip addr add 2001:db8:cafe::1/48 dev ogstun 2>/dev/null || true

# NAT masquerade so UE packets reach the internet
iptables -t nat -A POSTROUTING -s 10.45.0.0/16 ! -o ogstun -j MASQUERADE

echo "[entrypoint] ogstun configured: $(ip addr show ogstun 2>&1 | grep 'inet ')"

# Wait for UPF daemon
wait $UPF_PID
