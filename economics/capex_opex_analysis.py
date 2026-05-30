#!/usr/bin/env python3
"""
capex_opex_analysis.py
======================
Phase 8.9 — Comprehensive Economic Analysis
Cloud-Native 5G SA Core vs Traditional EPC Infrastructure

Author  : Nigel Kadzunga, HIT Final Year Engineering Project
Date    : 2026-05-30
Data    : Real AWS billing ($32.36 over 7 days, May 21-28 2026)
"""

import os, json, math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path

BASE_DIR = Path(__file__).parent
FIG_DIR  = BASE_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

DPI = 150
sns.set_theme(style="whitegrid", context="paper", font_scale=1.15)

PALETTE = {
    "tier1":   "#1f4e79",
    "tier2":   "#2e75b6",
    "cloud":   "#2e8b57",
    "savings": "#f0a500",
    "accent":  "#c0392b",
    "neutral": "#7f8c8d",
    "light":   "#d6eaf8",
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — TRADITIONAL EPC HARDWARE BASELINE
# ═══════════════════════════════════════════════════════════════════
print("=" * 70)
print("SECTION 1 — TRADITIONAL EPC HARDWARE BASELINE")
print("=" * 70)

T1_CAPEX=3_200_000; T1_MAINT=0.15; T1_REFRESH_YR=5
T1_DC=120_000; T1_OPS=4*45_000
t1_ann_maint = T1_CAPEX * T1_MAINT
t1_rows=[]
for y in range(1,6):
    cap = T1_CAPEX if y==1 else (T1_CAPEX if y==T1_REFRESH_YR else 0)
    opx = t1_ann_maint + T1_DC + T1_OPS
    t1_rows.append({"year":y,"capex":cap,"opex":opx,"total":cap+opx})
T1_5YR = sum(r["total"] for r in t1_rows)
T1_CUM  = np.cumsum([r["total"] for r in t1_rows])

T2_CAPEX=800_000; T2_MAINT=0.15; T2_REFRESH_YR=5
T2_DC=48_000; T2_OPS=2*30_000
t2_ann_maint = T2_CAPEX * T2_MAINT
t2_rows=[]
for y in range(1,6):
    cap = T2_CAPEX if y==1 else (T2_CAPEX if y==T2_REFRESH_YR else 0)
    opx = t2_ann_maint + T2_DC + T2_OPS
    t2_rows.append({"year":y,"capex":cap,"opex":opx,"total":cap+opx})
T2_5YR = sum(r["total"] for r in t2_rows)
T2_CUM  = np.cumsum([r["total"] for r in t2_rows])

print(f"  Tier 1 5-yr TCO: ${T1_5YR:,.0f}")
for r in t1_rows:
    print(f"    Yr{r['year']}: CAPEX ${r['capex']:>10,.0f}  OPEX ${r['opex']:>10,.0f}  Total ${r['total']:>10,.0f}")
print(f"  Tier 2 5-yr TCO: ${T2_5YR:,.0f}")
for r in t2_rows:
    print(f"    Yr{r['year']}: CAPEX ${r['capex']:>10,.0f}  OPEX ${r['opex']:>10,.0f}  Total ${r['total']:>10,.0f}")

# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — CLOUD-NATIVE AWS COSTS (REAL DATA)
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 2 — CLOUD-NATIVE AWS COSTS (REAL DATA)")
print("=" * 70)

ACTUAL_SPEND=32.36; ACTUAL_DAYS=7; ACTUAL_DAILY=ACTUAL_SPEND/ACTUAL_DAYS

MIN_DAILY       = 2.60
STANDARD_DAILY  = 2.40+1.99+2.16+0.50+0.30       # 7.35
FULL_PROD_DAILY = 2.40+3.00+2.16+1.00+0.22+0.40   # 9.18
ENTERPRISE_DAILY= 2.40+6.00+2.16+4.68+2.00+0.50+1.00+0.80  # 19.54

CLOUD_DAILY = FULL_PROD_DAILY
CLOUD_ANNUAL = CLOUD_DAILY * 365.25
CLOUD_5YR   = CLOUD_ANNUAL * 5

print(f"  Real 7-day spend: ${ACTUAL_SPEND} (${ACTUAL_DAILY:.2f}/day)")
print(f"  Full Production daily: ${CLOUD_DAILY:.2f}  annual: ${CLOUD_ANNUAL:,.0f}  5yr: ${CLOUD_5YR:,.0f}")
print(f"  TCO reduction vs Tier 1: {(1-CLOUD_5YR/T1_5YR)*100:.1f}%")
print(f"  TCO reduction vs Tier 2: {(1-CLOUD_5YR/T2_5YR)*100:.1f}%")

# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — AUTOSCALING COST SAVINGS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 3 — AUTOSCALING COST SAVINGS (HPA vs FIXED)")
print("=" * 70)

T3_HR=0.0416; HRS_YR=8760
FIXED_R=5; HPA_R=2.3
fixed_ann = FIXED_R * T3_HR * HRS_YR
hpa_ann   = HPA_R   * T3_HR * HRS_YR
ann_sav   = fixed_ann - hpa_ann
pct_red   = ann_sav / fixed_ann * 100
fyr_sav   = ann_sav * 5

np.random.seed(42)
replica_dist = np.random.choice([1,2,3,4,5], size=2016,
                                p=[0.30,0.35,0.20,0.10,0.05])
HPA_MEAN = np.mean(replica_dist)

print(f"  Fixed (5 replicas): ${fixed_ann:,.2f}/yr")
print(f"  HPA   (avg {HPA_R}):   ${hpa_ann:,.2f}/yr")
print(f"  Annual savings: ${ann_sav:,.2f}  ({pct_red:.1f}%)")
print(f"  5-year savings: ${fyr_sav:,.2f}")

# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — AI/ML COST-BENEFIT
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 4 — AI/ML COST-BENEFIT ANALYSIS")
print("=" * 70)

SM_HR=0.065; SM_N=3
SM_ANN   = SM_HR * SM_N * HRS_YR
BDR_COST_CALL = (500/1e6)*3.00 + (800/1e6)*15.00
BDR_ANN  = BDR_COST_CALL * 12 * HRS_YR
AI_COST_ANN = SM_ANN + BDR_ANN

OUTAGE_MIN=5600; EVT_WK=1; MIN_SAVED=10
ANOMALY_VAL = EVT_WK * 52 * MIN_SAVED * OUTAGE_MIN

FORECAST_VAL = 1000 * (25/3600) * 50 * 0.001 * 365.25 * 3600 / 3600
QOS_VAL      = 1000 * 4.0 * 12 * 0.03
AI_VAL_ANN   = ANOMALY_VAL + FORECAST_VAL + QOS_VAL
AI_ROI       = AI_VAL_ANN / AI_COST_ANN * 100
AI_PAYBACK   = AI_COST_ANN / AI_VAL_ANN * 12

print(f"  SM annual cost:  ${SM_ANN:,.2f}")
print(f"  Bedrock annual:  ${BDR_ANN:,.2f}")
print(f"  Total AI cost:   ${AI_COST_ANN:,.2f}/yr")
print(f"  Anomaly value:   ${ANOMALY_VAL:,.0f}/yr")
print(f"  Forecast value:  ${FORECAST_VAL:,.0f}/yr")
print(f"  QoS value:       ${QOS_VAL:,.0f}/yr")
print(f"  Total AI value:  ${AI_VAL_ANN:,.0f}/yr")
print(f"  AI ROI:          {AI_ROI:,.0f}%")
print(f"  AI payback:      {AI_PAYBACK:.1f} months")

# ═══════════════════════════════════════════════════════════════════
# SECTION 5 — NETWORK SLICING
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 5 — NETWORK SLICING ECONOMIC VALUE")
print("=" * 70)

TRAD_MULTI = 3 * 800_000
CLOUD_SLICE_5YR = 3 * 500 * 5 + 50_000
SLICE_SAV = TRAD_MULTI - CLOUD_SLICE_5YR

EMBB_REV  = 5000  * 8.0  * 12
MMTC_REV  = 50000 * 0.5  * 12
URLLC_REV = 10    * 500  * 12

print(f"  Traditional 3-core CAPEX:  ${TRAD_MULTI:,.0f}")
print(f"  Cloud slicing 5-yr cost:   ${CLOUD_SLICE_5YR:,.0f}")
print(f"  Savings:                   ${SLICE_SAV:,.0f}")
print(f"  eMBB rev potential:        ${EMBB_REV:,.0f}/yr")
print(f"  mMTC rev potential:        ${MMTC_REV:,.0f}/yr")
print(f"  URLLC rev potential:       ${URLLC_REV:,.0f}/yr")

# ═══════════════════════════════════════════════════════════════════
# SECTION 6 — BREAK-EVEN
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 6 — BREAK-EVEN ANALYSIS")
print("=" * 70)

MIG_COST = 50_000
t2_mo_opex    = (t2_ann_maint + T2_DC + T2_OPS) / 12
cloud_mo      = CLOUD_DAILY * 30.44
mo_sav        = t2_mo_opex - cloud_mo
be_base       = MIG_COST / mo_sav

cloud_mo_best  = cloud_mo * 0.60
cloud_mo_worst = cloud_mo * 1.20
be_best  = MIG_COST / (t2_mo_opex - cloud_mo_best)
be_worst = MIG_COST / (t2_mo_opex - cloud_mo_worst) if (t2_mo_opex - cloud_mo_worst) > 0 else 999

months = np.arange(0, 61)
hw_cum    = T2_CAPEX + t2_mo_opex * months
cloud_cum = MIG_COST + cloud_mo   * months

print(f"  T2 monthly OPEX:    ${t2_mo_opex:,.0f}/mo")
print(f"  Cloud monthly cost: ${cloud_mo:,.0f}/mo")
print(f"  Monthly savings:    ${mo_sav:,.0f}/mo")
print(f"  Break-even base:    {be_base:.1f} months")
print(f"  Break-even best:    {be_best:.1f} months  (40% reserved discount)")
print(f"  Break-even worst:   {be_worst:.1f} months (20% overrun)")

# ═══════════════════════════════════════════════════════════════════
# SECTION 7 — SENSITIVITY
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 7 — SENSITIVITY ANALYSIS")
print("=" * 70)

tornado = {
    "AWS price ±20%":          (CLOUD_5YR*0.80, CLOUD_5YR*1.20),
    "UE count 100–50K":        (CLOUD_DAILY*0.6*365.25*5, CLOUD_DAILY*4.0*365.25*5),
    "Reserved inst. discount": (CLOUD_5YR*0.40, CLOUD_5YR),
    "Node count 3–12":         (CLOUD_5YR,       CLOUD_DAILY*2.35*365.25*5),
    "Migration overrun ±20%":  (MIG_COST*0.8+CLOUD_5YR, MIG_COST*1.2+CLOUD_5YR),
    "Data transfer variance":  (CLOUD_5YR*0.97,  CLOUD_5YR*1.05),
}

for k,(lo,hi) in tornado.items():
    print(f"  {k:<35}  low: ${lo:>10,.0f}   high: ${hi:>10,.0f}   range: ${hi-lo:>10,.0f}")

# ═══════════════════════════════════════════════════════════════════
# SECTION 8 — AFRICAN TELECOMS MARKET
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 8 — AFRICAN TELECOMS MARKET CONTEXT")
print("=" * 70)

ZIM_ARPU=4.00
CLOUD_MO_FULL = CLOUD_DAILY * 30.44
T2_MO_AMORT   = T2_5YR / (5*12)
BE_UES_CLOUD  = math.ceil(CLOUD_MO_FULL / ZIM_ARPU)
BE_UES_HW     = math.ceil(T2_MO_AMORT / ZIM_ARPU)

GROWTH = {"Optimistic (30%/yr)":0.30, "Base (15%/yr)":0.15, "Pessimistic (5%/yr)":0.05}
INIT_SUBS = 500
cumrev = {}
for label, rate in GROWTH.items():
    monthly_r=[]; subs=INIT_SUBS
    for m in range(61):
        monthly_r.append(subs * ZIM_ARPU)
        subs *= (1 + rate/12)
    cumrev[label] = np.cumsum(monthly_r)

print(f"  Break-even UEs cloud: {BE_UES_CLOUD}")
print(f"  Break-even UEs hw:    {BE_UES_HW}")

# ═══════════════════════════════════════════════════════════════════
# SECTION 9 — CARBON ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SECTION 9 — CARBON / ENVIRONMENTAL ANALYSIS")
print("=" * 70)

TRAD_PUE=1.8; AWS_PUE=1.2
TRAD_KWH = (20 * 300 * TRAD_PUE / 1000) * HRS_YR
CLOUD_KWH= (6  *  35 * AWS_PUE  / 1000) * HRS_YR
KWH_SAVED= TRAD_KWH - CLOUD_KWH
CO2_SAVED_T = KWH_SAVED * 0.38 / 1000
CARBON_VAL  = CO2_SAVED_T * 50

print(f"  Traditional DC: {TRAD_KWH:,.0f} kWh/yr  (PUE {TRAD_PUE})")
print(f"  AWS Cloud:      {CLOUD_KWH:,.0f} kWh/yr  (PUE {AWS_PUE})")
print(f"  kWh saved:      {KWH_SAVED:,.0f} kWh/yr")
print(f"  CO2 saved:      {CO2_SAVED_T:.1f} tonnes/yr")
print(f"  Carbon value:   ${CARBON_VAL:,.0f}/yr")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 1 — 5-YEAR CAPEX vs OPEX
# ═══════════════════════════════════════════════════════════════════
print("\n--- Generating Figure 1 ---")

yr_labels=["Year 1","Year 2","Year 3","Year 4","Year 5"]
t1_cap=[r["capex"] for r in t1_rows]; t1_op=[r["opex"] for r in t1_rows]
t2_cap=[r["capex"] for r in t2_rows]; t2_op=[r["opex"] for r in t2_rows]
cl_ser=[CLOUD_ANNUAL]*5
cl_cum=np.cumsum(cl_ser)

fig, axes = plt.subplots(1,2,figsize=(14,6))
fig.suptitle("5-Year TCO: Hardware EPC vs Cloud-Native 5G Core",fontsize=14,fontweight="bold")
x=np.arange(5); w=0.26; ax=axes[0]
ax.bar(x-w,t1_cap,w,label="Tier 1 CAPEX",color=PALETTE["tier1"],alpha=0.9)
ax.bar(x-w,t1_op, w,bottom=t1_cap,label="Tier 1 OPEX",color=PALETTE["tier1"],alpha=0.45,hatch="//")
ax.bar(x,   t2_cap,w,label="Tier 2 CAPEX",color=PALETTE["tier2"],alpha=0.9)
ax.bar(x,   t2_op, w,bottom=t2_cap,label="Tier 2 OPEX",color=PALETTE["tier2"],alpha=0.45,hatch="//")
ax.bar(x+w, cl_ser,w,label="Cloud-Native",color=PALETTE["cloud"],alpha=0.9)
ax.set_xticks(x); ax.set_xticklabels(yr_labels)
ax.set_ylabel("Annual Cost (USD)")
ax.set_title("Annual Cost by Year")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v/1e3:.0f}K"))
ax.legend(fontsize=8)

ax2=axes[1]
ax2.plot(range(1,6),T1_CUM/1e6,"o-",color=PALETTE["tier1"],lw=2.5,label=f"Tier 1 HW  (5yr: ${T1_5YR/1e6:.2f}M)")
ax2.plot(range(1,6),T2_CUM/1e3,"s-",color=PALETTE["tier2"],lw=2.5,label=f"Tier 2 HW  (5yr: ${T2_5YR/1e3:.0f}K)")
ax2.plot(range(1,6),cl_cum/1e3,"^-",color=PALETTE["cloud"],lw=2.5,label=f"Cloud-Native (5yr: ${CLOUD_5YR/1e3:.0f}K)")
be_yr=be_base/12
if 0<be_yr<5:
    be_v=(MIG_COST+CLOUD_DAILY*365.25*be_yr)/1e3
    ax2.axvline(be_yr,color=PALETTE["accent"],ls="--",lw=1.5,alpha=0.8)
    ax2.annotate(f"Break-even\n~{be_base:.0f} mo",xy=(be_yr,be_v),
                 xytext=(be_yr+0.25,be_v+80),fontsize=8,color=PALETTE["accent"],
                 arrowprops=dict(arrowstyle="->",color=PALETTE["accent"]))
ax2.set_xlabel("Year"); ax2.set_ylabel("Cumulative Cost")
ax2.set_title("Cumulative 5-Year TCO")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:.0f}K" if v<1000 else f"${v/1e3:.1f}M"))
ax2.legend(fontsize=8); ax2.set_xticks(range(1,6)); ax2.set_xticklabels(yr_labels)
plt.tight_layout()
fig.savefig(FIG_DIR/"capex_vs_opex_5year.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 1 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 2 — BREAK-EVEN ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 2 ---")
fig,ax=plt.subplots(figsize=(11,6))
ax.set_title("Cumulative Cost Break-Even: Cloud-Native vs Tier 2 Hardware",fontsize=13,fontweight="bold")
ax.plot(months,hw_cum/1e3,color=PALETTE["tier2"],lw=2.5,
        label=f"Tier 2 Hardware  (CAPEX ${T2_CAPEX/1e3:.0f}K + ${t2_mo_opex:,.0f}/mo OPEX)")
ax.plot(months,cloud_cum/1e3,color=PALETTE["cloud"],lw=2.5,
        label=f"Cloud-Native     (migration ${MIG_COST/1e3:.0f}K + ${cloud_mo:,.0f}/mo)")

cloud_best_cum  = MIG_COST*0.8 + cloud_mo*0.6  * months
cloud_worst_cum = MIG_COST*1.2 + cloud_mo*1.20 * months
ax.fill_between(months,cloud_best_cum/1e3,cloud_worst_cum/1e3,
                color=PALETTE["cloud"],alpha=0.12,label="Cloud sensitivity ±20%")

diff=hw_cum-cloud_cum
cross=np.argwhere(np.diff(np.sign(diff))).flatten()
if len(cross):
    xc=cross[0]
    ax.fill_between(months[xc:],hw_cum[xc:]/1e3,cloud_cum[xc:]/1e3,
                    color=PALETTE["savings"],alpha=0.25,label="Cloud saving region")
    ax.axvline(months[xc],color=PALETTE["accent"],ls="--",lw=1.8)
    ax.annotate(f"Break-even: Month {months[xc]}",
                xy=(months[xc],cloud_cum[xc]/1e3),
                xytext=(months[xc]+2,cloud_cum[xc]/1e3+20),
                fontsize=9,color=PALETTE["accent"],
                arrowprops=dict(arrowstyle="->",color=PALETTE["accent"]))
ax.set_xlabel("Months since deployment"); ax.set_ylabel("Cumulative Cost (USD thousands)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:.0f}K"))
ax.legend(fontsize=9); ax.set_xlim(0,60)
plt.tight_layout()
fig.savefig(FIG_DIR/"breakeven_analysis.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 2 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 3 — AUTOSCALING SAVINGS
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 3 ---")
fig,(ax1,ax2,ax3)=plt.subplots(1,3,figsize=(15,5))
fig.suptitle("HPA Autoscaling Economic Impact — Phase 6 Data",fontsize=13,fontweight="bold")

ax1.hist(replica_dist,bins=[0.5,1.5,2.5,3.5,4.5,5.5],
         color=PALETTE["cloud"],edgecolor="white",rwidth=0.8,alpha=0.85)
ax1.axvline(HPA_MEAN,color=PALETTE["accent"],ls="--",lw=2,label=f"Mean={HPA_MEAN:.2f}")
ax1.set_xlabel("UPF Replicas"); ax1.set_ylabel("Frequency"); ax1.set_xticks([1,2,3,4,5])
ax1.set_title("UPF Replica Distribution\n(Phase 6 HPA, simulated)"); ax1.legend(fontsize=9)

mo_fix=[FIXED_R*T3_HR*24*30.44]*12
mo_hpa=[HPA_R  *T3_HR*24*30.44]*12
x12=np.arange(12)
ax2.bar(x12-0.2,mo_fix,0.4,label=f"Fixed ({FIXED_R} replicas)",color=PALETTE["tier2"],alpha=0.85)
ax2.bar(x12+0.2,mo_hpa,0.4,label=f"HPA  ({HPA_R} avg)",        color=PALETTE["cloud"],alpha=0.85)
ax2.set_xticks(x12); ax2.set_xticklabels([f"M{i+1}" for i in range(12)],fontsize=8)
ax2.set_ylabel("Monthly Cost (USD)"); ax2.set_title("Fixed vs HPA Monthly Cost")
ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:.0f}"))
ax2.legend(fontsize=9)

cum_sav=[ann_sav*y for y in range(1,6)]
ax3.bar(range(1,6),cum_sav,color=PALETTE["savings"],alpha=0.85,edgecolor="white")
for yr,val in zip(range(1,6),cum_sav):
    ax3.text(yr,val+15,f"${val:,.0f}",ha="center",fontsize=9,fontweight="bold")
ax3.set_xlabel("Year"); ax3.set_ylabel("Cumulative Savings (USD)")
ax3.set_title(f"5-Year HPA Savings ({pct_red:.0f}% reduction)")
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
plt.tight_layout()
fig.savefig(FIG_DIR/"autoscaling_savings.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 3 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 4 — TCO COMPARISON
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 4 ---")
fig,ax=plt.subplots(figsize=(10,7))
ax.set_title("5-Year TCO Component Breakdown",fontsize=13,fontweight="bold")
x=np.arange(3); w=0.55
capex_v =[T1_CAPEX*2,         T2_CAPEX*2,       MIG_COST]
maint_v =[t1_ann_maint*5,     t2_ann_maint*5,   0]
ops_v   =[T1_OPS*5,           T2_OPS*5,         0]
fac_v   =[T1_DC*5,            T2_DC*5,          0]
csvc_v  =[0,                  0,                CLOUD_5YR-MIG_COST]

COMP_COLORS=["#1f4e79","#2e75b6","#70ad47","#ed7d31","#2e8b57"]
COMP_LABELS=["CAPEX (hardware+refresh)","Maintenance (15%/yr)","Operations (staff)",
             "Facilities (DC)","Cloud Services (AWS)"]
bot=np.zeros(3)
for vals,col,lbl in zip([capex_v,maint_v,ops_v,fac_v,csvc_v],COMP_COLORS,COMP_LABELS):
    ax.bar(x,vals,w,bottom=bot,label=lbl,color=col,alpha=0.88); bot+=np.array(vals)
for i,t in enumerate([T1_5YR,T2_5YR,CLOUD_5YR]):
    ax.text(i,t+20000,f"${t/1e3:.0f}K",ha="center",fontsize=10,fontweight="bold",color=PALETTE["accent"])
ax.set_xticks(x); ax.set_xticklabels(["Tier 1\nHardware","Tier 2\nHardware","Cloud-Native\n(24/7 prod)"],fontsize=11)
ax.set_ylabel("5-Year Total Cost (USD)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v/1e6:.1f}M" if v>=1e6 else f"${v/1e3:.0f}K"))
ax.legend(fontsize=9,loc="upper right")
plt.tight_layout()
fig.savefig(FIG_DIR/"tco_comparison.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 4 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 5 — TORNADO CHART
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 5 ---")
params=list(tornado.keys())
lows =[v[0]-CLOUD_5YR for v in tornado.values()]
highs=[v[1]-CLOUD_5YR for v in tornado.values()]
rngs =[abs(h-l) for h,l in zip(highs,lows)]
order=np.argsort(rngs)
ps=[params[i] for i in order]; ls=[lows[i] for i in order]; hs=[highs[i] for i in order]

fig,ax=plt.subplots(figsize=(10,6))
ax.set_title("Sensitivity (Tornado) Chart — 5-Year Cloud TCO Deviation from Base",fontsize=13,fontweight="bold")
y=np.arange(len(ps))
ax.barh(y,hs,left=0,color=PALETTE["accent"],alpha=0.75,label="Higher cost")
ax.barh(y,ls,left=0,color=PALETTE["cloud"], alpha=0.75,label="Lower cost")
ax.axvline(0,color="black",lw=1.2)
ax.set_yticks(y); ax.set_yticklabels(ps,fontsize=10)
ax.set_xlabel("Δ vs Base Case 5-yr TCO (USD)")
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"+${v/1e3:.0f}K" if v>0 else f"-${abs(v)/1e3:.0f}K"))
ax.legend(fontsize=9)
ax.text(0.98,0.02,f"Base: ${CLOUD_5YR/1e3:.0f}K",transform=ax.transAxes,ha="right",fontsize=9,color=PALETTE["neutral"])
plt.tight_layout()
fig.savefig(FIG_DIR/"sensitivity_analysis.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 5 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 6 — AI ROI
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 6 ---")
fig,axes=plt.subplots(1,2,figsize=(13,6))
fig.suptitle("AI/ML Economic Value — SageMaker + Bedrock Integration",fontsize=13,fontweight="bold")

xlbls=["Anomaly\nDetection","Traffic\nForecasting","QoS\nClassification","Total AI\nValue"]
xvals=[ANOMALY_VAL,FORECAST_VAL,QOS_VAL,AI_VAL_ANN]
ax6a=axes[0]
bars=ax6a.bar(range(4),xvals,color=[PALETTE["tier1"],PALETTE["tier2"],PALETTE["neutral"],PALETTE["savings"]],
              alpha=0.85,edgecolor="white")
ax6a.axhline(AI_COST_ANN,color=PALETTE["accent"],ls="--",lw=2,label=f"Total cost: ${AI_COST_ANN:,.0f}/yr")
for bar,val in zip(bars,xvals):
    ax6a.text(bar.get_x()+bar.get_width()/2,val+500,f"${val:,.0f}",ha="center",fontsize=9,fontweight="bold")
ax6a.set_xticks(range(4)); ax6a.set_xticklabels(xlbls,fontsize=9)
ax6a.set_ylabel("Annual Value (USD)")
ax6a.set_title("Value by AI Component vs Infrastructure Cost")
ax6a.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v/1e3:.0f}K"))
ax6a.legend(fontsize=9)

ax6b=axes[1]
pie_vals=[AI_COST_ANN, AI_VAL_ANN-AI_COST_ANN]
pie_lbls=[f"Cost\n${AI_COST_ANN:,.0f}",f"Net Gain\n${AI_VAL_ANN-AI_COST_ANN:,.0f}"]
wedges,_,autotxts=ax6b.pie(pie_vals,labels=pie_lbls,colors=[PALETTE["accent"],PALETTE["savings"]],
                            autopct="%1.0f%%",startangle=90,pctdistance=0.82,
                            wedgeprops={"edgecolor":"white","linewidth":2})
ax6b.text(0,0,f"ROI\n{AI_ROI:,.0f}%",ha="center",va="center",fontsize=16,fontweight="bold",color=PALETTE["tier1"])
ax6b.set_title(f"AI Investment ROI\n(Payback: {AI_PAYBACK:.1f} months)")
plt.tight_layout()
fig.savefig(FIG_DIR/"ai_roi.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 6 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 7 — SCALING COST CURVE
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 7 ---")
ue_arr=np.array([10,50,100,250,500,1000,2000,3000,5000])
cloud_per_ue = CLOUD_MO_FULL / ue_arr
hw_t2_per_ue = T2_MO_AMORT  / ue_arr
hw_t1_per_ue = (T1_5YR/(5*12)) / ue_arr

fig,ax=plt.subplots(figsize=(11,6))
ax.set_title("Cost per UE per Month — Economies of Scale",fontsize=13,fontweight="bold")
ax.loglog(ue_arr,cloud_per_ue,"o-",color=PALETTE["cloud"], lw=2.5,label="Cloud-Native (AWS)")
ax.loglog(ue_arr,hw_t2_per_ue,"s-",color=PALETTE["tier2"], lw=2.5,label="Tier 2 Hardware")
ax.loglog(ue_arr,hw_t1_per_ue,"^-",color=PALETTE["tier1"], lw=2.5,label="Tier 1 Hardware")
ax.axhline(ZIM_ARPU,color=PALETTE["accent"],ls="--",lw=1.5,label=f"Zimbabwe ARPU ${ZIM_ARPU}/mo")
cross_idx=np.argwhere(cloud_per_ue<hw_t2_per_ue).flatten()
if len(cross_idx):
    xc=ue_arr[cross_idx[0]]
    ax.axvline(xc,color=PALETTE["savings"],ls=":",lw=1.8)
    ax.annotate(f"Cloud cheaper\n>{xc} UEs",xy=(xc,cloud_per_ue[cross_idx[0]]),
                xytext=(xc*1.3,cloud_per_ue[cross_idx[0]]*3),fontsize=8.5,color=PALETTE["savings"],
                arrowprops=dict(arrowstyle="->",color=PALETTE["savings"]))
ax.set_xlabel("Number of User Equipment (UEs)")
ax.set_ylabel("Cost per UE per Month (USD)")
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{int(v):,}"))
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:.2f}"))
ax.legend(fontsize=9)
plt.tight_layout()
fig.savefig(FIG_DIR/"scaling_cost_curve.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 7 saved")

# ═══════════════════════════════════════════════════════════════════
# FIGURE 8 — AFRICAN MARKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("--- Generating Figure 8 ---")
fig,axes=plt.subplots(1,2,figsize=(14,6))
fig.suptitle("Zimbabwean Operator Business Case — Cloud-Native 5G SA Core",fontsize=13,fontweight="bold")

ax8a=axes[0]
tot_cloud_cum = MIG_COST + CLOUD_MO_FULL * months
ax8a.plot(months,tot_cloud_cum/1e3,color=PALETTE["accent"],lw=2.5,ls="--",
          label=f"Cloud cost (${MIG_COST/1e3:.0f}K + ${CLOUD_MO_FULL:.0f}/mo)")
cols_gr=[PALETTE["savings"],PALETTE["cloud"],PALETTE["tier2"]]
for (lbl,_),col in zip(GROWTH.items(),cols_gr):
    rate_str=lbl.split("(")[1].rstrip(")")
    ax8a.plot(months,cumrev[lbl]/1e3,color=col,lw=2,label=f"Revenue — {rate_str}")
    diff2=cumrev[lbl]-tot_cloud_cum
    be2=np.argwhere(diff2>0).flatten()
    if len(be2):
        bm=be2[0]
        ax8a.scatter(months[bm],tot_cloud_cum[bm]/1e3,color=col,s=90,zorder=5)
ax8a.set_xlabel("Month"); ax8a.set_ylabel("Cumulative (USD thousands)")
ax8a.set_title(f"Revenue vs Cost ({INIT_SUBS} initial subs, ARPU ${ZIM_ARPU}/mo)")
ax8a.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:.0f}K"))
ax8a.legend(fontsize=8.5)

ax8b=axes[1]
be_data={"Cloud-Native\n(on-demand)": BE_UES_CLOUD,
         "Cloud-Native\n(30% reserved)": math.ceil(CLOUD_MO_FULL*0.7/ZIM_ARPU),
         "Tier 2 Hardware\n(amortised)": BE_UES_HW}
xb=np.arange(3)
brs=ax8b.bar(xb,list(be_data.values()),
             color=[PALETTE["cloud"],PALETTE["savings"],PALETTE["tier2"]],alpha=0.88,edgecolor="white")
for bar,val in zip(brs,be_data.values()):
    ax8b.text(bar.get_x()+bar.get_width()/2,val+0.5,f"{val:,} UEs",ha="center",fontsize=10,fontweight="bold")
ax8b.set_xticks(xb); ax8b.set_xticklabels(list(be_data.keys()),fontsize=10)
ax8b.set_ylabel("Minimum Subscribers for Cost Recovery")
ax8b.set_title(f"Break-Even Subscriber Count\n@ ARPU ${ZIM_ARPU}/month")
ax8b.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{int(v):,}"))
plt.tight_layout()
fig.savefig(FIG_DIR/"african_market_analysis.png",dpi=DPI,bbox_inches="tight"); plt.close()
print("   Fig 8 saved")

# ═══════════════════════════════════════════════════════════════════
# SAVE SUMMARY JSON
# ═══════════════════════════════════════════════════════════════════
summary={
    "generated":"2026-05-30",
    "actual_7day_spend_usd": ACTUAL_SPEND,
    "tier1_5yr_tco": round(T1_5YR),
    "tier2_5yr_tco": round(T2_5YR),
    "cloud_5yr_tco_full_prod": round(CLOUD_5YR),
    "cloud_daily_production": CLOUD_DAILY,
    "tco_reduction_vs_tier1_pct": round((1-CLOUD_5YR/T1_5YR)*100,1),
    "tco_reduction_vs_tier2_pct": round((1-CLOUD_5YR/T2_5YR)*100,1),
    "hpa_annual_savings_usd": round(ann_sav,2),
    "hpa_5yr_savings_usd": round(fyr_sav,2),
    "hpa_pct_reduction": round(pct_red,1),
    "ai_roi_pct": round(AI_ROI),
    "ai_payback_months": round(AI_PAYBACK,1),
    "ai_annual_value_usd": round(AI_VAL_ANN),
    "ai_annual_cost_usd": round(AI_COST_ANN,2),
    "breakeven_months_base": round(be_base,1),
    "breakeven_months_best": round(be_best,1),
    "breakeven_months_worst": round(be_worst,1),
    "co2_saved_tonnes_per_year": round(CO2_SAVED_T,1),
    "carbon_savings_usd_per_year": round(CARBON_VAL),
    "breakeven_ues_cloud": BE_UES_CLOUD,
    "breakeven_ues_hardware": BE_UES_HW,
    "network_slicing_savings": round(SLICE_SAV),
}
with open(BASE_DIR/"analysis_summary.json","w") as f:
    json.dump(summary,f,indent=2)

print("\n" + "=" * 70)
print(f"All 8 figures saved to {FIG_DIR}")
print(f"Summary JSON: {BASE_DIR/'analysis_summary.json'}")
print("=" * 70)
