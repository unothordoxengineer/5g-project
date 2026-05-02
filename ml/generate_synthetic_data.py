#!/opt/homebrew/bin/python3
"""
generate_synthetic_data.py — Synthetic 5G telemetry augmentation for Open5GS.

Generates 7 days of realistic 5G core network telemetry with:
  • Diurnal load patterns (night / morning ramp / daytime / evening peak / dropoff)
  • Weekday vs weekend variation (weekends 40% lower peak)
  • Gaussian noise on all metrics (±5% of mean)
  • 50 labelled anomaly events across 4 categories:
      - CPU spikes      (>85% UPF CPU)
      - Memory leaks    (gradual 30-min increase)
      - Pod crashes     (sudden drop to 0 → recovery)
      - Flash crowds    (5× traffic spike)

Output format matches ~/5g-project/data/raw/ Prometheus CSV format exactly:
  columns: timestamp, metric_name, pod_name, value, load_phase

Per-metric files saved to ~/5g-project/data/synthetic/
Combined file with anomaly_label saved to:
  ~/5g-project/data/synthetic/synthetic_7day_telemetry.csv

Usage:
  cd ~/5g-project/ml && /opt/homebrew/bin/python3 generate_synthetic_data.py
"""

import warnings
warnings.filterwarnings('ignore')

import sys
import json
import random
from pathlib import Path
from datetime import timezone

import numpy as np
import pandas as pd

# ── Reproducibility ────────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
random.seed(SEED)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent
RAW_DIR   = BASE_DIR / 'data' / 'raw'
SYNTH_DIR = BASE_DIR / 'data' / 'synthetic'
SYNTH_DIR.mkdir(parents=True, exist_ok=True)

# ── Pod names (matching real data exactly) ─────────────────────────────────────
# These are the same pod name hashes as the real Prometheus export.
# The run_all_models.py strips everything after the first "-" to get the NF label
# (e.g. "amf-6bdd589888-zll2k" → "amf"), so the suffix does not affect training.
PODS_CPU_MEM = [
    'amf-6bdd589888-zll2k',
    'ausf-7d4d65bc8f-psmkp',
    'bsf-75c77f6785-mlflk',
    'gnb-68849455f4-wqmgj',
    'mongodb-0',
    'nrf-cc9f6c975-5pfzr',
    'nssf-7599889897-f4zjb',
    'pcf-6666b7784f-nkfkn',
    'scp-7f595667f-btjvp',
    'smf-85b99d5b4d-jh4lk',
    'udm-95b5d7d7f-zccjx',
    'udr-d58c4bd58-jnh8x',
    'ue-6b4d9c46fc-wtghn',
    'upf-6bf7fc9b9b-5d5kg',   # primary UPF pod (always running)
]
# Additional UPF pods that HPA spins up under load (pods 2-5)
EXTRA_UPF_PODS = [
    'upf-6bf7fc9b9b-8gzjq',
    'upf-6bf7fc9b9b-94wcs',
    'upf-6bf7fc9b9b-cwmnw',
    'upf-6bf7fc9b9b-fhpzl',
]

UPF_PRIMARY  = 'upf-6bf7fc9b9b-5d5kg'
AMF_POD      = 'amf-6bdd589888-zll2k'
HPA_POD      = 'prometheus-kube-state-metrics-d585bd88d-6hljz'
AMF_SVC      = 'amf.open5gs.svc.cluster.local:9090'
UPF_SVC      = 'upf.open5gs.svc.cluster.local:9090'

# ── Baseline resource budgets (normal, no load) ─────────────────────────────────
# CPU percents at idle (matching real pre_test measurements)
CPU_IDLE = {
    'amf':     0.18,   'ausf':   0.12,   'bsf':    0.10,   'gnb':  0.20,
    'mongodb': 0.35,   'nrf':    0.13,   'nssf':   0.08,   'pcf':  0.11,
    'scp':     0.09,   'smf':    0.15,   'udm':    0.12,   'udr':  0.10,
    'ue':      0.10,   'upf':    1.50,
}
# Per-UE CPU increment for UPF (percent per UE)
CPU_PER_UE_UPF  = 0.38    # 0.38% per UE → at 180 UEs ≈ 68%

# Memory working set bytes at idle (bytes)
MEM_IDLE = {
    'amf':     24_551_424,  'ausf':   18_874_368,   'bsf':    15_728_640,
    'gnb':     20_971_520,  'mongodb':52_428_800,   'nrf':    16_777_216,
    'nssf':    14_680_064,  'pcf':    17_825_792,   'scp':    13_631_488,
    'smf':     21_495_808,  'udm':    16_252_928,   'udr':    15_204_352,
    'ue':      12_582_912,  'upf':    48_234_496,
}
# Memory growth per UE for UPF (bytes per UE)
MEM_PER_UE_UPF = 131_072   # 128 KiB per UE

# ── Time series parameters ─────────────────────────────────────────────────────
START_DATE = pd.Timestamp('2026-04-20T00:00:00', tz='UTC')   # Monday (before real data)
INTERVAL   = 30       # seconds between scrapes (Prometheus default)
DAYS       = 7
N_STEPS    = int(DAYS * 24 * 3600 / INTERVAL)   # 20 160 steps

print(f'  Generating {N_STEPS:,} timesteps over {DAYS} days ({INTERVAL}s intervals)')
print(f'  Period: {START_DATE.date()} → {(START_DATE + pd.Timedelta(days=DAYS)).date()}')

timestamps = pd.date_range(start=START_DATE, periods=N_STEPS, freq=f'{INTERVAL}s', tz='UTC')

# ── Diurnal load factor ────────────────────────────────────────────────────────

def diurnal_factor(hour_float: float) -> float:
    """
    Return dimensionless load multiplier ∈ [0.08, 1.20] for a given decimal hour.

    Pattern:
      00:00–07:00  night           ≈ 0.08–0.12
      07:00–09:00  morning ramp    0.12 → 1.00
      09:00–17:00  daytime plateau ≈ 0.95–1.00
      17:00–21:00  evening peak    1.00 → 1.20 → 1.00
      21:00–24:00  night drop-off  1.00 → 0.08
    """
    h = hour_float % 24
    if h < 7.0:
        # Night — gentle sine to add micro-variation
        return 0.08 + 0.04 * np.sin(np.pi * h / 7.0)
    elif h < 9.0:
        # Morning ramp — smooth logistic
        t = (h - 7.0) / 2.0            # 0 → 1
        return 0.12 + 0.88 / (1 + np.exp(-8 * (t - 0.5)))
    elif h < 17.0:
        # Daytime plateau — slight bump at lunch (12:00)
        return 0.95 + 0.05 * np.sin(np.pi * (h - 9.0) / 8.0)
    elif h < 21.0:
        # Evening peak — bell peaking at 19:00
        t = (h - 17.0) / 4.0           # 0 → 1
        return 1.00 + 0.20 * np.sin(np.pi * t)
    else:
        # Drop-off — exponential decay
        t = (h - 21.0) / 3.0           # 0 → 1
        return 1.00 * (1 - t) + 0.08 * t


# Precompute diurnal factor for all timestamps
hours   = timestamps.hour + timestamps.minute / 60.0 + timestamps.second / 3600.0
dof     = np.vectorize(diurnal_factor)(hours)

# Weekend factor (Sat=5, Sun=6 in pandas dayofweek: Mon=0)
weekend = np.where(timestamps.dayofweek >= 5, 0.60, 1.00)

load    = np.clip(dof * weekend, 0.08, 1.20)   # combined load factor

# Load phase label for each timestep
def _phase(h, is_weekend):
    if h < 7:     return 'night'
    if h < 9:     return 'morning_ramp'
    if h < 17:    return 'daytime'
    if h < 21:    return 'evening_peak'
    return 'night_dropoff'

load_phases = np.array([
    _phase(h, timestamps[i].dayofweek >= 5)
    for i, h in enumerate(hours)
])

# ── Derived signals ────────────────────────────────────────────────────────────

def noisy(arr, frac=0.05):
    """Add Gaussian noise at ±frac fraction of each value."""
    noise = np.random.normal(1.0, frac, size=arr.shape)
    return np.clip(arr * noise, 0, None)


# UE count  (0–200 realistic range)
ue_base    = np.round(load * 175).astype(float)
ue_count   = np.clip(noisy(ue_base, 0.08), 1, 200)

# gNB count (always 1 gNB in the testbed)
gnb_count  = np.ones(N_STEPS, dtype=float)

# UPF CPU: linear with UE count + noise
cpu_upf_base = CPU_IDLE['upf'] + CPU_PER_UE_UPF * ue_count
cpu_upf      = np.clip(noisy(cpu_upf_base, 0.05), 0.5, 99.0)

# HPA replicas: ceil(ue_count / 45), range 1-5
hpa_current  = np.clip(np.ceil(ue_count / 45).astype(int), 1, 5).astype(float)
hpa_desired  = hpa_current.copy()

# GTP pps: proportional to UE count (each UE generates ~4 pps in/out)
gtp_in_pps_arr  = np.clip(noisy(ue_count * 4.2, 0.06), 0, None)
gtp_out_pps_arr = np.clip(noisy(ue_count * 3.9, 0.06), 0, None)

# GTP cumulative packets (integrate pps × INTERVAL)
gtp_in_pkt_arr  = np.cumsum(gtp_in_pps_arr  * INTERVAL).astype(float)
gtp_out_pkt_arr = np.cumsum(gtp_out_pps_arr * INTERVAL).astype(float)

# Per-NF CPU (not UPF): scale gently with load, ±5% noise
def nf_cpu(nf, ue):
    idle = CPU_IDLE[nf]
    # Control-plane NFs see mild CPU increase with UE registrations
    scale = idle + idle * 0.5 * (ue / 180.0)
    return np.clip(noisy(scale * np.ones(N_STEPS), 0.05), 0.01, None)

# Per-NF memory: mostly flat, slight growth with UE count
def nf_mem(nf, ue):
    idle = MEM_IDLE[nf]
    scale = idle + idle * 0.15 * (ue / 180.0)
    return np.clip(noisy(scale * np.ones(N_STEPS), 0.03), 1e6, None)

# UPF memory (scales with UE count)
upf_mem_base = MEM_IDLE['upf'] + MEM_PER_UE_UPF * ue_count
upf_mem      = np.clip(noisy(upf_mem_base, 0.04), 1e6, None)

# Container restarts (normally 0; incremented by pod crash anomalies later)
restarts = {pod: np.zeros(N_STEPS, dtype=float) for pod in PODS_CPU_MEM + EXTRA_UPF_PODS}

# ── Anomaly injection ──────────────────────────────────────────────────────────
# anomaly_label[t] = 1 if any anomaly is active at timestep t
anomaly_label = np.zeros(N_STEPS, dtype=int)

# Helper: convert timestep index to minute marker
def _minutes(n): return n * INTERVAL // 60

# --- Anomaly type 1: CPU spikes  (15 events) -----------------------------------
# UPF CPU jumps to 85-98% for 5-15 minutes during any daytime period.
CPU_SPIKE_EVENTS = [
    # (start_hour_of_day_on_day, day_idx, duration_minutes)
    (9.5,  0, 8),   (12.3, 0, 12),  (15.0, 0, 6),
    (10.2, 1, 10),  (14.5, 1, 7),   (18.0, 1, 9),
    (9.0,  2, 11),  (16.5, 2, 8),   (11.0, 2, 6),
    (13.0, 3, 12),  (19.0, 3, 7),   (10.5, 3, 5),
    (11.5, 4, 9),   (15.3, 5, 8),   (14.0, 6, 10),
]
for (start_h, day, dur_min) in CPU_SPIKE_EVENTS:
    step_s  = int((day * 86400 + start_h * 3600) / INTERVAL)
    step_e  = step_s + int(dur_min * 60 / INTERVAL)
    step_s  = min(step_s, N_STEPS - 1)
    step_e  = min(step_e, N_STEPS)
    if step_s < N_STEPS:
        spike_cpu           = np.random.uniform(85, 98, size=step_e - step_s)
        cpu_upf[step_s:step_e] = spike_cpu
        anomaly_label[step_s:step_e] = 1

# --- Anomaly type 2: Memory leaks  (12 events) ---------------------------------
# One pod's memory grows linearly over 30 minutes, then resets (pod restart).
MEM_LEAK_PODS = [
    ('smf-85b99d5b4d-jh4lk', 'smf'),
    ('pcf-6666b7784f-nkfkn', 'pcf'),
    ('amf-6bdd589888-zll2k', 'amf'),
]
MEM_LEAK_EVENTS = [
    (8.0,  0, 0), (11.0, 1, 1), (14.0, 2, 0),
    (9.5,  3, 2), (13.0, 4, 1), (10.0, 5, 0),
    (16.0, 0, 1), (17.5, 2, 2), (20.0, 3, 0),
    (7.5,  4, 2), (12.0, 5, 1), (15.0, 6, 0),
]
# Store per-NF memory arrays so we can modify them
nf_mem_arrays = {}
for pod in PODS_CPU_MEM:
    nf  = pod.split('-')[0]
    nf_mem_arrays[pod] = nf_mem(nf, ue_count)
nf_mem_arrays[UPF_PRIMARY] = upf_mem.copy()

for i, (start_h, day, pod_idx) in enumerate(MEM_LEAK_EVENTS):
    pod    = MEM_LEAK_PODS[pod_idx % len(MEM_LEAK_PODS)][0]
    nf     = pod.split('-')[0]
    step_s = int((day * 86400 + start_h * 3600) / INTERVAL)
    dur    = int(30 * 60 / INTERVAL)    # 30 minutes
    step_e = min(step_s + dur, N_STEPS)
    if step_s < N_STEPS:
        arr     = nf_mem_arrays[pod]
        base    = float(arr[step_s])
        # Gradual increase to 3× baseline over 30 min
        leak    = np.linspace(base, base * 3.0, step_e - step_s)
        arr[step_s:step_e] = leak
        # Reset after leak
        if step_e < N_STEPS:
            arr[step_e] = base * 0.95   # slight reset after pod restart
        nf_mem_arrays[pod] = arr
        anomaly_label[step_s:step_e] = 1

# --- Anomaly type 3: Pod crashes  (12 events) ----------------------------------
# A pod suddenly disappears (value → 0) for 2-5 min, then recovers.
# container_restarts_total increments after each crash.
CRASH_PODS = [
    'smf-85b99d5b4d-jh4lk',
    'udm-95b5d7d7f-zccjx',
    'pcf-6666b7784f-nkfkn',
    'ausf-7d4d65bc8f-psmkp',
]
CRASH_EVENTS = [
    (10.5, 0), (14.0, 0), (9.0,  1), (18.5, 1),
    (11.5, 2), (16.0, 2), (13.0, 3), (20.0, 3),
    (10.0, 4), (15.5, 4), (12.0, 5), (14.5, 6),
]
restart_acc = {pod: 0 for pod in CRASH_PODS}   # cumulative restart counter

# CPU crash arrays (per-pod)
nf_cpu_arrays = {}
for pod in PODS_CPU_MEM:
    nf = pod.split('-')[0]
    if nf == 'upf':
        nf_cpu_arrays[pod] = cpu_upf.copy()
    else:
        nf_cpu_arrays[pod] = nf_cpu(nf, ue_count)

for i, (start_h, day) in enumerate(CRASH_EVENTS):
    pod    = CRASH_PODS[i % len(CRASH_PODS)]
    step_s = int((day * 86400 + start_h * 3600) / INTERVAL)
    dur    = int(random.randint(2, 5) * 60 / INTERVAL)   # 2-5 min down
    step_e = min(step_s + dur, N_STEPS)
    rec_e  = min(step_e + int(3 * 60 / INTERVAL), N_STEPS)   # 3 min recovery
    if step_s < N_STEPS:
        # Zero out during crash
        if pod in nf_cpu_arrays:
            nf_cpu_arrays[pod][step_s:step_e] = 0.0
            # Recovery ramp
            rec_len = rec_e - step_e
            if rec_len > 0:
                nf_mean = CPU_IDLE[pod.split('-')[0]]
                nf_cpu_arrays[pod][step_e:rec_e] = np.linspace(0, nf_mean, rec_len)
        if pod in nf_mem_arrays:
            nf_mem_arrays[pod][step_s:step_e] = 0.0
        # Increment restart counter from crash point onward
        restart_acc[pod] += 1
        restarts[pod][step_e:] = float(restart_acc[pod])
        anomaly_label[step_s:step_e] = 1

# --- Anomaly type 4: Flash crowds  (11 events) ---------------------------------
# Sudden 5× traffic spike: UE count, GTP pps, and UPF CPU all spike.
FLASH_EVENTS = [
    (13.5, 0, 15), (17.0, 0, 12),
    (11.0, 1, 18), (19.5, 1, 10),
    (10.5, 2, 14), (16.0, 2, 11),
    (12.0, 3, 20), (18.5, 3, 8),
    (15.0, 4, 13), (11.5, 5, 16),
    (14.0, 6, 12),
]
for (start_h, day, dur_min) in FLASH_EVENTS:
    step_s = int((day * 86400 + start_h * 3600) / INTERVAL)
    step_e = min(step_s + int(dur_min * 60 / INTERVAL), N_STEPS)
    if step_s < N_STEPS:
        # 5× spike
        ue_count[step_s:step_e]        = np.clip(ue_count[step_s:step_e] * 5, 0, 200)
        gtp_in_pps_arr[step_s:step_e]  *= 5
        gtp_out_pps_arr[step_s:step_e] *= 5
        cpu_upf[step_s:step_e]          = np.clip(cpu_upf[step_s:step_e] * 4.5, 0, 99)
        hpa_desired[step_s:step_e]      = np.clip(hpa_current[step_s:step_e] + 2, 1, 5)
        anomaly_label[step_s:step_e]    = 1

total_anomaly_steps  = int(anomaly_label.sum())
total_anomaly_events = (len(CPU_SPIKE_EVENTS) + len(MEM_LEAK_EVENTS) +
                        len(CRASH_EVENTS)    + len(FLASH_EVENTS))
print(f'\n  Anomaly events injected: {total_anomaly_events}')
print(f'    CPU spikes:    {len(CPU_SPIKE_EVENTS)}')
print(f'    Memory leaks:  {len(MEM_LEAK_EVENTS)}')
print(f'    Pod crashes:   {len(CRASH_EVENTS)}')
print(f'    Flash crowds:  {len(FLASH_EVENTS)}')
print(f'  Anomalous steps: {total_anomaly_steps:,} / {N_STEPS:,}'
      f'  ({total_anomaly_steps/N_STEPS*100:.1f}%)')

# ── Assemble per-metric DataFrames ─────────────────────────────────────────────

def make_df(metric, pod, values, lp=None):
    """Build a tidy long-format DataFrame matching the raw CSV schema."""
    return pd.DataFrame({
        'timestamp':    timestamps,
        'metric_name':  metric,
        'pod_name':     pod,
        'value':        np.round(values, 6),
        'load_phase':   lp if lp is not None else load_phases,
        'anomaly_label': anomaly_label,
    })


print('\n  Assembling per-metric DataFrames...')

all_dfs = []    # collect all rows for the combined file

# 1. cpu_usage_percent
print('    cpu_usage_percent')
cpu_rows = []
for pod in PODS_CPU_MEM:
    nf = pod.split('-')[0]
    if nf == 'upf':
        cpu_arr = cpu_upf
    elif pod in nf_cpu_arrays:
        cpu_arr = nf_cpu_arrays[pod]
    else:
        cpu_arr = nf_cpu(nf, ue_count)
    cpu_rows.append(make_df('cpu_usage_percent', pod, cpu_arr))
# Active extra UPF pods (only appear when hpa_current >= their slot)
for slot, pod in enumerate(EXTRA_UPF_PODS, start=2):
    active = hpa_current >= slot
    arr    = np.where(active, cpu_upf * np.random.uniform(0.7, 0.9, N_STEPS), 0.0)
    cpu_rows.append(make_df('cpu_usage_percent', pod, arr))
df_cpu = pd.concat(cpu_rows, ignore_index=True)
all_dfs.append(df_cpu)

# 2. memory_working_set_bytes
print('    memory_working_set_bytes')
mem_rows = []
for pod in PODS_CPU_MEM:
    nf = pod.split('-')[0]
    if nf == 'upf':
        mem_arr = nf_mem_arrays.get(pod, upf_mem)
    elif pod in nf_mem_arrays:
        mem_arr = nf_mem_arrays[pod]
    else:
        mem_arr = nf_mem(nf, ue_count)
    mem_rows.append(make_df('memory_working_set_bytes', pod, mem_arr))
for slot, pod in enumerate(EXTRA_UPF_PODS, start=2):
    active  = hpa_current >= slot
    mem_arr = np.where(active, upf_mem * np.random.uniform(0.8, 1.1, N_STEPS), 0.0)
    mem_rows.append(make_df('memory_working_set_bytes', pod, mem_arr))
df_mem = pd.concat(mem_rows, ignore_index=True)
all_dfs.append(df_mem)

# 3. upf_hpa_current_replicas
print('    upf_hpa_current_replicas')
df_hpa_cur = make_df('upf_hpa_current_replicas', HPA_POD, hpa_current)
all_dfs.append(df_hpa_cur)

# 4. upf_hpa_desired_replicas
print('    upf_hpa_desired_replicas')
df_hpa_des = make_df('upf_hpa_desired_replicas', HPA_POD, hpa_desired)
all_dfs.append(df_hpa_des)

# 5. upf_gtp_in_pps
print('    upf_gtp_in_pps')
df_gtp_in_pps = make_df('upf_gtp_in_pps', UPF_SVC, gtp_in_pps_arr)
all_dfs.append(df_gtp_in_pps)

# 6. upf_gtp_out_pps
print('    upf_gtp_out_pps')
df_gtp_out_pps = make_df('upf_gtp_out_pps', UPF_SVC, gtp_out_pps_arr)
all_dfs.append(df_gtp_out_pps)

# 7. upf_gtp_in_packets (cumulative counter)
print('    upf_gtp_in_packets')
df_gtp_in_pkt = make_df('upf_gtp_in_packets', UPF_SVC, gtp_in_pkt_arr)
all_dfs.append(df_gtp_in_pkt)

# 8. upf_gtp_out_packets (cumulative counter)
print('    upf_gtp_out_packets')
df_gtp_out_pkt = make_df('upf_gtp_out_packets', UPF_SVC, gtp_out_pkt_arr)
all_dfs.append(df_gtp_out_pkt)

# 9. amf_ran_ue_count
print('    amf_ran_ue_count')
df_ue = make_df('amf_ran_ue_count', AMF_SVC, ue_count)
all_dfs.append(df_ue)

# 10. amf_gnb_count
print('    amf_gnb_count')
df_gnb = make_df('amf_gnb_count', AMF_SVC, gnb_count)
all_dfs.append(df_gnb)

# 11. container_restarts_total
print('    container_restarts_total')
restart_rows = []
for pod in PODS_CPU_MEM + EXTRA_UPF_PODS:
    arr = restarts.get(pod, np.zeros(N_STEPS, dtype=float))
    restart_rows.append(make_df('container_restarts_total', pod, arr))
df_restart = pd.concat(restart_rows, ignore_index=True)
all_dfs.append(df_restart)

# ── Save per-metric files  (same format as data/raw/, minus anomaly_label) ─────
print('\n  Saving per-metric CSV files...')
metric_dfs = {
    'cpu_usage_percent.csv':          df_cpu,
    'memory_working_set_bytes.csv':   df_mem,
    'upf_hpa_current_replicas.csv':   df_hpa_cur,
    'upf_hpa_desired_replicas.csv':   df_hpa_des,
    'upf_gtp_in_pps.csv':             df_gtp_in_pps,
    'upf_gtp_out_pps.csv':            df_gtp_out_pps,
    'upf_gtp_in_packets.csv':         df_gtp_in_pkt,
    'upf_gtp_out_packets.csv':        df_gtp_out_pkt,
    'amf_ran_ue_count.csv':           df_ue,
    'amf_gnb_count.csv':              df_gnb,
    'container_restarts_total.csv':   df_restart,
}
# Raw-format columns (no anomaly_label)
RAW_COLS = ['timestamp', 'metric_name', 'pod_name', 'value', 'load_phase']

for fname, df in metric_dfs.items():
    out_path = SYNTH_DIR / fname
    # Keep only raw-format columns for per-metric files
    df[RAW_COLS].to_csv(out_path, index=False)
    print(f'    {fname}: {len(df):,} rows → {out_path}')

# ── Save combined file with anomaly_label ──────────────────────────────────────
print('\n  Saving combined telemetry file...')
combined = pd.concat(all_dfs, ignore_index=True)
combined = combined.sort_values(['timestamp', 'metric_name', 'pod_name'])
combined_path = SYNTH_DIR / 'synthetic_7day_telemetry.csv'
combined.to_csv(combined_path, index=False)
print(f'    synthetic_7day_telemetry.csv: {len(combined):,} rows → {combined_path}')

# ── Summary statistics ─────────────────────────────────────────────────────────
print('\n' + '='*60)
print('SYNTHETIC DATA GENERATION SUMMARY')
print('='*60)

total_samples   = len(combined)
anomaly_rows    = int((combined['anomaly_label'] == 1).sum())
normal_rows     = total_samples - anomaly_rows
anomaly_pct     = anomaly_rows / total_samples * 100

# Samples per day (use first metric as representative)
ue_only = combined[combined['metric_name'] == 'amf_ran_ue_count'].copy()
ue_only['date'] = ue_only['timestamp'].dt.date
spd = ue_only.groupby('date').size()

print(f'  Total samples (all metrics × all pods): {total_samples:,}')
print(f'  Normal samples:                          {normal_rows:,} ({100-anomaly_pct:.1f}%)')
print(f'  Anomaly samples:                         {anomaly_rows:,} ({anomaly_pct:.1f}%)')
print(f'  Anomaly events:                          {total_anomaly_events}')
print(f'    CPU spikes:    {len(CPU_SPIKE_EVENTS)} events')
print(f'    Memory leaks:  {len(MEM_LEAK_EVENTS)} events')
print(f'    Pod crashes:   {len(CRASH_EVENTS)} events')
print(f'    Flash crowds:  {len(FLASH_EVENTS)} events')
print()
print('  Samples per day (amf_ran_ue_count metric):')
for date, cnt in spd.items():
    dow = pd.Timestamp(date).day_name()
    tag = ' (weekend)' if pd.Timestamp(date).dayofweek >= 5 else ''
    print(f'    {date}  {dow:<9}{tag:>10}: {cnt:,} samples')
print()
print(f'  Date range:  {timestamps[0].isoformat()} → {timestamps[-1].isoformat()}')
print(f'  Scrape interval: {INTERVAL}s')
print()

# Signal statistics
print('  Signal statistics (mean ± std, full 7-day window):')
print(f'    UE count:       {ue_count.mean():.1f} ± {ue_count.std():.1f}  '
      f'(min={ue_count.min():.0f}, max={ue_count.max():.0f})')
print(f'    UPF CPU (%):    {cpu_upf.mean():.1f} ± {cpu_upf.std():.1f}  '
      f'(min={cpu_upf.min():.1f}, max={cpu_upf.max():.1f})')
print(f'    UPF replicas:   {hpa_current.mean():.1f} ± {hpa_current.std():.1f}  '
      f'(min={hpa_current.min():.0f}, max={hpa_current.max():.0f})')
print(f'    GTP in pps:     {gtp_in_pps_arr.mean():.0f} ± {gtp_in_pps_arr.std():.0f}')
print()
print(f'  Output directory: {SYNTH_DIR}')
print(f'  Per-metric files: {len(metric_dfs)}')
print(f'  Combined file:    synthetic_7day_telemetry.csv')
print('='*60)
print('  DONE ✅')
