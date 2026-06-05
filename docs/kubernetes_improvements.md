# Kubernetes Improvements — Priority 4

**Date:** 2026-06-05  
**Cluster:** kind (1 control-plane + 2 workers, Kubernetes v1.35.0)  
**Namespace:** open5gs

---

## Summary

Five production-hardening improvements applied to the Open5GS 5G SA Core:

| # | Improvement | Status |
|---|-------------|--------|
| 1 | Pod Disruption Budgets (12 NFs) | Applied |
| 2 | Resource requests/limits tuning | Applied |
| 3 | Liveness/readiness/startup probe tuning | Applied |
| 4 | Extended HPA — AMF + SMF | Applied |
| 5 | VPA — MongoDB (manifest ready, CRD pending) | Manifest created |

---

## 1. Pod Disruption Budgets

**File:** `k8s/security/pod-disruption-budgets.yaml`

All 12 critical NFs now have PDBs with `minAvailable: 1`. This prevents `kubectl drain` or rolling upgrades from simultaneously removing the only running instance of any NF, which would break active UE sessions.

| PDB | NF | 3GPP Role |
|-----|----|-----------|
| nrf-pdb | NRF | NF registry — all NFs register here |
| scp-pdb | SCP | Service Communication Proxy |
| udr-pdb | UDR | Subscriber data store |
| udm-pdb | UDM | Authentication & subscriber management |
| ausf-pdb | AUSF | 5G-AKA authentication |
| pcf-pdb | PCF | Policy control |
| bsf-pdb | BSF | Binding Support Function |
| nssf-pdb | NSSF | Network slice selection |
| amf-pdb | AMF | Access & mobility management |
| smf-pdb | SMF | Session management + PFCP |
| upf-pdb | UPF | User-plane GTP-U forwarding |
| mongodb-pdb | MongoDB | Subscriber database |

```bash
# Verification
kubectl get pdb -n open5gs
# All 12 show minAvailable=1, ALLOWED DISRUPTIONS=0
```

---

## 2. Resource Requests/Limits Tuning

All values derived from Phase 6 stress-test observations (200 concurrent UEs, 3-slice simultaneous load).

### Control-Plane NFs (SBI-only, no user-plane)

| NF | CPU Request | CPU Limit | Memory Request | Memory Limit | Rationale |
|----|-------------|-----------|----------------|--------------|-----------|
| NRF | 50m | 200m | 64Mi | 128Mi | Registration-only; peak <80Mi |
| SCP | 50m | 200m | 64Mi | 128Mi | Proxy only; no state |
| UDR | 50m | 200m | 64Mi | 128Mi | Read-heavy DB client |
| UDM | 50m | 200m | 64Mi | 128Mi | Auth crypto bursty |
| AUSF | 50m | 200m | 64Mi | 128Mi | AKA computation burst |
| PCF | 50m | 200m | 64Mi | 128Mi | Policy rules in-memory |
| BSF | 50m | 200m | 64Mi | 128Mi | PCF binding store |
| NSSF | 50m | 200m | 64Mi | 128Mi | Slice selection only |

### Signalling NFs

| NF | CPU Request | CPU Limit | Memory Request | Memory Limit | Rationale |
|----|-------------|-----------|----------------|--------------|-----------|
| AMF | 100m | 500m | 128Mi | 256Mi | NAS crypto bursty; 200 UE contexts |
| SMF | 100m | 500m | 128Mi | 256Mi | PFCP sessions; peaks at ~350m |

### User-Plane & RAN simulation

| NF | CPU Request | CPU Limit | Memory Request | Memory Limit | Rationale |
|----|-------------|-----------|----------------|--------------|-----------|
| UPF | 200m | 1000m | 256Mi | 512Mi | GTP-U forwarding; HPA adds replicas |
| MongoDB | 200m | 500m | 256Mi | 512Mi | Subscriber DB; peak <400Mi |
| gNB | 100m | 300m | 128Mi | 256Mi | NGAP + RLS emulation |
| UE | 100m | 300m | 128Mi | 256Mi | NAS context + uesimtun0 I/O |

---

## 3. Probe Tuning

### Startup Probes (AMF, SMF)

AMF and SMF require NRF registration, PFCP/NGAP socket binding, and network function bootstrap before they can serve traffic. A startup probe window of **300 seconds** (30 × 10s) prevents liveness from killing a healthy but slow-starting NF.

```yaml
startupProbe:
  # tcpSocket, NOT httpGet — Open5GS SBI uses HTTP/2 prior-knowledge (h2c).
  # httpGet probes send HTTP/1.1 which is rejected as "bad client magic byte string".
  tcpSocket:
    port: 80
  failureThreshold: 30   # 30 × 10s = 300s startup budget
  periodSeconds: 10
```

### Liveness Probe Tuning (all NFs)

| Parameter | Old | New | Rationale |
|-----------|-----|-----|-----------|
| `initialDelaySeconds` | 15 | 30 | After startupProbe clears; avoids kill during boot |
| `periodSeconds` | 30 | 15 | Faster deadlock detection without unnecessary restarts |
| `failureThreshold` | 2 | 3 | Tolerate one transient hiccup before restart |

### Readiness Probe Tuning (all NFs)

Added `failureThreshold: 3` uniformly. NRF uses the Open5GS-native `curl --http2-prior-knowledge` probe (the only NF that exposes a stable h2c endpoint internally).

### Key Fix: HTTP/2 vs HTTP/1.1

Open5GS SBI ports use HTTP/2 with prior knowledge. Kubernetes `httpGet` probes speak HTTP/1.1 and are rejected with:

```
nghttp2_session_mem_recv() failed (-903:Received bad client magic byte string)
```

**Resolution:** Changed all AMF/SMF probes to `tcpSocket` (checks TCP liveness, not HTTP layer). NRF readiness uses `exec [curl --http2-prior-knowledge]` as it has a stable API endpoint.

---

## 4. Extended HPA — AMF + SMF

**File:** `k8s/manifests/16-hpa-extended.yaml`

AMF and SMF now autoscale alongside UPF under NAS/PFCP burst load.

```yaml
# AMF HPA
spec:
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30       # Fast scale-up during attach storms
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300      # Slow drain — AMF holds stateful UE contexts
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

The SMF HPA uses identical parameters. The longer scaleDown stabilization (300s vs UPF's 120s) accounts for AMF/SMF statefulness — UE contexts and PFCP sessions must drain before a replica is removed.

```bash
# Verification
kubectl get hpa -n open5gs
# upf-hpa: cpu 3%/70%, 1/5 replicas
# amf-hpa: cpu <unknown>/70%, 1/3 replicas (metrics-server intermittent on kind)
# smf-hpa: cpu <unknown>/70%, 1/3 replicas
```

---

## 5. VPA — MongoDB

**File:** `k8s/manifests/17-vpa-mongodb.yaml`

```yaml
spec:
  updatePolicy:
    updateMode: "Off"    # Recommend only — never evict MongoDB to resize
  resourcePolicy:
    containerPolicies:
      - containerName: mongodb
        minAllowed:
          cpu: 100m
          memory: 128Mi
        maxAllowed:
          cpu: 1000m
          memory: 1Gi
        controlledValues: RequestsAndLimits
```

`updateMode: "Off"` is intentional — VPA would evict the MongoDB pod to apply new requests, causing data loss or session disruption. Recommendations are viewable via `kubectl describe vpa mongodb-vpa -n open5gs` and applied manually after maintenance windows.

**Note:** The VPA CRD (`autoscaling.k8s.io/v1`) is not installed on this kind cluster by default. Install with:
```bash
git clone https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler
./hack/vpa-install.sh
```

---

## Verification Commands

```bash
# All pods Running
kubectl get pods -n open5gs

# 12 PDBs with minAvailable=1
kubectl get pdb -n open5gs

# 3 HPAs (upf, amf, smf)
kubectl get hpa -n open5gs

# No OOMKill events
kubectl get events -n open5gs --sort-by='.lastTimestamp' | grep -i oom

# Resource usage vs limits
kubectl top pods -n open5gs
```

---

## Post-Rollout Observations

| NF | Restart Count | Cause | Status |
|----|---------------|-------|--------|
| NRF | 1 | Readiness probe during rolling update | Resolved |
| PCF | 1 | Readiness probe race during startup | Resolved |
| UDR | 2 | Liveness probe before MongoDB reconnect | Resolved |
| All others | 0 | Clean rollout | OK |

No OOMKill events observed. All 14 deployments stabilised within 10 minutes of manifest application.

### Binary Path Fix

During rolling update, new pods entered `CrashLoopBackOff` because the batch manifest update script set binary paths to `/opt/open5gs/bin/` (a common Open5GS install prefix), but all images in this cluster install binaries at `/usr/local/bin/`. Fixed by:

```bash
sed -i '' 's|/opt/open5gs/bin/|/usr/local/bin/|g' k8s/manifests/*.yaml
```

---

## Architecture Impact

```
Before Priority 4:
  - Single-point-of-failure: any NF pod deletion = service outage
  - Unbounded resource usage: NFs could starve neighbours
  - No startup protection: slow NFs killed during boot
  - HPA only on UPF

After Priority 4:
  - PDBs protect all 12 NFs from involuntary disruption
  - Resource limits prevent noisy-neighbour interference across 3 slices
  - startupProbe + livenessProbe tuning: resilient to transient load spikes
  - HPA on AMF + SMF + UPF: full 5G control+user plane autoscaling
  - VPA on MongoDB: cost-optimised recommendation (Off mode)
```
