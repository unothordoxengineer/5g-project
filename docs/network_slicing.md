# Network Slicing — Implementation Guide

## Overview

Network slicing (3GPP TS 23.501 §5.15) partitions a single physical 5G core into
multiple logically independent virtual networks, each with its own QoS profile,
IP address pool, and traffic policy.  Each slice is identified by an
**S-NSSAI** (Single-Network Slice Selection Assistance Information) comprising:

| Field | Width | Meaning |
|-------|-------|---------|
| **SST** (Slice/Service Type) | 8 bits | Standardised service category |
| **SD**  (Slice Differentiator) | 24 bits | Optional operator-specific tag |

This project implements three standardised SST values across the Open5GS core.

---

## Slice Definitions

### Slice 1 — eMBB (Enhanced Mobile Broadband)

| Parameter | Value |
|-----------|-------|
| SST | 1 |
| DNN | `internet` |
| UE AMBR DL / UL | 100 Mbps / 50 Mbps |
| 5QI | 9 (Non-GBR) |
| Packet Delay Budget | 300 ms |
| IP Pool | `10.45.0.0/16` (GW `10.45.0.1`) |
| ARP Priority | 8 |
| Use-cases | Smartphone data, video streaming, mobile broadband |

### Slice 2 — mMTC (Massive Machine-Type Communications)

| Parameter | Value |
|-----------|-------|
| SST | 2 |
| DNN | `iot` |
| UE AMBR DL / UL | 1 Mbps / 1 Mbps |
| 5QI | 9 (Non-GBR, low priority) |
| Packet Delay Budget | 300 ms |
| IP Pool | `10.46.0.0/16` (GW `10.46.0.1`) |
| ARP Priority | 15 (lowest) |
| Use-cases | Smart meters, environmental sensors, low-power IoT |

### Slice 3 — URLLC (Ultra-Reliable Low-Latency Communications)

| Parameter | Value |
|-----------|-------|
| SST | 3 |
| DNN | `urllc` |
| UE AMBR DL / UL | 10 Mbps / 5 Mbps |
| 5QI | 1 (GBR) |
| Packet Delay Budget | 100 ms |
| Packet Error Rate | 10⁻² |
| IP Pool | `10.47.0.0/16` (GW `10.47.0.1`) |
| ARP Priority | 1 (highest) |
| Use-cases | Industrial automation, V2X communications, remote surgery |

---

## Control-Plane Slice Selection Flow

```
UE                gNB              AMF              NSSF              SMF
 |                 |                |                 |                 |
 |── Registration ─►               |                 |                 |
 |   (configured-NSSAI: 1,2,3)     |                 |                 |
 |                 |── NGAP Init ──►|                 |                 |
 |                 |   (requested-  |                 |                 |
 |                 |    NSSAI: 1)   |                 |                 |
 |                 |                |── NSSelection ─►|                 |
 |                 |                |   (S-NSSAI=1)   |                 |
 |                 |                |◄── Allowed ─────|                 |
 |                 |                |   NSSAI         |                 |
 |                 |                |──────────────────────── PDU Sess ─►|
 |                 |                |                 |   (DNN=internet)|
 |◄──────────────── Registration Accept ─────────────────────────────── |
 |   (allowed-NSSAI: 1,2,3)        |                 |                 |
```

---

## Data-Plane IP Assignment per Slice

| Slice | SST | DNN | UE IP Range | Gateway |
|-------|-----|-----|-------------|---------|
| eMBB | 1 | internet | 10.45.0.2–10.45.255.254 | 10.45.0.1 |
| mMTC | 2 | iot | 10.46.0.2–10.46.255.254 | 10.46.0.1 |
| URLLC | 3 | urllc | 10.47.0.2–10.47.255.254 | 10.47.0.1 |

---

## Configuration Files Modified

### Open5GS Docker Configs (`docker/configs/`)

| File | Change |
|------|--------|
| `amf.yaml` | `plmn_support.s_nssai` lists SST 1, 2, 3 |
| `nssf.yaml` | `nsi` entries for SST 1, 2, 3 (all pointing to NRF) |
| `smf.yaml` | `session` pools with per-DNN subnets for all 3 slices |

### UERANSIM Configs (`docker/ueransim-config/`)

| File | Change |
|------|--------|
| `nr-gnb.yaml` | `slices` list: SST 1, 2, 3 |
| `nr-ue.yaml` | `configured-nssai`: SST 1, 2, 3; `default-nssai`: SST 1 |

### Kubernetes ConfigMaps (`k8s/manifests/`)

| Manifest | Change |
|----------|--------|
| `10-amf.yaml` | `plmn_support.s_nssai`: SST 1, 2, 3 |
| `08-nssf.yaml` | `nsi` entries: SST 1, 2, 3 |
| `11-smf.yaml` | `session` pools: internet/iot/urllc |
| `14-ue.yaml` | `configured-nssai`: SST 1, 2, 3 |
| `15-subscriber-init.yaml` | 3-slice subscriber with per-slice AMBR |

---

## Switching the UE to a Different Slice

The default PDU session uses **eMBB (SST=1, DNN=internet)**.  
To test a different slice, edit `docker/ueransim-config/nr-ue.yaml`:

**mMTC (IoT) slice:**
```yaml
sessions:
  - type: 'IPv4'
    apn: 'iot'
    slice:
      sst: 2
```

**URLLC slice:**
```yaml
sessions:
  - type: 'IPv4'
    apn: 'urllc'
    slice:
      sst: 3
```

Then restart UERANSIM:
```bash
docker compose -f docker/docker-compose.yml restart ueransim-ue
```

Verify the assigned IP falls in the correct pool:
```bash
docker exec ueransim-ue ip addr show uesimtun0
# eMBB  → 10.45.x.x
# mMTC  → 10.46.x.x
# URLLC → 10.47.x.x
```

---

## Subscriber Database Schema (MongoDB)

Each slice is stored as an entry in the `slice` array of the subscriber document.
AMBR `unit` encoding: `0`=bps, `1`=Kbps, `2`=Mbps, `3`=Gbps.

```js
slice: [
  { sst: 1, session: [{ name: 'internet', ambr: { dl: {value:100,unit:2}, ul: {value:50,unit:2} } }] },
  { sst: 2, session: [{ name: 'iot',      ambr: { dl: {value:1,  unit:2}, ul: {value:1, unit:2} } }] },
  { sst: 3, session: [{ name: 'urllc',    ambr: { dl: {value:10, unit:2}, ul: {value:5, unit:2} } }] }
]
```

---

## Verification Steps

### 1. Confirm NSSF registers all 3 slices
```bash
docker compose -f docker/docker-compose.yml logs nssf | grep -i "nsi\|sst\|slice"
```

### 2. Confirm AMF advertises all 3 slices to gNB
```bash
docker compose -f docker/docker-compose.yml logs amf | grep -i "s_nssai\|slice\|allowed"
```

### 3. Confirm UE receives allowed-NSSAI with SST 1, 2, 3
```bash
docker compose -f docker/docker-compose.yml logs ueransim-ue | grep -i "nssai\|slice"
```

### 4. Verify per-slice IP assignment (eMBB default)
```bash
docker exec ueransim-ue ip addr show uesimtun0
# Expected: inet 10.45.x.x/24
```

---

## References

- 3GPP TS 23.501 §5.15 — Network Slicing
- 3GPP TS 23.503 §6.3 — Policy and Charging Control for Slices
- Open5GS documentation: https://open5gs.org/open5gs/docs/
- UERANSIM: https://github.com/aligungr/UERANSIM
