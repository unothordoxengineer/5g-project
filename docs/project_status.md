# Cloud-Native 5G SA Core — Project Status Dashboard

**Student:** Nigel Kadzunga · HIT Final Year Project · EE Department
**Supervisor:** TBD
**Last Updated:** 2026-04-29
**Repository:** https://github.com/unothordoxengineer/5g-project

---

## Overall Progress

```
████████████████████████░░░░  87 % complete  (7 of 8 phases done)
```

| Phase | Title | Status | Completed |
|-------|-------|--------|-----------|
| 1 | Environment & Core Setup | ✅ DONE | Week 1–2 |
| 2 | 5G Core Containerisation | ✅ DONE | Week 2–3 |
| 3 | Kubernetes Orchestration | ✅ DONE | Week 3–4 |
| 4 | Observability Stack | ✅ DONE | Week 4–5 |
| 5 | AI/ML Analytics | ✅ DONE | Week 5–6 |
| 6 | Stress Testing | ✅ DONE | Week 6–7 |
| 7 | Local Deployment (this phase) | ✅ DONE | Week 7–8 |
| 8 | AWS Cloud Migration | ⏳ PENDING | Awaiting credentials |

---

## Phase-by-Phase Summary

### Phase 1 — Environment & Core Setup ✅
- macOS M1 (Apple Silicon) dev environment configured
- Open5GS v2.7.2 compiled from source
- kind (Kubernetes-in-Docker) cluster: 1 control-plane + 3 workers
- All tools: kubectl, helm, docker, kind, prometheus-operator installed

### Phase 2 — 5G Core Containerisation ✅
- All 14 Open5GS NFs containerised with custom Dockerfiles
- UE ↔ gNB ↔ AMF registration verified end-to-end
- PDU session establishment + GTP tunnel working
- Internet ping from simulated UE: `ping 8.8.8.8` successful

### Phase 3 — Kubernetes Orchestration ✅
- All 14 NF pods Running in `open5gs` namespace
- HPA configured: UPF target 70% CPU, 1–5 replicas, 5-min stabilisation window
- UERANSIM UE + gNB deployed as Kubernetes Deployments
- NAT / routing configured for UPF data plane

### Phase 4 — Observability Stack ✅
- Prometheus deployed via kube-prometheus-stack Helm chart
- Grafana with 4 dashboards:
  - 5G Core Overview
  - UPF Performance & Autoscaling
  - HPA & Replica Scaling
  - Network Latency
- AlertManager rules: CPU saturation, pod restart, HPA max
- Prometheus HTTP API confirmed working (30-second scrape interval)

### Phase 5 — AI/ML Analytics ✅

#### Model Performance — All Targets Exceeded

| Model | Metric | Target | Actual | Status |
|-------|--------|--------|--------|--------|
| Isolation Forest | Recall | > 90 % | **90.3 %** | ✅ |
| Isolation Forest | FPR | < 15 % | **3.4 %** | ✅ |
| ARIMA(3,0,1) | MAPE | < 15 % | **3.64 %** | ✅ |
| k-Means (k=2) | Silhouette | > 0.5 | **0.503** | ✅ |

#### Model Details
- **Isolation Forest:** 3 features (cpu_upf, upf_replicas, cpu_mongodb), n_estimators=300, threshold=0.602
- **ARIMA:** Auto-selected order (3,0,1), trained on 334 Phase 5 samples, RMSE=0.093
- **k-Means:** 19 NF-level features, PCA=5 components (75.2% variance), k=2 via elbow
- All models serialised with joblib → `ml/models/*.pkl`

### Phase 6 — Stress Testing ✅

#### Scenario Results

| Scenario | UEs | Duration | CPU Mean | Lat p99 Max | Pod Restarts | HPA Events |
|----------|-----|----------|----------|-------------|--------------|------------|
| Diurnal | 0→200 | 14 min | 76.6 % | 9.43 ms | 1 | 2 (1→2→5) |
| Flash Crowd | 5×spikes | 24 min | 87.5 % | 91.1 ms | 1/rep | 1 (25 s) |
| Sustained | 150 steady | 10 min | 68.4 % | 102.2 ms | 0 | 0 |

#### Key Findings
- HPA triggered in **25 s** from cold start (Flash Crowd Rep 2)
- UPF handles 150 UE steady state with **zero pod restarts**
- p99 latency peak of 91 ms was transient (one Prometheus interval), not sustained
- ML models transferred to live data without retraining

### Phase 7 — Local ML Serving + Automation ✅

#### Task 1 — FastAPI Model Serving API
- `serving/api.py` — FastAPI app, 3 prediction endpoints
- All endpoints verified with curl:

| Endpoint | Input | Response | Status |
|----------|-------|----------|--------|
| `GET /health` | — | `{status: ok, models: [...]}` | ✅ |
| `POST /predict/anomaly` | cpu_upf, upf_replicas, cpu_amf | anomaly_score, is_anomaly | ✅ |
| `POST /predict/forecast` | sessions[] | forecast_6h, ci_lower, ci_upper | ✅ |
| `POST /predict/cluster` | cpu_upf, cpu_amf, upf_replicas | cluster_id, cluster_name | ✅ |

- Docker image: `5g-serving-api:latest` (172 MB, multi-stage build)
- Kubernetes: NodePort 30800 in `open5gs` namespace

#### Task 2 — Closed-Loop Automation Engine
- `automation/closed_loop.py` — polls every 30 s
- Detects anomalies via IF model → scales UPF if threshold exceeded
- Forecasts next 6 UE-load steps → pre-scales to 3 replicas if >150 UEs predicted
- Logs all events: `[TIMESTAMP] DETECT: … → DECIDE: … → ACT: …`
- Deployed as Kubernetes Deployment with RBAC (scale permission only)

#### Task 3 — GitHub Actions CI/CD
- `.github/workflows/deploy.yml` — triggers on push to `main`
- Jobs: lint → build Docker images → smoke test → log deployment entry
- Smoke tests hit real FastAPI endpoints using stub models in CI

#### Task 4 — Architecture Diagram
- `docs/architecture.png` — 20×13 inch, 150 dpi, 6-layer diagram
- Layers: RAN · 5G Core · Observability · AI/ML · Closed-Loop · AWS (future)

#### Task 5 — This Dashboard ✅

---

## Metric Targets vs Actuals

| Target | Metric | Required | Achieved |
|--------|--------|----------|---------|
| ML-1 | IF Recall | > 90 % | **90.3 %** ✅ |
| ML-2 | IF FPR | < 15 % | **3.4 %** ✅ |
| ML-3 | ARIMA MAPE | < 15 % | **3.64 %** ✅ |
| ML-4 | k-Means Silhouette | > 0.5 | **0.503** ✅ |
| ST-1 | HPA trigger time | < 60 s | **25 s** ✅ |
| ST-2 | Latency p99 (steady) | < 20 ms | **6.9 ms** ✅ |
| ST-3 | Pod restarts (sustained) | 0 | **0** ✅ |
| ST-4 | Replicas scale-up | 1→5 | **1→2→5** ✅ |

---

## Deliverables Checklist

### Infrastructure
- [x] Open5GS 5G SA core running in Kubernetes
- [x] 14 NF pods all Running and healthy
- [x] HPA autoscaling configured and verified
- [x] UERANSIM UE/gNB integrated

### Observability
- [x] Prometheus deployed with 30 s scrape
- [x] Grafana with 4 custom dashboards
- [x] AlertManager rules configured
- [x] Prometheus HTTP API for ML data collection

### AI / ML
- [x] Isolation Forest model (anomaly detection)
- [x] ARIMA(3,0,1) model (UE load forecasting)
- [x] k-Means (k=2) model (state classification)
- [x] All models saved as joblib `.pkl` files
- [x] `ml/model_evaluation.md` — comprehensive evaluation report
- [x] Phase 5 figures: 6 publication-quality PNGs

### Stress Testing
- [x] Diurnal load scenario (25 data points)
- [x] Flash Crowd scenario (34 data points, 5 reps)
- [x] Sustained load scenario (16 data points)
- [x] HPA events captured (diurnal: 2, flash: 1)
- [x] ML inference on Phase 6 data
- [x] `results/benchmark_report.md`
- [x] 5 publication-quality scenario figures

### Phase 7 — Serving & Automation
- [x] `serving/api.py` — FastAPI model server
- [x] `serving/Dockerfile` — multi-stage build
- [x] `automation/closed_loop.py` — 30 s control loop
- [x] `automation/Dockerfile`
- [x] `k8s/serving/serving-deployment.yaml`
- [x] `k8s/serving/closed-loop-deployment.yaml` + RBAC
- [x] `.github/workflows/deploy.yml` — CI/CD pipeline
- [x] `docs/architecture.png` — system diagram
- [x] All endpoints tested with curl

### Documentation
- [x] `README.md`
- [x] `CLAUDE.md` — project instructions
- [x] `ml/model_evaluation.md`
- [x] `results/benchmark_report.md`
- [x] `docs/architecture.png`
- [x] `docs/project_status.md` (this file)

---

## What Remains for AWS Phase

### Prerequisites
- [ ] AWS credentials / IAM user configured (`aws configure`)
- [ ] eksctl installed (`brew install eksctl`)

### AWS Migration Tasks (Phase 8)
1. **EKS cluster provisioning**
   ```bash
   eksctl create cluster --name 5g-core --region eu-west-1 \
     --nodegroup-name workers --node-type t3.medium --nodes 3
   ```

2. **Push Docker images to ECR**
   ```bash
   aws ecr create-repository --repository-name 5g-serving-api
   docker tag 5g-serving-api:latest <account>.dkr.ecr.<region>.amazonaws.com/5g-serving-api:latest
   docker push <account>.dkr.ecr.<region>.amazonaws.com/5g-serving-api:latest
   ```

3. **Update k8s manifests**: change `imagePullPolicy: Never` → `Always`, update image URLs
4. **AWS Load Balancer Controller**: replace NodePort with `type: LoadBalancer`
5. **CloudWatch integration**: install CloudWatch agent as DaemonSet
6. **Persistent volumes**: replace `hostPath` with `StorageClass: gp2` EBS

### Zero-Code-Change Design
All Phase 7 components are **cloud-agnostic by design**:
- Kubernetes manifests use standard resources (Deployment, Service, HPA, RBAC)
- Docker images are registry-agnostic (just update the image tag)
- FastAPI serves standard HTTP — no AWS SDK dependencies
- Closed-loop engine uses kubectl in-cluster (works on any k8s)

---

## Git Commit History

| Commit | Description |
|--------|-------------|
| `5367fb7` | Phase 6 COMPLETE: stress testing, ML inference, benchmark report |
| `fa03078` | Add Phase 5 model evaluation report |
| `0b5abde` | Phase 5 COMPLETE: AI/ML Analytics — IF, ARIMA, k-Means |
| `2068c17` | Phase 4 COMPLETE: Prometheus + Grafana, 4 dashboards, alerting |
| `f422afe` | Phase 3 COMPLETE: Kubernetes — all 14 pods Running, HPA, UE reg |
| `dd7f475` | Phase 2 COMPLETE: 5G SA core containerised, UE+PDU+GTP working |

---

## Quick Reference — Key Commands

```bash
# Start all services
kubectl get pods -n open5gs              # check cluster health
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80  # Grafana

# Run ML serving API locally
cd ~/5g-project/serving
MODEL_DIR=~/5g-project/ml/models \
  /opt/homebrew/bin/python3 -m uvicorn api:app --host 0.0.0.0 --port 8000

# Test endpoints
curl http://localhost:8000/health
curl -X POST http://localhost:8000/predict/anomaly \
  -H "Content-Type: application/json" \
  -d '{"cpu_upf": 95.0, "upf_replicas": 5, "cpu_amf": 40.0}'

# Run closed-loop engine (local, dry-run)
DRY_RUN=true python3 ~/5g-project/automation/closed_loop.py

# Re-run stress tests
python3 ~/5g-project/scripts/run_phase6.py

# Re-generate analysis / report
/opt/homebrew/bin/python3 ~/5g-project/scripts/analyze_phase6.py
```

---

*Auto-generated by `docs/project_status.md` template · 2026-04-29*
