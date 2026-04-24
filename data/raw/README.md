# Open5GS Phase 4 — Raw Metrics

**Export time range**: 2026-04-23T06:12:44.944304+00:00 → 2026-04-23T14:12:44.944313+00:00

## CSV Column Descriptions

| Column | Description |
|--------|-------------|
| `timestamp` | ISO-8601 UTC timestamp of the sample |
| `metric_name` | Prometheus metric identifier (matches filename) |
| `pod_name` | Kubernetes pod name the metric belongs to |
| `value` | Numeric sample value (units depend on metric — see below) |
| `load_phase` | Load test phase active at sample time (from `load_phases.csv`) |

## Metric Descriptions

| Metric | Units | Source |
|--------|-------|--------|
| `cpu_usage_percent` | — | CPU usage % per pod (1m rate of cpu_seconds_total) |
| `memory_working_set_bytes` | — | Memory working set bytes per pod |
| `container_restarts_total` | — | Total container restarts per pod |
| `upf_hpa_current_replicas` | — | UPF HPA current replica count |
| `upf_hpa_desired_replicas` | — | UPF HPA desired replica count |
| `upf_gtp_in_packets` | — | UPF N3 uplink GTP packet count (cumulative) |
| `upf_gtp_out_packets` | — | UPF N3 downlink GTP packet count (cumulative) |
| `upf_gtp_in_pps` | — | UPF N3 uplink packets/sec (1m rate) |
| `upf_gtp_out_pps` | — | UPF N3 downlink packets/sec (1m rate) |
| `amf_gnb_count` | — | Number of connected gNBs (AMF metric) |
| `amf_ran_ue_count` | — | Number of active RAN UEs (AMF metric) |
| `amf_amf_ue_count` | — | Number of AMF UE contexts (AMF metric) |
| `smf_session_count` | — | Number of active SMF PDU sessions |
| `pcf_am_policy_req_total` | — | PCF AM policy association requests (cumulative) |

## Load Phases

| Phase | Duration | Description |
|-------|----------|-------------|
| `A_baseline` | 10 min | 2 parallel iperf3 streams — light load |
| `B_moderate` | 15 min | 20 parallel streams — moderate load |
| `C_high` | 15 min | 64 parallel streams — high load targeting UPF CPU >70% |
| `D_recovery` | 10 min | Back to 2 streams — observe HPA scale-down |
| `unknown` | — | Samples before load test started |

## Files

| File | Description |
|------|-------------|
| `load_phases.csv` | Timestamped phase log from `load_generator.sh` |
| `cpu_usage_percent.csv` | cpu_usage_percent time series |
| `memory_working_set_bytes.csv` | memory_working_set_bytes time series |
| `container_restarts_total.csv` | container_restarts_total time series |
| `upf_hpa_current_replicas.csv` | upf_hpa_current_replicas time series |
| `upf_hpa_desired_replicas.csv` | upf_hpa_desired_replicas time series |
| `upf_gtp_in_packets.csv` | upf_gtp_in_packets time series |
| `upf_gtp_out_packets.csv` | upf_gtp_out_packets time series |
| `upf_gtp_in_pps.csv` | upf_gtp_in_pps time series |
| `upf_gtp_out_pps.csv` | upf_gtp_out_pps time series |
| `amf_gnb_count.csv` | amf_gnb_count time series |
| `amf_ran_ue_count.csv` | amf_ran_ue_count time series |
| `amf_amf_ue_count.csv` | amf_amf_ue_count time series |
| `smf_session_count.csv` | smf_session_count time series |
| `pcf_am_policy_req_total.csv` | pcf_am_policy_req_total time series |
