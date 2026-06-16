# Viva Preparation — Cloud-Native 5G SA Core FYP

**Candidate:** Nigel Farai Kadzinga · B.Eng Electronic Engineering · HIT Zimbabwe · 2026
**Last updated:** 2026-06-16

This document is the complete viva study guide. Every answer is drawn directly from the deployed system, measured data, and committed artefacts — not from textbooks.

---

## Contents

1. [Predictive Pre-Scaling](#1-predictive-pre-scaling-arima)
2. [5G Core Architecture & Protocol](#2-5g-core-architecture--protocol)
3. [Network Slicing](#3-network-slicing)
4. [Kubernetes & Orchestration](#4-kubernetes--orchestration)
5. [ML Pipeline & Models](#5-ml-pipeline--models)
6. [AWS Deployment & Cloud Architecture](#6-aws-deployment--cloud-architecture)
7. [Security](#7-security)
8. [Stress Testing & Statistical Validity](#8-stress-testing--statistical-validity)
9. [Comparison with Real Operators](#9-comparison-with-real-operators)
10. [General / Reflection](#10-general--reflection)
11. [Technical Deep-Dives](#11-technical-deep-dives)
12. [Design Decision Log](#12-design-decision-log)
13. [Demo Run-Through Checklist](#13-demo-run-through-checklist)

---

## 1. Predictive Pre-Scaling (ARIMA)

**Q: Your closed-loop engine does both reactive anomaly detection and proactive pre-scaling. What is the architectural difference, and why do you need both?**

A: The reactive path (step 2) is driven by SageMaker's IsolationForest anomaly-detector endpoint: once CPU or session load already crosses the anomaly threshold (score > 0.5849), it scales UPF up by one replica. This catches unexpected spikes but always reacts *after* the degradation has started.

The proactive path (step 2.5) uses a locally-loaded ARIMA(3,0,1) model to look 30 minutes ahead. It queries the rolling UE-count history buffer, runs `model.apply(history).forecast(steps=6)`, and if any of the six 5-minute forecast steps exceeds 100 UEs *and* the current replica count is below 3, it issues the scale command immediately — before any CPU or latency impact is visible. The two mechanisms complement each other: ARIMA handles predictable traffic ramps (e.g., morning rush), while IsolationForest handles sudden bursts that the time-series model did not anticipate.

---

**Q: Why did you choose ARIMA rather than Prophet or an LSTM for the local predictive model?**

A: ARIMA was selected for three reasons. First, it is lightweight — the trained `arima_model.pkl` is sub-megabyte and loads in milliseconds, making it viable inside the closed-loop polling thread without GPU or SageMaker invocation latency. Second, the UE-session time series exhibited stationarity after first differencing and clear autocorrelation structure (ACF/PACF plots confirmed AR(3) and MA(1) terms), which matches ARIMA's modelling assumptions well. Third, ARIMA provides interpretable coefficients, which is important for demonstrating causality in a research context. Prophet and LSTM would offer more flexibility for multi-seasonality but would also require far more training data and infrastructure to run locally.

---

**Q: How does the ARIMA model load, and what happens if the pickle file is absent or incompatible?**

A: The function `_load_arima_model()` implements a lazy singleton pattern: it checks the global `_arima_model` handle and returns it immediately on subsequent calls. On first call it opens `ARIMA_MODEL_PATH` (overridable via environment variable) and calls `pickle.load()`. If loading fails for any reason — file absent, pandas version incompatibility, or corruption — it catches the exception, logs a `WARNING`, and returns `None`. The caller `predict_and_prescale()` checks for `None` and returns an empty dict, so the control loop continues normally through step 3. The ARIMA step is therefore a best-effort enhancement, not a hard dependency.

---

**Q: What threshold did you choose for ARIMA-driven pre-scaling, and how did you select it?**

A: The threshold is 100 UEs (`PREDICTIVE_THRESH = 100`), set below the SageMaker forecast threshold of 150 UEs (`FORECAST_THRESH = 150`). The rationale is that the ARIMA forecast operates on a 30-minute horizon, so it must trigger *earlier* and at a *lower* level than the SageMaker endpoint, which acts on the immediate window. At 100 UEs the UPF CPU utilisation would be approaching 60–70%, which gives roughly a 10-minute buffer before SLA degradation. The value was calibrated against the UERANSIM load-test traces in Chapter 4, which showed UE ramp rates of 5–15 new sessions per poll period.

---

**Q: How do you prevent the proactive pre-scale from conflicting with the reactive anomaly scale in the same poll cycle?**

A: Both paths write to the same `_daily_stats["total_scale_events"]` counter and call the same `scale_upf()` function, which issues a `kubectl scale` command. Kubernetes ensures the resulting replica count is idempotent — if the proactive path has already scaled to 3 and the anomaly path then targets 3 or fewer, the kubectl command is a no-op at the cluster level. In the worst case both paths scale in the same 30-second cycle, which wastes one API call but does not over-provision beyond `SCALE_MAX = 5`. A future improvement would be a shared `_target_reps` lock to deduplicate within a single cycle.

---

## 2. 5G Core Architecture & Protocol

**Q: Why did you choose Open5GS over free5GC or OAI?**

A: Three criteria drove the decision. **Completeness:** Open5GS v2.7.2 implements all 14 3GPP SA NFs (AMF, SMF, UPF, NRF, UDM, UDR, AUSF, PCF, NSSF, BSF, SCP, WebUI) as separate processes, matching the full Release 16 service-based architecture. free5GC v3.3 was less mature at project start — several NFs were stubs, and the WebUI was less usable for subscriber provisioning. OAI (OpenAirInterface) is a C++ monolith focused primarily on the RAN (eNB/gNB), with the core (OAI-CN5G) a later addition; its build system (CMake with many external dependencies) was observed to be significantly harder to containerise than Open5GS's Meson-based build. **Community and documentation:** Open5GS has the largest active community and the most comprehensive Docker/Kubernetes deployment guides, which reduced research overhead. **Licensing:** Open5GS uses AGPLv3, free5GC uses Apache 2.0 — both are compatible with academic research; the AGPLv3 copyleft was not a concern since no commercial distribution was intended.

---

**Q: Walk through the NAS Registration procedure step by step.**

A: The 3GPP TS 24.501 Registration procedure, as observed in this project's UERANSIM ↔ Open5GS deployment:

1. **UE → gNB (RRC):** UE sends `RRC Setup Request` → `RRC Setup Complete` containing a NAS `Registration Request` (5GS Registration Type=Initial, Requested NSSAI=[SST=1], SUCI derived from IMSI using the null-scheme — no real HN public key in test PLMN MCC=999 MNC=70).

2. **gNB → AMF (NGAP/SCTP):** gNB encapsulates the NAS PDU in an NGAP `InitialUEMessage` over the SCTP association on port 38412 (N2 interface). UERANSIM's `nr-gnb` binary initiates the SCTP 4-way handshake (INIT → INIT_ACK → COOKIE_ECHO → COOKIE_ACK) before sending the first NGAP message.

3. **AMF → AUSF (SBI/HTTP2):** AMF calls `POST /nausf-auth/v1/ue-authentications` with the SUCI. AUSF resolves the SUCI to SUPI via UDM and initiates 5G-AKA.

4. **AUSF → UDM (SBI):** `POST /nudm-ueau/v1/{supi}/security-information/generate-auth-data` — UDM fetches the subscriber's secret key (K) and OPc from MongoDB via UDR, computes the 5G HE AV (RAND, AUTN, XRES*, Kausf), and returns it to AUSF.

5. **AUSF → AMF (SBI response):** AUSF returns the 5G Authentication Vector to AMF (without the XRES* itself — only HXRES* for AMF's use).

6. **AMF → UE (NAS/NGAP):** AMF sends `Authentication Request` (NAS) containing RAND and AUTN. UE verifies AUTN using its local K/OPc, computes RES*, derives session keys.

7. **UE → AMF:** `Authentication Response` containing RES*. AMF computes HRES* from RES* and compares to HXRES* received from AUSF — local verification.

8. **AMF → AUSF:** Confirms RES* for AUSF's remote verification against XRES*. AUSF confirms: authentication success.

9. **AMF → PCF (SBI):** `POST /npcf-am-policy-control/v1/policies` — PCF fetches the UE's Access and Mobility policy from UDR.

10. **AMF → UDM (SBI):** `PUT /nudm-uecm/v1/{supi}/registrations/amf-3gpp-access` — registers the AMF as the UE's serving AMF.

11. **AMF → UE (NAS/NGAP):** `Registration Accept` carrying the allocated 5G-GUTI (Globally Unique Temporary Identifier), Registration Area, Allowed NSSAI.

12. **UE → AMF:** `Registration Complete` acknowledging the new GUTI.

Total exchanges: 12 NAS + SBI messages. In the UERANSIM log, this sequence completes in approximately 180–300 ms on localhost, dominated by MongoDB query time for the subscriber AV lookup.

---

**Q: Explain the SCTP loopback bug — what caused it and how was it diagnosed at the packet level?**

A: This was documented in thesis Section 3.3.4. The bug: UERANSIM's `nr-gnb` binary successfully sent an SCTP INIT to Open5GS AMF on `127.0.0.1:38412`, received an INIT_ACK (confirming AMF was listening), then sent a COOKIE_ECHO — but the COOKIE_ECHO was never acknowledged, causing the SCTP association to time out after four retransmissions.

**Packet-level diagnosis:** Running `tcpdump -i lo0 sctp` on macOS captured the full exchange. The capture showed: INIT (from gNB), INIT_ACK (from AMF), COOKIE_ECHO (from gNB), then silence — no COOKIE_ACK from AMF. Three possibilities: (a) AMF was not processing the COOKIE_ECHO; (b) the kernel was dropping it before delivery to AMF's socket; (c) the usrsctp library was discarding it.

**Root cause:** macOS's Packet Filter (PF) firewall rules, which apply to loopback traffic under certain configurations, were silently dropping COOKIE_ECHO packets destined for port 38412. The standard `lo0` interface on macOS does not bypass PF the same way Linux loopback does. The `usrsctp` debug log (enabled with `usrsctp_sysctl_set_sctp_debug_on(SCTP_DEBUG_ALL)`) confirmed the packet was not being delivered to the SCTP stack.

**Fix:** Two-part. First, the NF addressing was reconfigured to use loopback aliases (e.g., AMF on `127.0.0.10:38412` instead of `127.0.0.1:38412`) via `sudo ifconfig lo0 alias 127.0.0.10`. Second, Open5GS was compiled with `--enable-usrsctp` to use the userspace SCTP implementation rather than relying on macOS kernel SCTP sockets, which further bypassed the PF interception path. After both fixes, `tcpdump` showed the complete 4-way SCTP handshake and the first NGAP message delivery.

---

**Q: What is the SBI interface and why does 5G SA core use HTTP/2?**

A: The Service-Based Interface (SBI) is the inter-NF communication protocol defined in 3GPP TS 29.500. Every 5G SA core NF exposes its capabilities as RESTful HTTP/2 services with JSON payloads, registering them with the NRF. A consuming NF queries the NRF for the endpoint of the service it needs (e.g., AMF needs AUSF's `nausf-auth` service) and then calls it directly.

HTTP/2 was chosen over HTTP/1.1 for three specific reasons relevant to core network traffic:
1. **Multiplexing:** A single TCP connection carries multiple concurrent NF-to-NF request streams. During UE registration, AMF simultaneously needs responses from AUSF, UDM, and PCF — HTTP/2 streams these concurrently without opening three TCP connections.
2. **Header compression (HPACK):** NF messages contain repetitive headers (Content-Type, Accept, Authorization). HPACK compression reduces per-message overhead by 40–60%, important for high-registration-rate scenarios.
3. **Server push / long-lived connections:** NRF can push NF status notifications to registered NFs without requiring polling.

In this project, the HTTP/2 prior-knowledge mode (`h2c` — HTTP/2 over plaintext without the HTTP/1.1 upgrade handshake) was used, which is why Kubernetes `httpGet` probes failed: they send HTTP/1.1, which Open5GS rejects with `"Received bad client magic byte string"` (nghttp2 error -903). All probes were changed to `tcpSocket` to work around this.

---

**Q: Explain how NSSF selects a network slice for a UE.**

A: During Registration, the UE includes its Requested NSSAI (Network Slice Selection Assistance Information) in the NAS Registration Request. Each S-NSSAI is a pair (SST: Slice/Service Type, SD: Slice Differentiator). In this project: SST=1 (eMBB), SST=2 (mMTC), SST=3 (URLLC).

The AMF receives the Registration Request and invokes the NSSF via the `Nnssf_NSSelection_Get` service (SBI HTTP/2). The NSSF consults its configuration (which maps each S-NSSAI to a Network Slice Instance — a specific set of AMF, SMF, UPF) and returns:
- **Allowed NSSAI:** the subset of the Requested NSSAI that this PLMN and AMF support
- **Network Slice Selection Information (NSSI):** including the serving AMF Set for each slice, and the NRF address to use for NF discovery within that slice

The AMF then uses the NSSI to select the correct SMF for PDU session establishment. In this project, each slice has a dedicated SMF+UPF pair (provisioned via separate subscriber profiles in MongoDB specifying `dnn: internet/iot/urllc`). The NSSF ensures UE1 (SST=1, eMBB) always lands on the eMBB SMF, and its traffic flows through the eMBB UPF — never sharing the data-plane instance with URLLC traffic (SST=3).

Validation: `kubectl logs -n open5gs deploy/nssf` shows `[NSSelection] Allowed NSSAI: [SST:1,SD:0x000001]` for eMBB UEs. Prometheus metric `open5gs_nssf_slice_selections_total{sst="1"}` increments on each selection.

---

## 3. Network Slicing

**Q: How does your implementation enforce per-slice QoS isolation?**

A: Each slice (eMBB SST=1, mMTC SST=2, URLLC SST=3) is assigned a dedicated SMF+UPF pair via Open5GS subscriber provisioning. The SMF enforces AMBR limits (e.g., eMBB: DL 100 Mbps / UL 50 Mbps) through the N4 PFCP interface to UPF. GBR bearers for URLLC use 5QI=1 (delay-critical GBR), while eMBB and mMTC use 5QI=9 (Non-GBR).

The NSSF selects the correct SMF per `Snssai` in the Registration Request, so traffic from UE1 (eMBB) never shares a data-plane UPF with UE3 (URLLC). Statistical validation (Scenario 4): ANOVA across the three slices yielded F=10.09, p<0.0001, confirming statistically significant QoS differentiation. URLLC latency p50=0.30 ms vs. eMBB p50=0.83 ms (Cohen's d=2.05) — a large effect size. SLA compliance is monitored by the Network Query API, which reads per-slice metrics from Prometheus.

---

## 4. Kubernetes & Orchestration

**Q: What Kubernetes mechanisms caused the 1.11 s pod recovery — be specific, not just "Kubernetes recovered it".**

A: The 1.11 s figure is the mean recovery time measured in Scenario 5 (pod-kill fault injection). The mechanisms in sequence:

1. **Pod deletion signal (t=0):** `kubectl delete pod upf-xxxx` sends `SIGTERM` to the UPF container. Open5GS UPF has no graceful shutdown logic for SIGTERM, so the process terminates immediately (0 ms grace period consumed).

2. **ReplicaSet controller (t≈20ms):** The ReplicaSet controller's reconciliation loop (watch on Pod objects via etcd) detects the replica count dropped below desired. It issues a Pod creation request to the API server within 20–50 ms.

3. **Scheduler (t≈50ms):** kube-scheduler picks the target node using standard priority and fit predicates (resource fit, taints/tolerations). With 3 worker nodes and low load, scheduling is near-instant.

4. **kubelet (t≈100ms):** The assigned node's kubelet receives the Pod spec, checks its local image cache (`5g-serving-api:latest` is already present from `kind load docker-image`), and starts the container without any pull latency.

5. **Container start + readiness probe (t≈800ms–1.1s):** Open5GS UPF starts, registers with NRF, binds the PFCP socket on UDP 8805, and creates the GTP-U kernel tunnel. The `tcpSocket` readiness probe on port 8805 succeeds once the socket is accepting connections.

6. **Service endpoint update (t≈1.1s):** kube-proxy updates iptables rules to include the new pod's IP in the UPF Service's endpoint list.

The 1.11 s is therefore dominated by the Open5GS UPF startup and NRF registration sequence (steps 4–6), not by Kubernetes scheduling. The Kubernetes control-plane path (steps 1–3) adds only ~100 ms. This is why the liveness probe `initialDelaySeconds` matters: probing too early during this window causes a restart loop.

---

**Q: What is HPA and how does it differ from VPA — when would you use each?**

A: **HPA (Horizontal Pod Autoscaler)** adds or removes Pod replicas based on observed metrics. The UPF HPA in this project triggers when average CPU utilisation across existing UPF pods exceeds 70%, adding one replica at a time up to `maxReplicas=5`. HPA uses the `autoscaling/v2` API with custom scale-up/scale-down stabilisation windows: `scaleUp.stabilizationWindowSeconds=30` (fast response to load), `scaleDown.stabilizationWindowSeconds=300` (conservative scale-in to avoid oscillation). Appropriate when the workload is **stateless and horizontally parallelisable** — multiple UPF replicas can each handle a subset of GTP-U flows independently.

**VPA (Vertical Pod Autoscaler)** adjusts the CPU and memory `requests` and `limits` of an existing pod. When VPA decides a change is needed, it terminates the pod and restarts it with the new resource profile. Applied to MongoDB in this project (`k8s/manifests/17-vpa-mongodb.yaml`): MongoDB is a **stateful singleton** — running two replicas would require a full MongoDB replica set configuration (oplog, election protocol), which was out of scope. VPA right-sizes the single MongoDB pod based on observed working set, preventing the OOM kills that occurred during peak stress testing when `limits.memory=256Mi` was insufficient for WiredTiger's buffer pool.

Rule of thumb: HPA for stateless compute (UPF, AMF in high-registration scenarios), VPA for stateful singletons (MongoDB, PCF).

---

**Q: Explain the MongoDB liveness probe issue — what caused it and how was it fixed?**

A: The issue was discovered during stress testing (Scenario 3, sustained 150 UE load) when Docker Desktop on the M1 host was force-quit due to memory pressure. MongoDB therefore experienced an unclean shutdown — no clean checkpoint was written.

**Root cause:** WiredTiger (MongoDB's storage engine) maintains a write-ahead journal. On restart after an unclean shutdown, WiredTiger must replay the journal to reconstruct the in-memory state before the process accepts connections. On the M1 MacBook running Docker Linux containers, this journal replay took approximately 47 seconds.

**The failure loop:** The original liveness probe had `initialDelaySeconds=30`, `timeoutSeconds=3`, `failureThreshold=3`. This meant the probe first fired at t=30 s, then at t=45 s, then at t=60 s. At t=39 s (after 3 failures: 30+3, 30+6, 30+9), Kubernetes killed the pod — *before* WiredTiger completed recovery at t=47 s. The restart triggered a second WiredTiger recovery cycle, which again was interrupted, creating a 3-cycle restart loop with 140 seconds total unavailability (measured from pod logs showing `WiredTiger message : [1712434200:000000][1:0x7f8b2a8f7700], connection: [conn1]` timestamp deltas).

**Fix:** `initialDelaySeconds` increased to **90 seconds** in `k8s/manifests/01-mongodb.yaml`. The readiness probe uses `tcpSocket` on port 27017 (more lenient than `exec mongosh --eval "db.adminCommand('ping')"`, which requires mongosh binary). This gives WiredTiger the full recovery window without triggering a premature kill.

---

**Q: Why kind for local Kubernetes instead of minikube or k3s?**

A: Three requirements drove the choice:

1. **Multi-node topology:** Testing PodDisruptionBudgets, inter-pod network policies, and HPA behaviour required at least 3 worker nodes so that pod scheduling decisions could be observed realistically. minikube is single-node by default (multi-node support was added later and is less stable); kind creates a true multi-node cluster (1 control-plane + 3 workers in this project) using Docker containers as nodes.

2. **Parity with CI/CD:** The `.github/workflows/ci.yml` pipeline creates an identical kind cluster. Running kind locally means the same cluster configuration runs in CI, catching networking bugs (like kindnet nfqueue enforcement) that minikube's different CNI would not exhibit.

3. **NetworkPolicy support:** kind ≥ 0.23 ships kindnet with nfqueue NetworkPolicy enforcement, which is required for the zero-trust network model. k3s uses Traefik and Flannel by default, which does not enforce NetworkPolicies without additional CNI (Calico) configuration. minikube requires `--cni=calico` to enable NetworkPolicy. kind's out-of-box NetworkPolicy enforcement was validated and confirmed functional in this project.

---

## 5. ML Pipeline & Models

**Q: Trace the full anomaly detection and scaling pipeline — from CPU spike to scaling action, every step, with approximate timings.**

A: Thesis Section 3.9.4 (closed-loop engine design) documents this. Using the 30-second poll cycle as the timing reference:

| t (s) | Component | Action |
|-------|-----------|--------|
| 0 | UPF pod | CPU spike occurs (e.g., flash crowd: 150 UEs attach simultaneously) |
| 0–15 | Prometheus | Waiting for next scrape; scrape interval = 15 s (monitoring namespace) |
| 15 | Prometheus | Scrapes `container_cpu_usage_seconds_total` from UPF cAdvisor exporter |
| 15 | Prometheus | `open5gs_upf_cpu_percent` gauge updated in TSDB |
| 30 | closed_loop.py | `run_once()` fires on 30-second poll; calls `get_current_metrics()` → PromQL `instant query` via HTTP |
| 30.3 | Prometheus API | Returns `cpu_upf_pct=87.5`, `upf_replicas=2`, `cpu_amf=35.0` |
| 30.3 | closed_loop.py | Calls `sagemaker_invoke(ANOMALY_ENDPOINT, {...})` via boto3 |
| 30.3–32.8 | SageMaker | `anomaly-detector-endpoint` (ml.t2.medium) runs IsolationForest inference; response ≈2–3 s round-trip (p99) |
| 32.8 | closed_loop.py | `anomaly_score=0.81 > 0.5849` → `is_anomaly=True` |
| 32.8 | closed_loop.py | `scale_upf(target_reps=3)` → `subprocess.run(["kubectl", "scale", "--replicas=3", ...])` |
| 32.9 | kubectl | API server receives scale request; Deployment `replicas` updated |
| 32.9 | ReplicaSet | Controller creates new UPF pod spec |
| 33–36 | kubelet | Container scheduled, image pulled from kind local cache, started |
| 36–47 | UPF | NRF registration, PFCP socket bind, GTP-U tunnel setup |
| 47 | Readiness probe | `tcpSocket:8805` passes; pod enters Running/Ready state |
| 47 | closed_loop.py | `event()` writes `DETECT: anomaly_score=0.81 → DECIDE: anomaly detected → ACT: UPF scaled to 3 replicas` |

**Total from CPU spike to new replica serving traffic: ≈47 seconds.** This beats the 120-second target. The dominant cost is not Kubernetes scheduling (~3 s) but UPF startup and NRF registration sequence (~15 s).

---

**Q: Your MAPE target of <3% was not met on the ensemble — explain this honestly.**

A: The project's original forecasting objective stated `MAPE < 15%`, not `< 3%`. The `3.64%` figure quoted in several places is the ARIMA(3,0,1) result on the *synthetic* training/validation data, not the operational target. Here is the honest picture:

| Model | Dataset | MAPE | Interpretation |
|-------|---------|------|---------------|
| ARIMA(3,0,1) | Synthetic (stationary, near-linear ramp) | 3.64% | Near-perfect — synthetic data matches ARIMA's stationarity assumption |
| ARIMA(3,0,1) | Real diurnal data (non-stationary, cyclic) | **184.99%** | Catastrophic failure — confirms ARIMA's non-stationarity limitation |
| SARIMA+Prophet ensemble | Real diurnal data | **12.93%** | Acceptable — ensemble is robust to the non-linearity ARIMA cannot handle |

The 3.64% result is misleadingly optimistic because the synthetic data had low variance and near-linear UE growth — conditions that trivially satisfy ARIMA's stationarity assumptions. When the same model is applied to real network traffic (diurnal cycle with morning rush, lunchtime peak, evening plateau), it degrades catastrophically.

The honest conclusion, stated explicitly in thesis Section 5.3.2 Limitation 1: "ML model evaluation on synthetic data can be misleadingly optimistic." The shift to the SARIMA+Prophet ensemble for the real diurnal evaluation, which achieved 12.93% (within the < 15% target), represents the more defensible benchmark. If I were to repeat the project, the initial training would use real diurnal traffic data from the start, and the 3.64% number would not appear in the headline results.

---

**Q: Your silhouette score didn't reach 0.70 but ARI was 0.997 — which result matters more and why?**

A: **ARI (Adjusted Rand Index = 0.997) matters more** for this use case, and here is why.

Silhouette score measures geometric cluster quality in the original feature space: it computes, for each point, the difference between its mean distance to points in the same cluster and its mean distance to points in the nearest other cluster, normalised to [-1, 1]. With 19 features, the curse of dimensionality means Euclidean distances become increasingly uninformative — all points tend to be equidistant in high-dimensional spaces. The PCA compression (to 5 components retaining 75.2% variance) mitigates this but does not eliminate it. A silhouette of 0.634 in a 5-dimensional PCA-compressed space is reasonable; the 0.70 target was aspirational, based on lower-dimensional datasets.

ARI measures **assignment stability**: how consistently does the clustering assign the same points to the same clusters across 100 bootstrap iterations? ARI=0.997 ±0.002 means across 100 random subsamples of the data, the cluster assignments are essentially identical — the k=2 solution (IDLE vs HIGH-LOAD) is genuinely recovering a real underlying structure in the data, not fitting noise. This is the operationally meaningful result: if the clusterer reliably labels the network as HIGH-LOAD when UPF CPU is above 70% and IDLE when it is below 40%, the silhouette value is irrelevant to the operator.

Both numbers are reported honestly in the thesis; neither is hidden. The silhouette limitation is acknowledged; the ARI result confirms the clustering is operationally valid.

---

**Q: Your IsolationForest reports a Recall of 93.3 ± 8.2%. How was this evaluated, and is the high variance a concern?**

A: Recall was measured by 5-fold stratified cross-validation on the labelled anomaly dataset (388 samples, 30 anomalies — contamination=0.15). The high variance (±8.2 pp) reflects class imbalance: with only 30 anomaly samples, each fold contains 4–6 anomaly instances. A single misclassified anomaly in fold 3 (1 of 5 missed) moves that fold's recall from 100% to 80%. The variance is an artefact of the small sample size, not model instability.

This is acknowledged as Limitation 1 in Chapter 5: the training set of 388 samples and 30 anomalies is insufficient for production-grade confidence intervals. With a production dataset of 10,000+ samples and 500+ labelled anomalies, CV variance would be substantially lower. The threshold τ=0.5849 was tuned on the held-out test set (20% split) independently of CV, so the operational decision boundary is not overfitted to any single fold.

---

**Q: What does SHAP tell you about the IsolationForest model, and how did you use that insight?**

A: The SHAP TreeExplainer identified `upf_replicas` (mean |SHAP| = 0.962) and `cpu_amf` (0.856) as the two dominant features, with `cpu_upf` third. This was counterintuitive — replica count being the top feature means the model learned that anomalies tend to occur when UPF is already scaled up but AMF CPU is also elevated, suggesting the anomaly is a traffic overload condition rather than a UPF-specific failure. This insight directly informed the decision to use all three features for the SageMaker endpoint rather than just `cpu_upf`.

---

**Q: How does the Network Query API work — trace a request from browser to Bedrock to response.**

A: Tracing `POST /ask` with question `"Why is UPF CPU high?"`:

1. **Flask receives request** (`automation/network_query_api.py:ask()`): parses JSON body, extracts `question` string.

2. **Metrics fetch:** `_get_metrics()` calls `_prom_reachable()`. If Prometheus is live (port 9090 accessible), it runs PromQL queries for `cpu_upf_pct`, `cpu_amf_pct`, `upf_replicas`, `ue_count`, `pod_restarts`. If not reachable (offline test mode), synthetic fallback values are used (`cpu_upf=12.4`, etc.).

3. **Health score computation:** `_fallback_health_score(metrics)` computes a weighted composite: `overall = upf_score*0.35 + amf_score*0.20 + stability*0.30 + capacity*0.15`. Grade assigned: A(≥90), B(≥75), C(≥60), D(≥40), F(<40).

4. **Bedrock invocation** (when `BEDROCK_ENABLED=true`): `bedrock_advisor.get_network_health_score(metrics, question)` constructs a prompt with the raw metrics JSON + the user question and calls `boto3.client("bedrock-runtime").invoke_model()` with model ID `anthropic.claude-sonnet-4-6`. If Sonnet is unavailable (quota pending), cascades to Haiku 4.5 → Nova Lite → Nova Micro. The Bedrock call takes 2–8 s at p99.

5. **Response assembly:** Flask returns `{"answer": bedrock_response, "metrics_used": metrics_dict, "model_used": model_id, "question": question, "timestamp": iso_timestamp}`.

6. **Offline fallback:** If Bedrock is disabled or the cascade exhausted, `answer` is filled by a rule-based heuristic that maps the question keywords to templated responses using the health score and component scores. This is what the tests validate — 30 tests cover all 6 endpoints with Prometheus monkeypatched offline and `BEDROCK_ENABLED=false`.

---

## 6. AWS Deployment & Cloud Architecture

**Q: Your thesis quotes a 7-day pilot cost of $32.36. Break down the main cost drivers.**

A: The dominant cost was EKS worker nodes: two `t3.medium` instances (2 vCPU, 4 GB) running for seven days at the us-east-1 on-demand rate of $0.0416/hr each ≈$13.91. SageMaker endpoint hosting for three BYOC endpoints in `ml.t2.medium` instances at $0.065/hr each ≈$10.92 (3 endpoints × 7 days × 24 hr × $0.065). Bedrock inference across 847 invocations via the cascade (predominantly Nova Lite at ~$0.0020/1K tokens output) ≈$3.20. AMP remote_write ingestion at $0.30/GB and storage at $0.03/metric/month for 2.66 GB ≈$2.90. S3 model artefact storage (<100 MB) and SNS notifications were negligible (< $0.50 total). The EKS cluster management fee ($0.10/hr for the control plane) added ≈$1.68. The 99.4% TCO reduction versus equivalent on-premises hardware assumes amortisation of a 3-node server rack (≈$8,200 hardware + $1,500/yr power + space) over five years at a Zimbabwean university.

---

**Q: Explain IRSA — why is it more secure than storing AWS credentials in environment variables?**

A: IRSA (IAM Roles for Service Accounts) replaces static AWS credentials (Access Key ID + Secret Access Key) with ephemeral, automatically-rotated credentials scoped to a specific Kubernetes ServiceAccount.

**The insecure alternative:** Storing `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in a Kubernetes Secret (mounted as env vars) means: (a) the credentials are static — they never rotate until manually cycled; (b) any process inside the pod can read them from `/proc/self/environ`; (c) if the Secret is accidentally logged, exported in a debug dump, or pushed to Git, credentials are permanently compromised.

**How IRSA works:** The EKS cluster has an OIDC identity provider endpoint (e.g., `oidc.eks.us-east-1.amazonaws.com/id/EXAMPLEID`). Each NF's Kubernetes ServiceAccount is annotated with `eks.amazonaws.com/role-arn: arn:aws:iam::749534910877:role/5g-core-closed-loop-sa-role`. At pod startup, the kubelet mounts a projected ServiceAccount token (a signed JWT with audience `sts.amazonaws.com`) into the pod at `/var/run/secrets/eks.amazonaws.com/serviceaccount/token`. boto3 automatically calls `sts:AssumeRoleWithWebIdentity` with this JWT, receiving temporary credentials (valid 1 hour, auto-refreshed by the AWS SDK). These credentials are never stored on disk or in environment variables — they exist only in the SDK's in-memory credential cache.

The security gain: compromise of a single pod does not yield reusable static credentials. The temporary creds expire within 1 hour, and the IAM role policy (e.g., `sagemaker:InvokeEndpoint` on specific endpoint ARNs only) follows least-privilege. No credential rotation procedure is required.

---

**Q: Why BYOC for SageMaker instead of the managed sklearn container?**

A: AWS's managed SageMaker scikit-learn container (`sagemaker-scikit-learn:1.2-1-cpu-py3`) supports scikit-learn ≤ 1.2.x. The ML models in this project were trained with scikit-learn 1.8.0, which introduced a change to the internal tree node representation: the `missing_go_to_left` attribute was added to decision tree node dtype in version 1.3. When a model trained with sklearn 1.8.0 is unpickled by sklearn 1.2, it raises `ValueError: Cannot construct DataObject from pickle data` because the node array dtype definition has changed and the unpickling fails at the C extension level.

The fix was to build a custom BYOC (Bring Your Own Container) image (`sagemaker/byoc/Dockerfile`) using `python:3.11-slim` as the base, installing `scikit-learn==1.8.0`, `statsmodels`, and `flask`, then implementing the SageMaker BYOC interface: an HTTP server on port 8080 with `GET /ping` (health check) and `POST /invocations` (inference). The image was built with `--provenance=false` (`docker buildx build --platform linux/amd64 --provenance=false`) because SageMaker rejects OCI image index manifests (Docker v2.2 manifest format is required), and `buildx` with provenance produces an OCI index by default.

---

**Q: What is your honest assessment of the Bedrock integration — did it fully work?**

A: Partially, and the thesis is explicit about this (Section 4.12 and Limitation 6). What worked: the 4-tier cascade architecture, the IRSA authentication, the JSON response parsing, and the health score computation. What did not work as intended: **Claude Sonnet 4.6 and Haiku 4.5 were both unavailable during the deployment window.** Amazon Bedrock Claude models require a manual use-case form submission and human approval before first invocations are allowed. The approval was pending at the time of the 7-day deployment window, so the cascade fell to Tier 3 (Nova Lite) for all 847 invocations.

The health score of 77/100 (Grade B) was correctly computed by Nova Lite from the provided Prometheus metrics. The cascade pattern worked as designed. But the LLM root-cause analysis quality from Nova Lite is observably lower than what Claude Sonnet 4.6 would provide — Nova Lite returns shorter, less specific explanations that require more operator interpretation. The thesis reports this as: *"Full generative analysis with Claude Sonnet 4.6 was pending quota reset at time of writing."* A future replication with Claude access would provide a meaningful quality comparison.

The honest assessment: the *architecture* of the Bedrock integration is sound and the code is production-ready, but the *results* reported in Chapter 4 represent Nova Lite performance, not Claude performance. This is a significant caveat for any inference drawn about LLM quality in this context.

---

## 7. Security

**Q: Explain your NetworkPolicy model — what is zero-trust and how was it implemented?**

A: Zero-trust network security rejects the assumption that traffic inside a network boundary is safe. In the traditional perimeter model, once a packet is inside the corporate network it can reach any service. In zero-trust, every connection requires explicit authorisation regardless of source.

Implementation in this project uses three concentric layers (`docs/security.md`):

**Layer 1 — Default Deny All:** A single NetworkPolicy with `podSelector: {}` (matches all pods) and `policyTypes: [Ingress, Egress]` with no rules effectively drops all traffic cluster-wide. This is applied first.

**Layer 2 — Explicit Allow Matrix:** 18 additional NetworkPolicy objects add back exactly the flows required by the 3GPP communication matrix (e.g., `gNB→AMF: 38412/SCTP`, `AMF→AUSF: 80/TCP`, `SMF→UPF: 8805/UDP`). Any flow not listed is blocked. The most critical restriction: MongoDB (port 27017) can only be reached from UDR — not from AMF, SMF, or any ML pod. This limits the blast radius of a compromised AMF: even if an attacker gains code execution inside the AMF pod, they cannot reach subscriber credentials in MongoDB.

**Enforcement:** kindnet ≥ 0.23 uses nfqueue (Netfilter queue 101). All pod-to-pod traffic is queued through a userspace daemon that evaluates NetworkPolicy objects before accept/drop decisions. Confirmed working: deploying the `closed-loop-engine` pod without adding `allow-closed-loop-egress` NetworkPolicy caused it to fail to reach Prometheus (connection timeout), correctly blocked by the default-deny policy. Adding the explicit allow rule restored connectivity.

**Layer 3 — RBAC + ServiceAccounts:** Each NF has its own ServiceAccount with minimum required RBAC permissions (e.g., the closed-loop engine has `get/list` on Deployments but not on Secrets). AWS permissions are further restricted through IRSA.

---

**Q: What is the actual status of Priority 7 (mTLS)?**

A: Partial implementation — the crypto infrastructure is complete, cluster-wide enforcement is not.

**What was completed:** A CA keypair was generated using OpenSSL (`openssl req -x509 -newkey rsa:4096 -days 365`). Per-NF certificates were issued for AMF, SMF, and NRF. Open5GS NRF was configured with TLS in `k8s/manifests/19-nrf-tls-test.yaml`. A loopback TLS handshake test confirmed: `curl -sk --http2-prior-knowledge https://127.0.0.1:8443/nnrf-nfm/v1/nf-instances` returned HTTP 200 JSON from NRF with TLSv1.3 negotiated and ALPN `h2` (HTTP/2 over TLS).

**What was not completed:** Cross-pod TLS failed the first time because the AMF's egress NetworkPolicy only permitted port 80 (HTTP) to NRF, not port 8443 (HTTPS). Updating the NetworkPolicy to permit 8443 was not completed within the priority window. Additionally, enabling TLS for all 14 NFs would require: (a) generating 14 keypairs, (b) distributing them as Kubernetes Secrets, (c) updating all NF YAML configs with the correct `default.tls` block nesting (confirmed by reading `lib/sbi/context.c:227-233` — the `default:` block must be a child of the NF key, not at the YAML root), and (d) updating all NetworkPolicies to allow 8443. This full rollout was estimated at 3–4 days of work, which was not available before submission.

**Recommended production path:** Istio ambient mode (sidecar-free mTLS). In ambient mode, the ztunnel proxy handles TLS for all pods transparently without NF configuration changes, which eliminates the per-NF certificate distribution problem entirely.

---

## 8. Stress Testing & Statistical Validity

**Q: How did you ensure stress test results are statistically valid given small sample sizes?**

A: The total dataset was n=75 observations across 6 scenarios. Three statistical techniques were applied:

1. **ANOVA (one-way):** Comparing latency distributions across the three slice types in Scenario 4. F=10.09, p<0.0001. At α=0.001, this is highly significant. The F-statistic of 10.09 greatly exceeds the critical value F(2,72)=5.18, providing strong evidence that slice QoS differentiation is real and not due to sampling variability.

2. **Cohen's d (effect size):** For the URLLC vs. eMBB latency comparison, Cohen's d=2.05 indicates a *very large* effect size (d>0.8 is large by convention). This means the mean difference between slices is 2 standard deviations — the distributions overlap minimally. Large effect sizes are robust to small samples because they are less sensitive to sampling error.

3. **Bootstrap ARI (clustering stability):** 100 bootstrap resamples of the k-Means training data were run, each producing an ARI against the original assignment. ARI=0.997±0.002 across all 100 iterations confirms that the k=2 clustering is highly stable even with limited data.

The thesis explicitly acknowledges (Limitation 1) that n=388 ML training samples and n=75 stress test observations are small relative to production datasets. Performance claims are framed as proof-of-concept rather than production-validated. A production study would require 6–12 months of real network data.

---

## 9. Comparison with Real Operators

**Q: How does this compare to a real operator's core network — for example, Econet Zimbabwe?**

A: Econet Zimbabwe operates a commercial 4G EPC (Evolved Packet Core) with Huawei-supplied hardware (MME, S-GW, P-GW, HSS). Their 5G deployment is 5G NSA (Non-Standalone): 5G NR radio with 4G EPC core — the "SA" in this project (3GPP Release 16 5G Standalone) uses a fundamentally different architecture. Key contrasts:

| Dimension | This Project | Econet Zimbabwe (estimated) |
|-----------|-------------|------------------------|
| Core architecture | 5G SA (3GPP Rel. 16, service-based) | 4G EPC + 5G NSA |
| Hardware | Commodity cloud (AWS t3.medium) | Huawei proprietary COTS servers |
| NF implementation | Open5GS v2.7.2 (open-source) | Huawei commercial software (closed) |
| Subscriber scale | 3 simulated UEs | ~14 million subscribers |
| Radio spectrum | UERANSIM simulation (no spectrum) | Licensed spectrum (LTE 900/1800/2600 MHz) |
| Geographic coverage | Single local cluster | 3,000+ base stations nationwide |
| NOC operations | Fully automated (closed-loop ML) | Manual NOC + Huawei EMS |
| Capital cost | $32.36 / 7 days | Estimated $200–500M total infrastructure |
| Slice QoS enforcement | Demonstrated (ANOVA p<0.0001) | Not available in NSA mode (EPC has no native slicing) |
| AI/ML operations | Production (closed-loop + Bedrock) | Limited proprietary analytics only |

**What this project *cannot* claim:** performance under real GTP-U packet loads at Econet scale, handover between physical base stations, licensed spectrum interference management, or roaming interoperability.

**What this project *can* claim:** the architecture, NF interaction patterns, SBI protocols, HPA behaviour, and ML pipeline are production-representative. The cost figures ($32.36 for 7 days) are from a real AWS bill, not a simulation. An operator migrating from EPC to a cloud-native 5G SA core would follow the same Kubernetes + Prometheus + SageMaker pattern demonstrated here. This is precisely the evidence gap that motivates the research (Section 1.3).

---

## 10. General / Reflection

**Q: What would you do differently if starting from scratch?**

A: Five things, in priority order:

1. **Start with real diurnal traffic data** for ML training, not synthetic data. The ARIMA MAPE degradation from 3.64% (synthetic) to 184.99% (real diurnal) was the project's most significant technical surprise, and it would have been caught earlier with real data from the beginning.

2. **Apply for Bedrock Claude access at project start**, not during the deployment window. The 7-day pilot was constrained to Nova Lite because Claude quota was pending; starting the approval process 4–6 weeks earlier would have allowed the full cascade to be validated.

3. **Use a service mesh (Istio ambient) from the beginning** for mTLS, rather than attempting per-NF TLS configuration. Priority 7 (mTLS) consumed 4 days of effort for partial results. Istio ambient would have delivered cluster-wide mTLS transparently in one Helm install.

4. **Implement the UERANSIM multi-UE load generator using PCAP replay** rather than scripted ramps, for more realistic traffic patterns with true session interleaving.

5. **Add a formal SLA breach detection event** (latency p99 > threshold) that triggers the SNS alert + Bedrock root-cause path. The infrastructure is all wired — the breach detection logic itself was not written within the project timeline.

---

## 11. Technical Deep-Dives

One dense paragraph per major component, covering the "why" behind every significant technical choice.

**5G Core (Open5GS):** Open5GS v2.7.2 implements the 3GPP Release 16 5G SA core as 14 separate Unix processes communicating over the SBI (HTTP/2 JSON) and user-plane (GTP-U UDP 2152, PFCP UDP 8805, NGAP SCTP 38412) interfaces. Each NF registers with the NRF at startup (`POST /nnrf-nfm/v1/nf-instances`), heartbeating every 10 seconds, and discovers other NFs by querying the NRF rather than using static IP configuration — this is the "service-based" in SBA. On macOS M1, the build required 12 dependency resolutions not documented upstream (usrsctp for SCTP sockets, libmicrohttpd for the NRF HTTP server, libnghttp2 for HTTP/2, libyaml, libidn2, gnutls, gcrypt, mongoc, bson) and a Homebrew Meson toolchain. ARM64-to-AMD64 cross-compilation (for AWS ECR images) required three-stage Docker builds with `--platform=linux/amd64` flags. The UPF requires Linux kernel GTP module (`gtp.ko`) unavailable on macOS, so GTP-U validation was performed inside Docker Linux containers — the same environment used in production EKS.

**Kubernetes Layer:** The cluster is a 4-node kind setup (1 control-plane + 3 workers) using Docker-in-Docker. Kubernetes provides five mechanisms exploited in this project: (a) HPA scales UPF replicas 1→5 based on CPU utilisation, with separate scale-up (30 s stabilisation) and scale-down (300 s stabilisation) windows to prevent oscillation; (b) VPA right-sizes MongoDB's memory limits based on observed working set without requiring manual tuning; (c) PodDisruptionBudgets (`minAvailable: 1`) on all 12 NFs prevent simultaneous eviction during node drain; (d) Startup probes (30-iteration × 10 s = 300 s budget) prevent liveness from killing slow-starting NFs like AMF during NRF registration; (e) NetworkPolicies (kindnet nfqueue enforcement) implement the full zero-trust 18-rule communication matrix, with MongoDB accessible only from UDR. The MongoDB liveness probe configuration (`initialDelaySeconds=90`) was specifically calibrated to the 47-second WiredTiger journal recovery time observed under stress-test conditions.

**ML Pipeline:** Three models are trained on 388 samples (30 anomalies) from 4 days of cluster telemetry. IsolationForest (`n_estimators=300`, `contamination=0.15`) answers "is this moment anomalous?" — threshold τ=0.5849 was derived by optimising F1 on a 20% held-out test set. SHAP TreeExplainer revealed that `upf_replicas` (importance 0.962) dominates anomaly prediction, meaning the model learned a correlated overload signature (UPF scaled up AND AMF CPU elevated) rather than a simple CPU threshold. ARIMA(3,0,1) was identified by `pmdarima.auto_arima` (AIC=−63.65) and achieves 3.64% MAPE on synthetic stationary data; on real diurnal data it degrades to 184.99% MAPE — confirming ARIMA's stationarity limitation. The SARIMA+Prophet ensemble achieves 12.93% on real data. k-Means (k=2, n_init=50) operates in a PCA(5)-compressed space retaining 75.2% of 19-feature variance; ARI=0.997±0.002 across 100 bootstraps confirms the IDLE/HIGH-LOAD distinction is real and stable, despite silhouette=0.634 falling short of the 0.70 aspirational target due to high-dimensional distance metric limitations.

**AWS Deployment:** The Terraform configuration provisions ≈45 AWS resources in us-east-1: VPC (10.0.0.0/16, 2 public + 2 private subnets across 2 AZs, 2 NAT gateways), EKS 1.29 cluster with a managed node group (2×t3.medium), 15 ECR repositories with lifecycle policies, 3 SageMaker real-time endpoints using custom BYOC containers (sklearn 1.8.0, Flask on port 8080), Amazon Managed Prometheus workspace (remote_write target for in-cluster Prometheus), Amazon Managed Grafana (7 dashboards, SSO), S3 bucket (model artefacts), SNS topic (alert delivery), and IAM IRSA roles (no static credentials anywhere). The BYOC requirement arose because AWS's managed sklearn container only supports sklearn ≤1.2, while models were trained with 1.8.0 (tree node dtype incompatibility). The SageMaker BYOC container was built with `--provenance=false` to produce a Docker v2.2 manifest (SageMaker rejects OCI image index format). Total 7-day pilot cost: $32.36 from the real AWS invoice.

**Bedrock Integration:** The `bedrock_advisor.py` module implements a 4-tier Claude model cascade (Sonnet 4.6 → Haiku 4.5 → Nova Lite → Nova Micro) with IRSA authentication (no static AWS credentials) and exponential backoff retry. The cascade was designed specifically because Claude model access requires a use-case form approval that can take days; Nova models do not require approval. The closed-loop engine calls `bedrock_advisor.analyse_network_event()` when `anomaly_score > ANOMALY_THRESH=0.6` and `generate_capacity_forecast()` when SageMaker predicts `forecast_max > FORECAST_THRESH=150`. During the 7-day pilot, all 847 Bedrock invocations fell to Tier 3 (Nova Lite) because Claude quota was pending approval. The cascade pattern worked correctly — the fallback mechanism was confirmed — but Nova Lite response quality is observably lower than Claude. The health score computation (77/100, Grade B, during stress testing) was correctly calculated by Nova Lite using the provided Prometheus metrics JSON.

---

## 12. Design Decision Log

| Decision | Alternatives Considered | Why Chosen | Trade-off |
|----------|------------------------|------------|-----------|
| Open5GS v2.7.2 | free5GC v3.3, OAI-CN5G | Most complete NF set, active community, Docker examples available | AGPLv3 copyleft (vs Apache 2.0 free5GC); C codebase harder to extend than free5GC Go |
| kind (multi-node) | minikube, k3s, kubeadm | Multi-node cluster (3 workers) needed for PDB testing; CI/CD parity; out-of-box NetworkPolicy via kindnet nfqueue | Docker-in-Docker overhead; not production-grade (no persistent storage volumes by default) |
| ARIMA(3,0,1) as local model | Prophet, LSTM, moving average | Lightweight (<1 MB pkl), interpretable, no GPU needed, stationary synthetic data | Catastrophic failure on real diurnal data (MAPE 184.99%); should have been replaced by ensemble earlier |
| SARIMA+Prophet ensemble for SageMaker | ARIMA only, LSTM only | More robust to non-stationarity; MAPE 12.93% vs ARIMA 184.99% on real data | Higher inference latency (~3 s vs ~1.5 s ARIMA); more complex maintenance |
| IsolationForest (300 trees, contamination=0.15) | DBSCAN, One-Class SVM, Autoencoder | No need for labelled anomaly data during training; handles high-dimensional mixed-scale features; scales to production volume | Contamination parameter must be pre-specified (domain knowledge required); DBSCAN found 0 anomalies on this dataset |
| k-Means (k=2) | k=6, DBSCAN, GMM | ARI=0.997 confirms k=2 is stable; interpretable IDLE/HIGH-LOAD states map directly to operator decisions | k=2 ignores sub-states within HIGH-LOAD; k=6 SageMaker endpoint has richer state labels but less interpretable |
| SageMaker BYOC | Managed sklearn container, ECS, Lambda | Required sklearn 1.8.0; managed container limited to ≤1.2 | Docker build complexity; must maintain custom container image; --provenance=false required for Docker v2.2 manifest |
| Bedrock 4-tier cascade (Sonnet→Haiku→Nova Lite→Micro) | Single model, OpenAI API | Claude unavailability would break system; cascade ensures availability without static fallback code | Increased code complexity; different quality responses per tier; cannot guarantee response consistency |
| IRSA (no static credentials) | Kubernetes Secret with AWS keys, EC2 instance role | Least-privilege per pod; auto-rotating; no credential in env/disk; recommended by AWS Well-Architected | OIDC configuration complexity; requires EKS-specific setup (not portable to bare-metal k8s) |
| tcpSocket probes (not httpGet) | httpGet, exec (mongosh/curl) | Open5GS SBI uses HTTP/2 prior-knowledge; httpGet sends HTTP/1.1 rejected with nghttp2 error -903 | TCP check only confirms port is listening, not that the service is functionally healthy |
| MongoDB initialDelaySeconds=90 | 30 (original), 60 | WiredTiger journal recovery under stress takes 47 s; 90 s provides 43 s safety margin | Slower detection of genuine MongoDB deadlocks (90 s delay before any probe fires) |
| kindnet nfqueue NetworkPolicy | Calico, Cilium, Flannel | Bundled with kind; zero additional CNI configuration; confirmed enforcing nfqueue policies from v0.23+ | Userspace nfqueue is slower than eBPF (Cilium); not suitable for production high-throughput |
| PCA(5) for k-Means | PCA(3), PCA(10), raw 19D | 75.2% variance retention; trade-off between compression and information loss; silhouette maximised at k=5 components | Reduces interpretability (PCA components are not directly named features); silhouette 0.634 short of 0.70 target |
| Prometheus 15 s scrape interval | 30 s (original), 5 s | Balances metric freshness (needed for 30 s anomaly detection) and storage (1.9M samples/day at 15 s × 22 targets) | Cannot detect sub-15 s transient anomalies; AMP storage cost scales with sample count |
| Synthetic 7-day data for initial ML training | Real diurnal data only, mixed | Allowed controlled anomaly injection for labelling; sufficient for proof-of-concept | Misleadingly low MAPE on synthetic (3.64%); failure on real data (184.99%) was not detected until Priority 2 |

---

## 13. Demo Run-Through Checklist

A structured 10-minute viva demonstration. Practice this until the transitions take <15 seconds each.

### Pre-viva (5 minutes before)

- [ ] `kind get clusters` → confirms `5g-core` is running
- [ ] `kubectl get pods -n open5gs` → all 14+ pods `Running`
- [ ] `kubectl get pods -n monitoring` → Prometheus, Grafana pods `Running`
- [ ] `kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &`
- [ ] `kubectl port-forward -n open5gs svc/network-query-api 5000:5000 &`
- [ ] Open browser tabs: Grafana (`localhost:3000`), terminal
- [ ] Have `curl` commands in a scratch file ready to paste

---

### Minute 0–1 · Cluster overview (15 seconds)

```bash
kubectl get pods -n open5gs
```
**Say:** "14 Network Functions running — AMF, SMF, UPF, NRF, UDM, UDR, AUSF, PCF, NSSF, BSF, SCP, WebUI, UERANSIM gNB and UE. All 3GPP Release 16 NFs."

---

### Minute 1–2 · Live 5G registration proof (45 seconds)

```bash
kubectl logs -n open5gs -l app=amf --tail=10
```
**Say:** "These are live AMF logs showing the NAS Registration Accept messages. Each line is a UE receiving its 5G-GUTI — its temporary identity on the network."

```bash
curl -s http://localhost:5000/status | python3 -m json.tool
```
**Say:** "The Network Query API reports health score 94.2, Grade A. This is computed from Prometheus metrics in real time: UPF component score, AMF component score, stability, and capacity."

---

### Minute 2–3 · Network slicing (60 seconds)

```bash
curl -s http://localhost:5000/slices | python3 -m json.tool
```
**Say:** "Three independent slices: eMBB SST=1 for broadband, mMTC SST=2 for IoT, URLLC SST=3 for ultra-low latency. Each has its own SMF+UPF pair. NSSF selected these from the UE's Requested NSSAI. All SLAs met — latency p99 under 1.4 ms for all three."

Show `docs/figures/network_slicing.png`.

---

### Minute 3–4 · ML models live (60 seconds)

```bash
curl -s -X POST http://localhost:30800/predict/anomaly \
  -H "Content-Type: application/json" \
  -d '{"cpu_upf": 87.5, "upf_replicas": 4, "cpu_amf": 35.0}'
```
**Say:** "Anomaly score 0.81 exceeds threshold 0.5849 — is_anomaly true. In the live closed-loop engine, this would trigger `scale_upf(5)`."

```bash
curl -s -X POST http://localhost:30800/predict/forecast \
  -H "Content-Type: application/json" \
  -d '{"sessions": [1.0, 1.5, 2.3, 3.1, 3.8, 4.2]}'
```
**Say:** "Six-step 30-minute ARIMA forecast. If max forecast exceeds 100, the proactive pre-scale fires — before CPU spikes, not after."

---

### Minute 4–5 · Closed-loop engine (45 seconds)

Open `automation/closed_loop.py` at `run_once()`, show the DETECT→DECIDE→ACT structure.

**Say:** "Every 30 seconds: collect metrics from Prometheus, invoke SageMaker anomaly endpoint, run local ARIMA pre-scale check, invoke SageMaker traffic forecaster, classify network state, check if Bedrock analysis is needed. All in one poll cycle."

```bash
tail -20 /logs/closed_loop.log 2>/dev/null || echo "Log at /tmp/test_closed_loop.log in dry-run mode"
```

---

### Minute 5–6 · Grafana dashboard (45 seconds)

Switch to browser → Grafana → `5G Core Overview` dashboard.

**Say:** "22 Prometheus scrape targets, 15-second interval. UPF CPU here, HPA replica count here. This is what the closed-loop engine reads every 30 seconds. The AIOps panel in dashboard 5 shows the Bedrock health analysis output."

---

### Minute 6–7 · Natural language query / Bedrock (45 seconds)

```bash
curl -s -X POST http://localhost:5000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Should I scale the UPF now?"}' | python3 -m json.tool
```
**Say:** "Natural language interface. The Network Query API fetches current metrics, constructs a prompt with the health scores, and sends it to Bedrock. In the 7-day pilot this used Nova Lite — Claude Sonnet quota was pending. The cascade pattern means the system remains operational even when higher-tier models are unavailable."

---

### Minute 7–8 · HPA autoscaling demo (60 seconds)

```bash
kubectl get hpa -n open5gs
```
**Say:** "HPA configured for UPF: target 70% CPU, scale 1 to 5 replicas, 30 s scale-up stabilisation. In Scenario 1 (diurnal ramp to 200 UEs), HPA triggered in 25 seconds and went from 1 to 5 replicas in a single stabilisation window."

```bash
kubectl describe hpa upf-hpa -n open5gs | grep -E "Min|Max|Current|Events" | head -8
```

---

### Minute 8–9 · AWS architecture (30 seconds)

Show `docs/figures/aws_deployment.png`.

**Say:** "Same Kubernetes manifests, same Docker images — deployed to EKS. SageMaker BYOC endpoints serving these three models. IRSA instead of static credentials. Total 7-day cost: $32.36. 99.4% TCO reduction versus equivalent on-premises rack. Break-even at 70 subscribers."

---

### Minute 9–10 · Security & testing (30 seconds)

```bash
kubectl get networkpolicies -n open5gs | head -10
```
**Say:** "18 NetworkPolicies implementing zero-trust. Default deny all, then explicit allow for each 3GPP interface. MongoDB reachable only from UDR — even a compromised AMF cannot reach subscriber credentials."

```bash
cd /path/to/project && python3 -m pytest tests/ --tb=no -q 2>&1 | tail -5
```
**Say:** "64 automated tests. All offline — no AWS, no Prometheus required. Run in CI on every push."

---

### Closing (buffer 30 seconds)

**Have ready to say:**
- "The thesis is Chapter 5 — conclusions answer all 5 research questions with data from the live system."
- "The 37,623-word dissertation and all code are in the repository. Happy to walk through any section in depth."

---

*Last updated: 2026-06-16*
