# Local Demo Script — Cloud-Native 5G SA Core
## Lecturer Progress Demonstration · HIT FYP · Nigel Kadzinga

**Duration:** ~20 minutes  
**Environment:** Local kind cluster (no AWS — all figures are from the real deployment)  
**Pre-demo:** Run `bash scripts/local_preflight.sh` and resolve any FAILs before the lecturer arrives.

---

## Port-Forwards (open these terminal tabs first)

```bash
# Tab A — Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

# Tab B — WebUI
kubectl port-forward -n open5gs svc/webui 9999:9999 &

# Tab C — Network Query API
kubectl port-forward -n open5gs svc/network-query-api 8080:8080 &
```

Browser tabs to open in advance:
- `http://localhost:3000` — Grafana (login: **admin / prom-operator**)
- `http://localhost:9999` — Open5GS WebUI (login: **admin / 1423**)

---

## Step-by-Step Checklist

---

### Step 1 · Cluster Status Overview
**Target time: 2 min**

- [ ] Run:
  ```bash
  kubectl get pods -n open5gs
  ```
- [ ] Point out: 14+ pods — one per 3GPP NF (AMF, SMF, UPF, NRF, UDM, UDR, AUSF, PCF, NSSF, BSF, SCP) plus gNB, UE, WebUI, MongoDB.
- [ ] Run:
  ```bash
  kubectl get nodes
  ```
- [ ] Point out: 1 control-plane + 2 worker nodes — this is a real multi-node Kubernetes cluster, not a single-VM emulator.

**Talking point:**
> "Each pod is an independent 3GPP Network Function communicating over the Service-Based Interface — HTTP/2 REST APIs on a private Kubernetes cluster network. This matches the architecture described in 3GPP TS 29.500."

---

### Step 2 · Slice Ping Test (End-to-End Data Plane)
**Target time: 3 min**

- [ ] Show UE is assigned an IP:
  ```bash
  kubectl exec -n open5gs -it \
    $(kubectl get pod -n open5gs -l app=ue -o jsonpath='{.items[0].metadata.name}') \
    -- ip addr show uesimtun0
  ```
  Expected: `10.45.0.x` assigned by the SMF via PFCP.

- [ ] Ping through the GTP-U tunnel:
  ```bash
  kubectl exec -n open5gs -it \
    $(kubectl get pod -n open5gs -l app=ue -o jsonpath='{.items[0].metadata.name}') \
    -- ping -I uesimtun0 8.8.8.8 -c 5
  ```
  Expected: 5/5 packets, 0% loss, ~2 ms RTT.

- [ ] Check slice assignments:
  ```bash
  kubectl exec -n open5gs -it \
    $(kubectl get pod -n open5gs -l app=amf -o jsonpath='{.items[0].metadata.name}') \
    -- grep -i "allowed nssai\|registration accept" /var/log/open5gs/amf.log 2>/dev/null \
    || kubectl logs -n open5gs -l app=amf --tail=30 | grep -i "nssai\|slice\|guti"
  ```

**Talking point:**
> "The UE IP `10.45.0.4` was assigned by the SMF during the PDU Session Establishment — a 5-step NAS + SBI procedure involving AMF, SMF, UPF, and MongoDB. Traffic is GTP-U encapsulated over the N3 interface, decapsulated by UPF, and NAT-forwarded to the internet."

---

### Step 3 · Grafana — Live Metrics Dashboard
**Target time: 2 min**

- [ ] Switch to browser → `http://localhost:3000`
- [ ] Open dashboard: **5G Core Overview** (or Dashboards → open5gs)
- [ ] Point out panels:
  - UPF CPU utilisation
  - HPA replica count for UPF
  - Pod restart counter (should be 0 or very low)
  - Active UE session count

- [ ] If the lecturer asks about data freshness:
  ```bash
  curl -s 'http://localhost:9090/api/v1/query?query=up' | \
    python3 -m json.tool | grep '"value"' | head -5
  ```
  Shows Prometheus is actively scraping all targets at 15 s intervals.

**Talking point:**
> "22 Prometheus scrape targets, 15-second interval. This is the same telemetry the closed-loop ML engine reads every 30 seconds. In the AWS deployment this feeds into Amazon Managed Prometheus with 15-day retention."

---

### Step 4 · Network Query API — Live Natural-Language Question
**Target time: 2 min**

- [ ] Health check first:
  ```bash
  curl -s http://localhost:8080/health | python3 -m json.tool
  ```

- [ ] Get network status score:
  ```bash
  curl -s http://localhost:8080/status | python3 -m json.tool
  ```
  Point out: `overall_score`, `grade`, per-component scores.

- [ ] Ask a natural-language question:
  ```bash
  curl -s -X POST http://localhost:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"question": "Is the network healthy enough to support 150 simultaneous users?"}' \
    | python3 -m json.tool
  ```
  Point out: `answer`, `metrics_used`, `model_used` (will be rule-based offline, or Bedrock in AWS).

- [ ] Show all three slices:
  ```bash
  curl -s http://localhost:8080/slices | python3 -m json.tool
  ```

**Talking point:**
> "This is the Flask-based Network Query API. It fetches live Prometheus metrics, computes a health score, and in the AWS deployment sends the question to Amazon Bedrock's Claude model for a natural-language root-cause analysis. Locally it uses an offline rule-based fallback so the demo works without internet."

---

### Step 5 · Anomaly Simulation + Closed-Loop Engine Logs
**Target time: 3 min**

- [ ] Open a watch on closed-loop logs (new terminal or split pane):
  ```bash
  kubectl logs -n open5gs -l app=closed-loop-engine -f --tail=20 2>/dev/null \
    || echo "Closed-loop not deployed as pod — showing automation log"
  ```

- [ ] Inject a simulated anomaly:
  ```bash
  curl -s -X POST http://localhost:8080/simulate-anomaly \
    -H "Content-Type: application/json" \
    -d '{"cpu_upf": 92.0, "upf_replicas": 2, "cpu_amf": 45.0, "duration": 60}' \
    | python3 -m json.tool
  ```

- [ ] Watch HPA respond (run this and let it update live):
  ```bash
  kubectl get hpa -n open5gs -w
  ```
  Expected: UPF HPA `REPLICAS` column increments within 30–60 s.

- [ ] Clear the anomaly:
  ```bash
  curl -s -X DELETE http://localhost:8080/simulate-anomaly | python3 -m json.tool
  ```

**Talking point:**
> "The closed-loop engine polls Prometheus every 30 seconds. When the IsolationForest anomaly score exceeds 0.5849 — the threshold tuned on our training set — it issues a `kubectl scale` command. The DETECT→DECIDE→ACT cycle completes within the same 30-second window. In the AWS deployment this also calls a SageMaker endpoint for the inference, adding ~2.5 seconds of latency."

---

### Step 6 · Predictive Pre-Scaling Explanation
**Target time: 2 min**

- [ ] Open `automation/closed_loop.py` and scroll to `predict_and_prescale()` — or show this command output:
  ```bash
  grep -n "predict_and_prescale\|PREDICTIVE_THRESH\|ARIMA_MODEL_PATH\|_load_arima_model\|PROACTIVE_REPS" \
    automation/closed_loop.py | head -20
  ```

- [ ] Show the ARIMA model file exists:
  ```bash
  ls -lh ml/models/arima_model.pkl
  python3 -c "
  import pickle
  with open('ml/models/arima_model.pkl','rb') as f:
      m = pickle.load(f)
  print('Model order:', m.order)
  print('Seasonal order:', getattr(m, 'seasonal_order', 'N/A'))
  "
  ```

- [ ] Show the forecast figure:
  ```bash
  open ml/figures/arima_forecast.png      # macOS
  # or: xdg-open ml/figures/arima_forecast.png  # Linux
  ```

**Talking point:**
> "Step 2.5 in the closed-loop cycle runs a local ARIMA(3,0,1) model — loaded from a pickle file, no network call needed. It looks 30 minutes ahead across 6 five-minute steps. If the forecast predicts more than 100 UEs and we're below 3 UPF replicas, it scales proactively — before any CPU spike is visible. This is the distinction between reactive anomaly detection in step 2 and proactive pre-scaling in step 2.5."

---

### Step 7 · WebUI — Subscriber Management
**Target time: 1 min**

- [ ] Switch to browser → `http://localhost:9999`
- [ ] Log in: **admin / 1423**
- [ ] Navigate to: Subscribers
- [ ] Point out the three test subscribers with different S-NSSAIs:
  - IMSI `999700000000001` → SST=1 eMBB
  - IMSI `999700000000002` → SST=2 mMTC
  - IMSI `999700000000003` → SST=3 URLLC

**Talking point:**
> "Each subscriber is provisioned with a specific slice type in MongoDB. When they register, the AMF queries the NSSF with their Requested NSSAI, and the NSSF returns the serving SMF and UPF for that slice. This is how traffic isolation is enforced at the subscriber level."

---

### Step 8 · ML Pipeline Figure
**Target time: 1 min**

- [ ] Open the ML pipeline diagram:
  ```bash
  open docs/figures/ml_pipeline.png          # full pipeline overview
  ```

- [ ] Then open the SHAP figure:
  ```bash
  open ml/figures/shap_summary_plot.png      # feature importance
  ```

**Talking point:**
> "This is the ML pipeline: IsolationForest for anomaly detection, ARIMA for local forecasting, k-Means for network-state classification. The SHAP figure shows that `upf_replicas` — not raw CPU — is the strongest predictor of anomalies. This means the model learned a correlated overload signature: UPF already scaled but AMF still CPU-elevated. That insight is what we'd miss with a simple CPU threshold."

---

### Step 9 · Stress Test Figure — QoS Differentiation
**Target time: 1 min**

- [ ] Open the QoS differentiation result:
  ```bash
  open results/figures/scenario4_qos_differentiation.png
  ```

- [ ] If the lecturer asks for the statistical backing:
  ```bash
  grep -A10 "ANOVA\|Cohen\|p-value\|F-statistic" results/statistical_report.md | head -20
  ```

**Talking point:**
> "Scenario 4 ran all three slices under simultaneous load. ANOVA F=10.09, p<0.0001 — the QoS difference is statistically significant, not random variation. URLLC achieved p50 latency of 0.30 ms versus eMBB's 0.83 ms — Cohen's d of 2.05, a very large effect. The slices are genuinely isolated, not just labelled differently."

---

### Step 10 · Closing — Thesis & Economic Analysis
**Target time: 2 min**

- [ ] Show the thesis word count:
  ```bash
  wc -w report/hit_thesis.md
  ```

- [ ] Show the README headline metrics:
  ```bash
  head -60 README.md | grep -A30 "Key Results\|Results"
  ```

- [ ] Open the architecture diagram:
  ```bash
  open docs/figures/architecture_overview.png
  ```

**Talking point:**
> "The 7-day AWS pilot cost \$32.36 from a real AWS invoice — not estimated. That's 99.4% cheaper than the equivalent on-premises rack (estimated \$5,820 per year). Break-even is at 70 subscribers. The thesis demonstrates that a student-built cloud-native 5G SA core, with production-grade Kubernetes orchestration, ML-driven automation, and a natural-language operations interface, is both technically feasible and economically compelling for a university research lab context."

- [ ] Offer to open specific thesis chapter if the lecturer wants to dig in:
  - Chapter 3 — System Design & Implementation
  - Chapter 4 — Results (stress tests, ML evaluation, AWS deployment)
  - Chapter 5 — Conclusions & Future Work

---

## Quick-Reference Card (cut and keep)

| Step | What | Key command / URL |
|------|------|-------------------|
| 1 | Cluster status | `kubectl get pods -n open5gs` |
| 2 | Slice ping | `kubectl exec ... -- ping -I uesimtun0 8.8.8.8 -c 5` |
| 3 | Grafana | `http://localhost:3000` |
| 4 | NL query | `curl -X POST http://localhost:8080/ask -d '{"question":"..."}'` |
| 5 | Anomaly sim | `curl -X POST http://localhost:8080/simulate-anomaly` |
| 6 | Pre-scaling | `grep predict_and_prescale automation/closed_loop.py` |
| 7 | WebUI | `http://localhost:9999` |
| 8 | ML figure | `open ml/figures/shap_summary_plot.png` |
| 9 | QoS figure | `open results/figures/scenario4_qos_differentiation.png` |
| 10 | Economics | `head -60 README.md` |

---

## If Something Goes Wrong

| Problem | Fast fix |
|---------|----------|
| Pod not Ready | `kubectl wait -n open5gs pod -l app=<name> --for=condition=Ready --timeout=120s` |
| Port-forward dropped | Re-run the port-forward command from the top of this doc |
| API returns 500 | `kubectl logs -n open5gs -l app=network-query-api --tail=30` |
| Ping fails (no uesimtun0) | `kubectl logs -n open5gs -l app=ue --tail=20` — UE may not have registered yet |
| Grafana blank dashboards | Dashboards → Manage → Import `k8s/monitoring/dashboards/` JSON files |
| HPA not scaling | `kubectl describe hpa -n open5gs` — check if metrics-server is running |

---

*Last updated: 2026-06-16 · Nigel Farai Kadzinga · HIT B.Eng Electronic Engineering FYP*
