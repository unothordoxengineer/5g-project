# End-to-End 5G Data Plane Validation

**Project:** Cloud-Native 5G SA Core — HIT Final Year Project  
**Author:** Nigel Farai Kadzinga, B.Eng Electronic Engineering, HIT Zimbabwe  
**Date:** 2026-04-23  
**Status:** ✅ Validated

---

## Summary

The GTP-U data plane was validated inside Docker Linux containers where kernel GTP support is available. A PDU session was established between a simulated UE (UERANSIM) and the Open5GS UPF, assigning the UE a routable IP address via the 5G core. End-to-end internet reachability was then confirmed by pinging and performing an HTTP request through the live GTP-U tunnel.

---

## Test Environment

| Component | Value |
|-----------|-------|
| Host OS | macOS Tahoe (Apple M1) |
| Container runtime | Docker Desktop (Linux VM, Ubuntu 22.04 kernel) |
| 5G Core | Open5GS v2.7.2 |
| RAN simulator | UERANSIM v3.2.6 |
| Deployment | Docker Compose (`docker-compose.yaml`) |
| GTP-U kernel module | `gtp` (Linux 5.15+ — available inside Docker VM) |

### macOS Platform Constraint

> **Note.** Native macOS does not support the Linux kernel GTP-U module (`gtp.ko`). The GTP-U data plane was therefore validated inside Docker Linux containers running Ubuntu 22.04 — the same environment used in production Kubernetes (EKS) deployment. This is documented as a **platform constraint**, not a system limitation. The identical Docker images are used in the Kubernetes manifests for Phase 8 AWS deployment, so the validation result is directly representative of the production environment.

---

## Data Plane Path

```
UE (UERANSIM)
  │  10.45.0.4 assigned via PDU session establishment (NAS)
  │
  ▼
uesimtun0 (TUN interface inside ueransim-ue container)
  │  GTP-U encapsulation (UDP/2152)
  │
  ▼
gNB container (ueransim-gnb)
  │  GTP-U tunnel: gNB ↔ UPF N3 interface
  │
  ▼
UPF (Open5GS) — ogstun interface
  │  GTP-U decapsulation → inner IP packet extracted
  │
  ▼
NAT (iptables masquerade on UPF container)
  │  10.45.0.4 → UPF container egress IP
  │
  ▼
Internet (Docker bridge → host → upstream)
```

---

## Test 1 — ICMP Ping (5/5 packets, 0% loss)

### Command

```bash
docker exec ueransim-ue ping -I uesimtun0 8.8.8.8 -c 5
```

### Output

```
PING 8.8.8.8 (8.8.8.8) from 10.45.0.4 uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=115 time=2.08 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=115 time=2.19 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=115 time=2.11 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=115 time=2.17 ms
64 bytes from 8.8.8.8: icmp_seq=5 ttl=115 time=2.15 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 2.08/2.14/2.19/0.04 ms
```

### Result

| Metric | Value | Pass criteria | Status |
|--------|-------|---------------|--------|
| Packets sent | 5 | — | — |
| Packets received | **5** | 5 | ✅ |
| Packet loss | **0 %** | 0 % | ✅ |
| RTT average | **2.14 ms** | < 10 ms | ✅ |
| RTT min / max | 2.08 ms / 2.19 ms | — | — |
| UE IP (uesimtun0) | **10.45.0.4** | assigned via PDU session | ✅ |

---

## Test 2 — HTTP Connectivity (curl via GTP-U tunnel)

### Command

```bash
docker exec ueransim-ue curl -s -o /dev/null -w "%{http_code} connect=%{time_connect}s total=%{time_total}s" \
  --interface uesimtun0 http://1.1.1.1
```

### Result

```
HTTP 301  connect=0.025s  total=0.049s
```

| Metric | Value | Status |
|--------|-------|--------|
| HTTP response code | **301** (redirect — server reachable) | ✅ |
| TCP connect time | **25 ms** | ✅ |
| Total request time | **49 ms** | ✅ |
| Interface used | uesimtun0 (GTP-U tunnel) | ✅ |

---

## PDU Session Establishment

The UE IP address `10.45.0.4` was assigned dynamically by the Open5GS SMF during the PDU session establishment procedure:

1. **UE → AMF:** PDU Session Establishment Request (NAS message)  
2. **AMF → SMF:** Nsmf_PDUSession_CreateSMContext (SBI)  
3. **SMF → UPF:** PFCP Session Establishment Request — N3 and N6 forwarding rules installed  
4. **SMF → AMF:** PDU Session Establishment Accept — UE IP `10.45.0.4` assigned from UPF pool (`10.45.0.0/16`)  
5. **gNB → UPF:** GTP-U tunnel established on N3 interface  

The `uesimtun0` TUN interface is created by UERANSIM to represent the UE-side end of the PDU session, allowing standard Linux `ping` and `curl` commands to source traffic from the assigned UE IP.

---

## Validation Scope

| Item | Validated | Notes |
|------|-----------|-------|
| UE registration (NAS) | ✅ | AMF accepted, 5G-GUTI assigned |
| PDU session establishment | ✅ | SMF / UPF PFCP session created |
| UE IP assignment | ✅ | 10.45.0.4 via IPAM pool |
| GTP-U tunnel (N3) | ✅ | gNB ↔ UPF encapsulation confirmed by packet receipt |
| UPF NAT / N6 forwarding | ✅ | ICMP and TCP traffic forwarded to internet |
| End-to-end ICMP (ping) | ✅ | 5/5 packets, 0% loss, 2.14 ms avg RTT |
| End-to-end HTTP (curl) | ✅ | HTTP 301, connect 25 ms, total 49 ms |
| macOS native data plane | ⚠️ | Not supported — Docker Linux container used (see platform note above) |

---

## Related Documents

| Document | Location | Content |
|----------|----------|---------|
| Architecture diagram | `docs/architecture.png` | Full 6-layer operational architecture |
| Stress test benchmark | `results/benchmark_report.md` | HPA timing, latency p99, throughput analysis |
| ML model evaluation | `ml/model_evaluation.md` | Anomaly detection, forecasting, clustering results |
| Project journal | `docs/journal.md` | Day-by-day implementation log |
