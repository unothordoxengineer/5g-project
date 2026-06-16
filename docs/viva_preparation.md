# Viva Preparation — Cloud-Native 5G SA Core FYP

## Overview

This document collects anticipated viva questions with structured answers drawn directly from the thesis and implementation artefacts.

---

## 1. Predictive Pre-Scaling (ARIMA)

**Q: Your closed-loop engine does both reactive anomaly detection and proactive pre-scaling. What is the architectural difference, and why do you need both?**

A: The reactive path (step 2) is driven by SageMaker's IsolationForest anomaly-detector endpoint: once CPU or session load already crosses the anomaly threshold (score > 0.6), it scales UPF up by one replica. This catches unexpected spikes but always reacts *after* the degradation has started.

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

## 2. Network Slicing

**Q: How does your implementation enforce per-slice QoS isolation?**

A: Each slice (eMBB SST=1, mMTC SST=2, URLLC SST=3) is assigned a dedicated SMF+UPF pair via Open5GS subscriber provisioning. The SMF enforces AMBR limits (e.g., eMBB: DL 100 Mbps / UL 50 Mbps) through the N4 interface to UPF. GBR bearers for URLLC use 5QI=1 (delay-critical), while eMBB and mMTC use 5QI=9 (Non-GBR). The NSSF selects the correct SMF per `Snssai` in the Registration request, so traffic from UE1 (eMBB) never shares a data-plane UPF with UE3 (URLLC). SLA compliance is monitored by the Network Query API, which reads per-slice metrics from Prometheus.

---

## 3. Machine Learning Pipeline

**Q: Your IsolationForest reports a Recall of 93.3 ± 8.2%. How was this evaluated, and is the high variance a concern?**

A: Recall was measured by 5-fold stratified cross-validation on the labelled anomaly dataset. The high variance (±8.2 pp) reflects class imbalance: the anomaly class is only 15% of samples (`contamination=0.15`), so folds with few anomaly examples produce noisy estimates. This is not operationally concerning because the threshold (0.5849) was tuned on the held-out test set to balance Precision and Recall at the specific operating point needed by the closed-loop engine. In production the model uses the full training set, which reduces variance further.

---

**Q: What does SHAP tell you about the IsolationForest model, and how did you use that insight?**

A: The SHAP TreeExplainer identified `upf_replicas` (mean |SHAP| = 0.962) and `cpu_amf` (0.856) as the two dominant features, with `cpu_upf` third. This was counterintuitive — replica count being the top feature means the model learned that anomalies tend to occur when UPF is already scaled up but AMF CPU is also elevated, suggesting the anomaly is a traffic overload condition rather than a UPF-specific failure. This insight directly informed the decision to use all three features for the SageMaker endpoint rather than just `cpu_upf`.

---

## 4. AWS Deployment and Cost

**Q: Your thesis quotes a 7-day pilot cost of $32.36. Break down the main cost drivers.**

A: The dominant cost was EKS worker nodes: two `t3.medium` instances running for seven days (≈$12.67). SageMaker endpoint hosting for three BYOC endpoints in `ml.t2.medium` instances accounted for ≈$11.90. Bedrock inference was low due to the cascade fallback (Sonnet → Haiku → Nova Lite → Nova Micro), totalling ≈$3.20 across 847 invocations. AMP remote_write ingestion and storage added ≈$2.90. S3 model artefact storage and SNS notifications were negligible (< $0.50). The 99.4% TCO reduction versus equivalent on-prem hardware assumes amortisation of a 3-node server rack over five years at a Zimbabwean university.

---

## 5. General

**Q: What would you do differently if you had another semester?**

A: Three things. First, extend the ARIMA model to a multivariate ARIMAX or VAR model that includes `cpu_amf` and `pod_restarts` as exogenous inputs, which would improve forecast accuracy during state-transition events. Second, implement true traffic replay using PCAP-based UERANSIM scripts to generate more realistic UE session patterns rather than scripted ramps. Third, add a formal SLA-breach event that triggers an SNS alert with Bedrock root-cause analysis — the infrastructure is already wired (SNS topic and Bedrock advisor exist) but the breach detection logic was not completed within the project timeline.

---

*Last updated: 2026-06-16*
