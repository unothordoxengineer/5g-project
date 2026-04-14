# CLAUDE.md — Project Context for Claude Code
# Cloud-Native 5G Standalone Core with AI/ML Analytics
# Nigel Farai Kadzinga | Harare Institute of Technology | Final Year Project 2026

---

## WHO I AM

- **Name:** Nigel Farai Kadzinga
- **Institution:** Harare Institute of Technology (HIT), Zimbabwe
- **Department:** Electronic Engineering
- **Project:** Final Year Project — Cloud-Native 5G Standalone Core with AI/ML Analytics
- **Timeline:** April 2026 — June 2026 (10 weeks remaining)
- **Target Grade:** Distinction (70%+)
- **GitHub:** https://github.com/unothordoxengineer/5g-project

---

## HARDWARE & ENVIRONMENT

- **Machine:** MacBook Air M1 (Apple Silicon, arm64)
- **RAM:** 8GB
- **Storage:** 256GB (37GB free at project start)
- **OS:** macOS Tahoe 26.4
- **Shell:** zsh
- **Key paths:**
  - Project root: `~/5g-project/`
  - Open5GS source: `~/5g-project/open5gs/`
  - Open5GS binaries: `~/5g-project/open5gs/build/src/`
  - Open5GS configs: `~/5g-project/open5gs/build/configs/open5gs/`
  - UERANSIM: `~/5g-project/ueransim/` (once cloned)
  - Docs/journal: `~/5g-project/docs/`

---

## PROJECT OVERVIEW

### Research Problem
Legacy telecom infrastructure (EPC) costs $2-5M per hardware cycle, has 12-18 week procurement cycles, wastes 40-60% resources during off-peak, and operates reactively. 5G demands sub-millisecond latency, massive IoT density, dynamic slicing, and elastic scaling — which hardware cannot satisfy.

### Research Gap
Limited empirical evidence quantifying cloud-native 5G core performance, AI/ML effectiveness, and economic viability with real measurements on accessible hardware.

### Main Objective
To design, implement, and evaluate a cloud-native 5G Standalone core with integrated AI/ML analytics, quantifying infrastructure performance, operational intelligence, and economic trade-offs.

### Four-Layer Architecture
```
Layer 1: RAN Simulation      → UERANSIM (gNB + UE)
Layer 2: 5G Core             → Open5GS (AMF, SMF, UPF, NRF, UDM, UDR, AUSF, PCF, BSF, NSSF)
Layer 3: Telemetry           → Prometheus + Grafana
Layer 4: AI/ML Analytics     → Python (scikit-learn, statsmodels)
```

### Data Flow
```
UERANSIM Traffic → Open5GS Processing → Prometheus Metrics → ML Models → Insights
```

---

## TECHNOLOGY STACK

### Infrastructure
- **Docker** — containerise all 10 NFs
- **Kubernetes (kind locally, AWS EKS for cloud deployment)** — orchestration + autoscaling
- **Helm** — K8s package manager
- **kubectl** — K8s CLI

### 5G Stack
- **Open5GS v2.7.2** — 5G SA core (compiled from source)
- **UERANSIM v3.2.6** — gNB and UE simulation

### Observability
- **Prometheus** — metrics collection (scrapes every 15s)
- **Grafana** — dashboards and visualisation
- **CloudWatch** — AWS monitoring (Phase 3+)

### AI/ML
- **Python 3.11+**
- **scikit-learn** — Isolation Forest (anomaly), k-Means (clustering)
- **statsmodels / pmdarima** — ARIMA forecasting
- **pandas, numpy** — data manipulation
- **matplotlib, seaborn** — publication-quality graphs
- **Jupyter Lab** — interactive notebooks

### Cloud (Phase 3+)
- **AWS EKS** — managed Kubernetes cluster
- **AWS EC2** — worker nodes
- **AWS CloudWatch** — cloud monitoring
- **eksctl** — EKS cluster management

### Documentation
- **LaTeX / Overleaf** — final report
- **GitHub** — version control (commit daily)

---

## CURRENT STATUS (Update this section as phases complete)

### ✅ COMPLETED

**Environment Setup (Day 1-2)**
- Homebrew 5.1.3, Git 2.53.0, kind 0.31.0, kubectl, helm installed
- Docker Desktop configured: 4 CPUs, 5GB RAM, 60GB disk
- GitHub repo created and linked
- MongoDB 7.0 installed and running via brew services

**Open5GS Build (Day 2-3)**
- All 15+ M1/macOS Tahoe dependency issues resolved:
  - libyaml .pc file created manually
  - libmongoc-1.0.pc and libbson-1.0.pc compatibility files created
  - talloc, libgcrypt, libidn, gnutls, libgpg-error symlinked to /usr/local
  - bison upgraded to 3.8.2 (system bison too old)
  - PKG_CONFIG_PATH configured for all Homebrew libraries
  - idna.h, idn-int.h, gnutls headers, yaml.h, mongoc.h, bson headers all symlinked
- All 10 NF binaries compiled successfully:
  - open5gs-nrfd, open5gs-amfd, open5gs-smfd, open5gs-upfd
  - open5gs-udmd, open5gs-udrd, open5gs-ausfd, open5gs-pcfd
  - open5gs-bsfd, open5gs-nssfd, open5gs-scpd
- NRF confirmed running on http://127.0.0.10:7777

**Loopback Aliases Configured**
```
127.0.0.4  → SMF
127.0.0.5  → AMF
127.0.0.7  → UPF
127.0.0.10 → NRF
127.0.0.11 → AUSF
127.0.0.12 → UDM
127.0.0.13 → PCF
127.0.0.14 → NSSF
127.0.0.15 → BSF
127.0.0.20 → UDR
127.0.0.200 → SCP
```

**UERANSIM**
- gNB binary built successfully

**UERANSIM + N2 Integration (Day 3)**
- gNB built and connected to AMF via SCTP/NGAP (NG Setup successful)
- Root cause of SCTP failure: usrsctp `sctp_no_csum_on_loopback` only fires when
  src==dst IP. Fix: bind both AMF NGAP and gNB to `127.0.0.1` (not separate aliases).
  AMF NGAP: `0.0.0.0` or `127.0.0.5` both fail; `127.0.0.1` works.
  gNB amfConfigs: changed from `127.0.0.5` → `127.0.0.1`.
- UE registered successfully: SUPI=imsi-999700000000001 assigned IPv4=10.45.0.2
- PDU Session established on DNN=internet, SST=1
- TUN interface creation requires sudo (run `sudo ./build/nr-ue -c config/open5gs-ue.yaml`)

### ⏳ IN PROGRESS
- Run UE with sudo to create uesimtun0 TUN interface
- Ping test: ping 8.8.8.8 from UE (via UPF NAT)
- First UE registration + ping test

### 🔲 NOT STARTED
- Phase 2: Docker containerisation
- Phase 3: Kubernetes + autoscaling
- Phase 4: Prometheus + Grafana
- Phase 5: AI/ML models
- Phase 6: Stress testing
- Phase 7: Economic analysis + report

---

## 10-WEEK IMPLEMENTATION PLAN

### Phase 1: Environment + 5G Core (Weeks 1-2) ← CURRENT
**Goal:** UE registers, gets IP, pings external host
- ✅ Build Open5GS from source
- ✅ Build UERANSIM
- ⏳ Start all NFs, verify NRF registration
- ⏳ Add subscriber to MongoDB
- ⏳ First UE registration + ping test

### Phase 2: Docker Containerisation (Weeks 2-3)
**Goal:** All 10 NFs running in Docker containers
- Write Dockerfiles for all NFs
- Set resource limits (AMF/SMF: 2 vCPU/2GB, UPF: 2 vCPU/4GB)
- Add health checks
- docker-compose.yml for full stack
- Verify registration still works

### Phase 3: Kubernetes + Autoscaling (Weeks 3-5)
**Goal:** HPA scales UPF under load, demonstrated and timed
- kind cluster (3 nodes) locally
- K8s manifests: Deployment, Service, ConfigMap, HPA
- metrics-server for HPA
- HPA target: CPU >70%, min 1 pod, max 5 pods
- Load test to trigger scaling
- AWS EKS deployment of same manifests

### Phase 4: Telemetry (Weeks 5-6)
**Goal:** Live Grafana dashboards + CSV data export for ML
- kube-prometheus-stack via Helm
- 4 dashboards: NF CPU/Memory, UE Sessions, Autoscaling, Throughput
- Prometheus alerts at CPU >70%
- Export time-series CSV for ML training
- Minimum 72 hours of data across varied load conditions

### Phase 5: AI/ML Models (Weeks 6-8)
**Goal:** 3 trained models meeting all metric targets

**Model 1 — Anomaly Detection (Isolation Forest)**
- Input: CPU%, memory%, session count, pod restarts per 5-min window
- Train/test split: 80/20
- Target: Recall >90%, FPR <15%
- Output: Real-time anomaly score per NF

**Model 2 — Traffic Forecasting (ARIMA)**
- Input: Hourly UE session count time series
- Use auto_arima (pmdarima) for optimal (p,d,q)
- Target: MAPE <15% on 6-hour forecast
- Output: 6-hour traffic forecast updated hourly

**Model 3 — Workload Clustering (k-Means)**
- Input: Multi-dimensional feature vector (CPU, memory, sessions, throughput)
- Elbow method to determine optimal k
- Target: Silhouette score >0.5
- Output: 4 clusters — morning commute, daytime, evening peak, overnight

### Phase 6: Stress Testing (Weeks 8-9)
**Goal:** Empirical benchmark dataset + statistical analysis

**Scenario 1 — Diurnal:** 10→200→10 UEs over 4 hours
**Scenario 2 — Flash Crowd:** 10→200 UEs in 60s (repeat x5)
**Scenario 3 — Sustained:** 150 UEs steady for 2 hours

Metrics to collect: registration success rate, latency percentiles (p50/p95/p99), autoscaling response time, throughput, pod restart count

### Phase 7: Economic Analysis + Report (Weeks 9-10)
**Goal:** Submitted final report + demo video

Economic model:
- CAPEX comparison: hardware $2-5M vs cloud-native $0 capex
- OPEX: AWS compute cost per UE-hour at different scales
- Autoscaling efficiency: % resource waste fixed vs elastic
- Break-even analysis

Report structure (HIT format):
1. Abstract (250 words)
2. Introduction & Motivation
3. Literature Review (25+ citations, Harvard)
4. System Architecture & Design
5. Implementation (detailed)
6. Results & Analysis
7. Economic Analysis
8. Discussion & Limitations
9. Conclusion & Future Work
10. References
11. Appendix A: Full Code
12. Appendix B: Raw Data

---

## SUCCESS METRICS

### 5G Core Performance
| Metric | Target |
|--------|--------|
| UE Registration Success Rate | >99% |
| Session Setup Latency (p95) | <50ms |
| User Plane Forwarding | <5ms |
| Autoscaling Response Time | <120s |
| Sustained Throughput | >10 Gbps (EKS) |

### AI/ML Performance
| Model | Metric | Target |
|-------|--------|--------|
| Isolation Forest | Recall | >90% |
| Isolation Forest | False Positive Rate | <15% |
| ARIMA | MAPE (6h forecast) | <15% |
| k-Means | Silhouette Score | >0.5 |
| Any model | Early warning time | >5 min before impact |

---

## RESEARCH CONTEXT (From Seminar Paper)

Key validated results from prior research to target/exceed:
- Pod provisioning: 47s median (target <120s) ✓
- Registration success: 99.7% (target >99%) ✓
- PDU session latency: 24.3ms mean (target <50ms) ✓
- Anomaly detection recall: 94% (target >90%) ✓
- False positive rate: 11% (target <15%) ✓
- Forecast MAPE: 7.2% for 24h (target <15%) ✓
- Clustering silhouette: 0.67 (target >0.5) ✓
- Cost reduction via autoscaling: 38%
- 4 operational clusters: morning commute, daytime, evening peak, overnight

---

## HOW CLAUDE CODE SHOULD BEHAVE

### Always
- Run commands directly — don't ask for permission for standard operations
- Fix errors automatically — paste the error, diagnose, fix, retry
- Commit to GitHub after every major milestone: `git add . && git commit -m "..." && git push`
- Explain what each command does in plain English (for report documentation)
- Generate publication-quality code with comments (goes into final report appendix)
- Keep a running log of what was completed (feeds into the Word document report)

### Priority Order
1. Get things working first
2. Then make them clean and documented
3. Then optimise

### When Stuck
- Try the fix maximum 3 times
- If still failing, explain the root cause clearly so Nigel can make a decision
- Always suggest a fallback/alternative approach

### Code Style
- Python: PEP8, with docstrings, type hints where appropriate
- Shell scripts: bash, with comments explaining each section
- Kubernetes YAML: well-commented, with resource limits always set
- All code goes to GitHub

### DO NOT
- Skip error handling
- Use placeholder/TODO code without flagging it
- Make assumptions about AWS credentials without asking
- Run `sudo` commands without explaining why they're needed

---

## KEY COMMANDS REFERENCE

### Start all NFs (minimal set for UE registration)
```bash
cd ~/5g-project/open5gs
./build/src/nrf/open5gs-nrfd -c build/configs/open5gs/nrf.yaml &
sleep 2
./build/src/scp/open5gs-scpd -c build/configs/open5gs/scp.yaml &
sleep 2
./build/src/udr/open5gs-udrd -c build/configs/open5gs/udr.yaml &
./build/src/udm/open5gs-udmd -c build/configs/open5gs/udm.yaml &
./build/src/ausf/open5gs-ausfd -c build/configs/open5gs/ausf.yaml &
sleep 2
./build/src/amf/open5gs-amfd -c build/configs/open5gs/amf.yaml &
./build/src/smf/open5gs-smfd -c build/configs/open5gs/smf.yaml &
sudo ./build/src/upf/open5gs-upfd -c build/configs/open5gs/upf.yaml &
```

### Stop all NFs
```bash
killall open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd open5gs-ausfd open5gs-amfd open5gs-smfd open5gs-upfd 2>/dev/null
```

### Add loopback aliases (run once after reboot)
```bash
sudo ifconfig lo0 alias 127.0.0.4 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.5 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.7 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.10 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.11 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.12 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.13 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.14 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.15 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.20 netmask 255.255.255.255
sudo ifconfig lo0 alias 127.0.0.200 netmask 255.255.255.255
```

### Check MongoDB is running
```bash
brew services list | grep mongodb
```

### Build NF binaries
```bash
cd ~/5g-project/open5gs
ninja -C build src/amf/open5gs-amfd src/smf/open5gs-smfd src/upf/open5gs-upfd src/nrf/open5gs-nrfd src/udm/open5gs-udmd src/ausf/open5gs-ausfd src/pcf/open5gs-pcfd src/bsf/open5gs-bsfd src/nssf/open5gs-nssfd src/udr/open5gs-udrd src/scp/open5gs-scpd
```

---

## KNOWN M1/macOS TAHOE ISSUES AND FIXES

These were resolved during build — document in report:

1. **libyaml .pc missing** → Created manually at `/opt/homebrew/lib/pkgconfig/libyaml.pc`
2. **libmongoc renamed to libmongoc2** → Created compatibility `libmongoc-1.0.pc`
3. **bson headers in versioned path** → Copied to `/usr/local/include/bson/`
4. **gcrypt/idn/gnutls not in system path** → Symlinked to `/usr/local/lib/` and `/usr/local/include/`
5. **bison too old (macOS system)** → Installed bison 3.8.2 via Homebrew, prepended to PATH
6. **loopback addresses missing** → Added via `ifconfig lo0 alias` (not persistent across reboots)
7. **PKG_CONFIG_PATH not set** → Added full path to ~/.zprofile
8. **talloc version mismatch warning** → Non-blocking, ignore

---

## DELIVERABLES CHECKLIST

### Technical
- [ ] Working 5G SA core (Open5GS) with UERANSIM integration
- [ ] Complete Dockerfiles for all NFs
- [ ] docker-compose.yml for full stack
- [ ] Kubernetes manifests (Deployment, Service, ConfigMap, HPA)
- [ ] kind cluster config + AWS EKS deployment
- [ ] Prometheus config + 4 Grafana dashboards (JSON)
- [ ] Isolation Forest anomaly model (.pkl + evaluation)
- [ ] ARIMA forecasting model (evaluated, MAPE documented)
- [ ] k-Means clustering model (silhouette score documented)
- [ ] Load generation scripts (3 scenarios)
- [ ] Raw benchmark dataset (labelled CSV)
- [ ] Statistical analysis notebook
- [ ] Economic model Python script + break-even chart

### Documentation
- [ ] Final report (HIT template, Harvard refs, 25+ citations)
- [ ] GitHub README with reproduction instructions
- [ ] 5-10 min screen-recorded demo video
- [ ] Viva presentation slides
- [ ] Project journal (docs/journal.md)

---

## ACADEMIC REFERENCES (From Seminar Paper — Use in Report)

1. 3GPP TS 23.501 — 5G System Architecture
2. 3GPP TS 24.501 — NAS Protocol for 5G
3. ETSI GS NFV 002 — NFV Architectural Framework
4. Open5GS Project — https://open5gs.org
5. UERANSIM — https://github.com/aligungr/UERANSIM
6. Prometheus — https://prometheus.io/docs
7. Grafana — https://grafana.com/docs
8. CNCF Kubernetes — https://kubernetes.io/docs
9. AWS EKS Documentation
10. Gupta et al. (2022) — ML for Anomaly Detection in 5G, IEEE Access
11. Salinas et al. (2023) — DeepAR Probabilistic Forecasting, JMLR
12. Foukas et al. (2017) — Network Slicing in 5G, IEEE Comm. Magazine
13. GSMA (2023) — Cloud-Native Network Functions Intelligence Report
14. Nokia (2022) — 5G Core Network Architecture
15. Ericsson (2023) — Cloud Native Infrastructure for 5G Core

---

*This file is read automatically by Claude Code at session start.*
*Update the CURRENT STATUS section after each milestone.*
*Last updated: April 14, 2026*
