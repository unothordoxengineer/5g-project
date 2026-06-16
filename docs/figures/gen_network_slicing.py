"""
Network Slicing diagram — 3 slices: eMBB / mMTC / URLLC
with UEs, SST, DNN, IP pools, QoS, and SLA indicators.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

OUT = "/Users/nigelkadzunga/5g-project/docs/figures/network_slicing"

C = {
    "bg":    "#0D1117",
    "panel": "#161B22",
    "embb":  "#1F6FEB",
    "mmtc":  "#2EA043",
    "urllc": "#F78166",
    "nf":    "#A371F7",
    "infra": "#30363D",
    "arrow": "#8B949E",
    "white": "#E6EDF3",
    "dim":   "#8B949E",
    "ok":    "#3FB950",
    "warn":  "#D29922",
}

def rbox(ax, x, y, w, h, color, lines, fs=8.5, alpha=0.85):
    ax.add_patch(FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle="round,pad=0,rounding_size=0.25",
        linewidth=2, edgecolor=color, facecolor=color + "22", zorder=3,
        alpha=alpha,
    ))
    n = len(lines)
    for i, (txt, bold, fc) in enumerate(lines):
        dy = (n - 1) * 0.16 / 2 - i * 0.16
        ax.text(x, y + dy, txt, ha="center", va="center",
                fontsize=fs if bold else fs - 1.5,
                fontweight="bold" if bold else "normal",
                color=fc or (C["white"] if bold else C["dim"]), zorder=4)

def hpanel(ax, x, y, w, h, color, title):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0,rounding_size=0.3",
        linewidth=2.5, edgecolor=color, facecolor=color + "12", zorder=1,
    ))
    ax.text(x + w / 2, y + h + 0.07, title,
            ha="center", fontsize=10.5, fontweight="bold", color=color, zorder=2)

def arr(ax, x0, y0, x1, y1, color, lw=1.6, rad=0.0):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                connectionstyle=f"arc3,rad={rad}",
                                mutation_scale=11),
                zorder=5)

def badge(ax, x, y, text, color):
    ax.add_patch(FancyBboxPatch(
        (x - 0.55, y - 0.2), 1.1, 0.4,
        boxstyle="round,pad=0,rounding_size=0.2",
        linewidth=1.2, edgecolor=color, facecolor=color + "30", zorder=6,
    ))
    ax.text(x, y, text, ha="center", va="center",
            fontsize=7, fontweight="bold", color=color, zorder=7)

fig, ax = plt.subplots(figsize=(20, 12))
fig.patch.set_facecolor(C["bg"])
ax.set_facecolor(C["bg"])
ax.set_xlim(0, 20); ax.set_ylim(0, 12)
ax.axis("off")

ax.text(10, 11.6, "5G Network Slicing — Three-Slice Architecture",
        ha="center", fontsize=14, fontweight="bold", color=C["white"])
ax.text(10, 11.15, "NSSF-driven slice selection  ·  Per-slice QoS policies  ·  Isolated data planes",
        ha="center", fontsize=9, color=C["dim"])

# ── Shared RAN / gNB ─────────────────────────────────────────────────────────
rbox(ax, 2.5, 8.5, 3.0, 5.5, C["nf"],
     [("gNB", True, None),
      ("UERANSIM v3.2.6", False, None),
      ("NR Radio", False, None),
      ("3 UEs connected", False, None),
      ("Slice-aware", False, None)], fs=9)

ax.text(2.5, 3.5, "Shared RAN\n(gNB)", ha="center", fontsize=8.5,
        fontweight="bold", color=C["nf"])

# ── UEs ──────────────────────────────────────────────────────────────────────
for i, (ue, y, col) in enumerate([("UE1", 10.0, C["embb"]),
                                   ("UE2",  8.5, C["mmtc"]),
                                   ("UE3",  7.0, C["urllc"])]):
    rbox(ax, 0.85, y, 1.3, 0.7, col,
         [(ue, True, None),
          ("IMSI-999…0" + str(i+1), False, None)], fs=8.5)
    arr(ax, 1.5, y, 1.95, [10.0, 8.5, 7.0][i], col)

# ── NSSF ──────────────────────────────────────────────────────────────────────
rbox(ax, 2.5, 5.5, 2.0, 0.8, C["nf"],
     [("NSSF", True, None), ("Slice Selection", False, None)], fs=8.5)
arr(ax, 2.5, 8.25, 2.5, 5.9, C["nf"], lw=1.2)

# ── Slice panels ─────────────────────────────────────────────────────────────
SLICES = [
    {
        "name": "eMBB  —  Enhanced Mobile Broadband",
        "color": C["embb"], "x": 4.5, "ue_y": 10.0,
        "sst": "SST=1", "dnn": "DNN: internet",
        "ip": "10.45.0.0/16",
        "ambr": "DL 100 Mbps  /  UL 50 Mbps",
        "5qi": "5QI=9 (Non-GBR)",
        "lat": "p99 ≈ 1.3 ms",
        "desc": "High throughput broadband\nstreaming & web access",
        "sla": "SLA: throughput ≥ 25 Mbps",
        "sla_ok": True,
        "load": "Load: 13.6%",
    },
    {
        "name": "mMTC  —  Massive Machine-Type Comms",
        "color": C["mmtc"], "x": 10.5, "ue_y": 8.5,
        "sst": "SST=2", "dnn": "DNN: iot",
        "ip": "10.46.0.0/16",
        "ambr": "DL 1 Mbps  /  UL 1 Mbps",
        "5qi": "5QI=9 (Non-GBR)",
        "lat": "p99 ≈ 1.4 ms",
        "desc": "IoT sensor networks\nhigh device density",
        "sla": "SLA: connectivity  ≥ 99.9%",
        "sla_ok": True,
        "load": "Load: 5.0%",
    },
    {
        "name": "URLLC  —  Ultra-Reliable Low-Latency",
        "color": C["urllc"], "x": 16.0, "ue_y": 7.0,
        "sst": "SST=3", "dnn": "DNN: urllc",
        "ip": "10.47.0.0/16",
        "ambr": "DL 10 Mbps  /  UL 5 Mbps",
        "5qi": "5QI=1 (GBR, delay-critical)",
        "lat": "p99 ≈ 1.3 ms",
        "desc": "Industrial automation\nmotion control / XR",
        "sla": "SLA: latency < 1 ms",
        "sla_ok": True,
        "load": "Load: 12.5%",
    },
]

for sl in SLICES:
    col = sl["color"]
    x   = sl["x"]
    hpanel(ax, x - 2.5, 1.0, 5.0, 9.5, col, sl["name"])

    # SST / DNN
    rbox(ax, x - 0.9, 9.8, 2.0, 0.75, col,
         [(sl["sst"], True, None), (sl["dnn"], False, None)], fs=8.5)
    rbox(ax, x + 1.5, 9.8, 1.8, 0.75, col,
         [("IP Pool", True, None), (sl["ip"], False, None)], fs=8.5)

    # AMBR / 5QI
    rbox(ax, x, 8.6, 4.5, 0.85, col,
         [("QoS Profile", True, None),
          (sl["ambr"], False, None),
          (sl["5qi"], False, None)], fs=8.5)

    # Latency
    rbox(ax, x - 1.1, 7.4, 2.0, 0.75, col,
         [("Latency", True, None), (sl["lat"], False, None)], fs=8.5)
    rbox(ax, x + 1.1, 7.4, 2.0, 0.75, col,
         [("Throughput", True, None), (sl["ambr"].split("/")[0].strip(), False, None)], fs=8)

    # SMF / UPF per slice
    rbox(ax, x, 5.8, 3.0, 1.2, C["nf"],
         [("SMF  +  UPF", True, None),
          ("N4 interface", False, None),
          ("Dedicated session", False, None),
          ("HPA: 1–5 replicas", False, None)], fs=8)

    # Description
    ax.text(x, 4.5, sl["desc"], ha="center", fontsize=8, color=C["dim"],
            style="italic", va="center")

    # SLA badge
    badge(ax, x - 0.6, 3.5, sl["sla"], C["ok"] if sl["sla_ok"] else C["warn"])
    badge(ax, x + 1.4, 3.5, sl["load"], col)

    # PDN gateway / internet
    rbox(ax, x, 2.1, 3.0, 0.75, col,
         [("DN Gateway", True, None), ("Internet / IoT / Industry", False, None)], fs=8)

    # Arrows
    arr(ax, 4.0, sl["ue_y"], sl["x"] - 2.45, 9.8, col, rad=-0.1)
    arr(ax, x, 9.42, x, 9.0,  col)
    arr(ax, x, 8.17, x, 6.4,  col)
    arr(ax, x, 5.4,  x, 4.8,  col)
    arr(ax, x, 4.2,  x, 3.7,  col)
    arr(ax, x, 3.3,  x, 2.48, col)

# ── Shared Core ──────────────────────────────────────────────────────────────
ax.add_patch(FancyBboxPatch((3.8, 1.4), 12.8, 0.5,
    boxstyle="round,pad=0,rounding_size=0.2",
    linewidth=1.5, edgecolor=C["nf"], facecolor=C["nf"] + "18", zorder=1))
ax.text(10.2, 1.65, "Shared 5GC Control Plane  —  AMF  ·  NRF  ·  UDM/UDR  ·  AUSF  ·  PCF  ·  BSF  ·  MongoDB",
        ha="center", fontsize=8, fontweight="bold", color=C["nf"], va="center", zorder=2)

ax.text(10, 0.5,
        "Figure 3.3  ·  5G Network Slicing — eMBB (SST=1) / mMTC (SST=2) / URLLC (SST=3) "
        "with Dedicated UPF and Per-Slice QoS",
        ha="center", fontsize=7.5, color=C["dim"], style="italic")

plt.tight_layout(pad=0)
fig.savefig(OUT + ".svg", format="svg", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
fig.savefig(OUT + ".png", format="png", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
plt.close(fig)
print(f"Saved {OUT}.svg + .png")
