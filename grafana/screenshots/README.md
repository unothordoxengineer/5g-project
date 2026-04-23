# Grafana Dashboard Screenshots — Phase 4 Load Test

## How to View and Screenshot the Dashboards

### 1. Start port-forwards (if not already running)
```bash
kubectl port-forward svc/prometheus-prometheus -n monitoring 9090:9090 &
kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80 &
```

### 2. Open Grafana
- URL: http://localhost:3000
- Username: `admin`
- Password: `open5gs`

### 3. Grafana Data Snapshots (embedded data from load test)
These snapshots contain the actual time-series data captured during the Phase 4 load test:

| Dashboard | Snapshot URL |
|-----------|-------------|
| NF CPU & Memory | http://localhost:3000/dashboard/snapshot/NmRUqxZuVnJGxiLaoOv9LMccBXYdevRt |
| UE Sessions | http://localhost:3000/dashboard/snapshot/TjktNwJJ7Xs8CCpkqJPjoAeZ0bFdsxjF |
| Autoscaling (UPF HPA) | http://localhost:3000/dashboard/snapshot/8ooEh1rDgImrGKWq4rEb9077lpmlz7Rw |
| Throughput | http://localhost:3000/dashboard/snapshot/XGufa7W4VZEZh3HDRDG9ddW6uHZxicgO |

### 4. Live Dashboards (with real-time data)
Navigate to: Dashboards → Browse → Open5GS folder

| Dashboard | UID | What it shows |
|-----------|-----|---------------|
| Open5GS — NF CPU & Memory | `open5gs-nf-cpu-mem` | CPU % and memory for all 14 pods |
| Open5GS — UE Sessions | `open5gs-ue-sessions` | gNB count, RAN UEs, PDU sessions |
| Open5GS — Autoscaling | `open5gs-autoscaling` | UPF HPA replicas, CPU vs 70% threshold |
| Open5GS — Throughput | `open5gs-throughput` | UPF GTP packets/sec, bytes/sec |

### 5. What to screenshot for the FYP report

#### Dashboard 1 — NF CPU & Memory
- Time range: last 1h (set to cover the load test)
- Key: MongoDB CPU spike (~10%), UPF CPU spike during Phase C

#### Dashboard 2 — UE Sessions
- Time range: last 1h
- Key: gnb=1, ran_ue=1, smf_sessions=1 (baseline)

#### Dashboard 3 — Autoscaling ⭐ (most important for FYP)
- Time range: last 1h
- Key: HPA replica count plot showing 1→2→3→4→3→2→1 scale-up/down
- Key: UPF CPU vs 70% threshold line (CPU exceeded threshold during load)
- Annotation markers for scale events

#### Dashboard 4 — Throughput
- Time range: last 1h
- Key: UPF GTP in/out packet counts

### 6. Screenshot command (macOS)
```bash
# After opening each dashboard in browser, use:
# Cmd+Shift+4, then drag to select the dashboard area
# Or use the Grafana "Share" → "Export" → "Render Image" button
#   (requires grafana-image-renderer plugin — install with helm upgrade if needed)
```

### 7. Install image renderer for automated PNG export
```bash
helm upgrade prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --reuse-values \
  --set grafana.imageRenderer.enabled=true
```

## Load Test Summary (captured in data/raw/)

| Phase | Duration | Load | UPF Replicas | Peak CPU |
|-------|----------|------|--------------|----------|
| A — Baseline | 90s | ~0% (idle) | 1 | <1% |
| B — Moderate | 90s | 20 CPU workers | 1→2 | 76% → 100% |
| C — High | 120s | 64 CPU workers | 2→3 | 100%+ |
| D — Recovery | 300s | idle | 4→3→2→1 | <2% |

**HPA scale-up confirmed:** 1 → 4 replicas during load  
**HPA scale-down confirmed:** 4 → 1 replicas during recovery (5-min stabilization)  
**UPFHighCPU alert:** FIRED at 07:22:35 UTC (threshold: 0.35 cores = 70% of 500m limit)
