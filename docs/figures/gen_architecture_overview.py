"""
Architecture Overview — full system diagram.
UE→gNB→5GC NFs→MongoDB→Observability→ML→Closed-Loop→Bedrock→Query API
Two layers: Local kind cluster (left) + AWS EKS (right).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

FIG_W, FIG_H = 22, 14
OUT = "/Users/nigelkadzunga/5g-project/docs/figures/architecture_overview"

# ── colour palette ────────────────────────────────────────────────────────────
C = {
    "bg":       "#0D1117",
    "panel":    "#161B22",
    "border":   "#30363D",
    "ue":       "#1F6FEB",   # UE/RAN  – blue
    "core":     "#2EA043",   # 5GC NFs – green
    "db":       "#F78166",   # MongoDB – red-orange
    "obs":      "#D29922",   # Observ. – yellow
    "ml":       "#A371F7",   # ML      – purple
    "aws":      "#FF9900",   # AWS     – orange
    "arrow":    "#8B949E",
    "arrowhi":  "#58A6FF",
    "title":    "#E6EDF3",
    "label":    "#C9D1D9",
    "sub":      "#8B949E",
    "white":    "#FFFFFF",
}

def box(ax, x, y, w, h, color, label, sublabel="", radius=0.35, alpha=0.92):
    patch = FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=1.5, edgecolor=color, facecolor=color + "33",
        zorder=3, alpha=alpha,
    )
    ax.add_patch(patch)
    # inner fill
    patch2 = FancyBboxPatch(
        (x - w/2 + 0.04, y - h/2 + 0.04), w - 0.08, h - 0.08,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=0, facecolor=color + "18", zorder=3,
    )
    ax.add_patch(patch2)
    ax.text(x, y + (0.12 if sublabel else 0), label,
            ha="center", va="center", fontsize=8.5, fontweight="bold",
            color=C["white"], zorder=4)
    if sublabel:
        ax.text(x, y - 0.22, sublabel,
                ha="center", va="center", fontsize=6.5,
                color=C["sub"], zorder=4)

def panel(ax, x, y, w, h, title, color, zorder=1):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0,rounding_size=0.4",
        linewidth=2, edgecolor=color, facecolor=C["panel"],
        zorder=zorder, alpha=0.7,
    )
    ax.add_patch(p)
    ax.text(x + w/2, y + h + 0.05, title,
            ha="center", va="bottom", fontsize=10, fontweight="bold",
            color=color, zorder=zorder+1)

def arr(ax, x0, y0, x1, y1, color=None, style="->", lw=1.4):
    color = color or C["arrow"]
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, connectionstyle="arc3,rad=0.0"),
                zorder=5)

def arr_curved(ax, x0, y0, x1, y1, rad=0.25, color=None, lw=1.4):
    color = color or C["arrowhi"]
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=color,
                                lw=lw, connectionstyle=f"arc3,rad={rad}"),
                zorder=5)

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
fig.patch.set_facecolor(C["bg"])
ax.set_facecolor(C["bg"])
ax.set_xlim(0, 22); ax.set_ylim(0, 14)
ax.axis("off")

# ── background panels ─────────────────────────────────────────────────────────
panel(ax, 0.3, 0.5, 12.9, 13.0, "LOCAL  —  kind Kubernetes Cluster (M1 MacBook)", C["ue"])
panel(ax, 13.8, 0.5, 7.8, 13.0, "AWS  —  EKS us-east-1  (t3.medium × 2)", C["aws"])

# ── title ─────────────────────────────────────────────────────────────────────
ax.text(11, 13.65, "Cloud-Native 5G SA Core — System Architecture",
        ha="center", va="center", fontsize=15, fontweight="bold",
        color=C["title"])
ax.text(11, 13.2, "Open5GS v2.7.2  ·  UERANSIM v3.2.6  ·  Kubernetes 1.29  ·  AWS EKS",
        ha="center", va="center", fontsize=9, color=C["sub"])

# ── RAN layer ─────────────────────────────────────────────────────────────────
box(ax, 1.3, 10.5, 1.6, 0.7, C["ue"], "UE1", "IMSI-999…01")
box(ax, 1.3,  9.5, 1.6, 0.7, C["ue"], "UE2", "IMSI-999…02")
box(ax, 1.3,  8.5, 1.6, 0.7, C["ue"], "UE3", "IMSI-999…03")

box(ax, 3.3,  9.5, 1.6, 1.5, C["ue"], "gNB", "UERANSIM\n3.2.6  ·  NR")

# UE→gNB
for y in [10.5, 9.5, 8.5]:
    arr(ax, 2.1, y, 2.5, 9.5, C["ue"])

# ── 5GC Control Plane ─────────────────────────────────────────────────────────
box(ax, 5.7, 11.5, 1.7, 0.75, C["core"], "AMF", "Access & Mobility")
box(ax, 7.8, 11.5, 1.7, 0.75, C["core"], "SMF", "Session Mgmt")
box(ax, 5.7, 10.2, 1.7, 0.75, C["core"], "NRF", "NF Repository")
box(ax, 7.8, 10.2, 1.7, 0.75, C["core"], "AUSF", "Auth Server")
box(ax, 5.7,  9.0, 1.7, 0.75, C["core"], "UDM", "User Data Mgmt")
box(ax, 7.8,  9.0, 1.7, 0.75, C["core"], "UDR", "User Data Repo")
box(ax, 5.7,  7.8, 1.7, 0.75, C["core"], "PCF", "Policy Control")
box(ax, 7.8,  7.8, 1.7, 0.75, C["core"], "NSSF", "Slice Selection")
box(ax, 6.75, 6.5, 1.7, 0.75, C["core"], "BSF", "Binding Support")

# Data Plane
box(ax, 10.0, 9.5, 1.8, 1.0, C["ue"], "UPF", "User Plane Fn\nHPA: 1–5 pods")

# gNB → AMF / UPF
arr(ax, 4.1, 9.5, 4.8, 11.5, C["core"])
arr(ax, 4.1, 9.5, 9.1, 9.5,  C["ue"])   # N3

# SBI mesh (light)
for src, dst in [
    ((5.7,11.5),(7.8,11.5)),   # AMF-SMF
    ((5.7,11.5),(5.7,10.2)),   # AMF-NRF
    ((7.8,11.5),(7.8,10.2)),   # SMF-AUSF
    ((5.7,10.2),(7.8,10.2)),   # NRF-AUSF
    ((5.7,10.2),(5.7,9.0)),    # NRF-UDM
    ((5.7,9.0), (7.8,9.0)),    # UDM-UDR
    ((5.7,9.0), (5.7,7.8)),    # UDM-PCF
    ((7.8,9.0), (7.8,7.8)),    # UDR-NSSF
    ((7.8,11.5),(10.0,9.5)),   # SMF-UPF (N4)
]:
    ax.annotate("", xy=dst, xytext=src,
                arrowprops=dict(arrowstyle="-", color=C["border"], lw=1.0),
                zorder=2)

# MongoDB
box(ax, 10.0, 11.5, 1.8, 0.75, C["db"], "MongoDB", "NF subscriber\n+ config data")
arr(ax, 10.0, 11.12, 10.0, 10.0, C["db"])
arr(ax, 7.8, 9.0, 9.1, 11.5, C["db"])   # UDR→MongoDB

# ── Observability ─────────────────────────────────────────────────────────────
box(ax, 2.0, 5.8, 1.7, 0.75, C["obs"], "Prometheus", "AMP-compatible\n22 targets")
box(ax, 4.1, 5.8, 1.7, 0.75, C["obs"], "Grafana", "7 dashboards\nLive metrics")
box(ax, 2.0, 4.5, 1.7, 0.75, C["obs"], "cAdvisor", "Container\nmetrics")
box(ax, 4.1, 4.5, 1.7, 0.75, C["obs"], "kube-SM", "kube-state\n-metrics")

arr(ax, 2.0, 5.42, 2.0, 4.88, C["obs"])
arr(ax, 4.1, 5.42, 4.1, 4.88, C["obs"])
arr(ax, 2.85, 5.8, 3.25, 5.8, C["obs"])

# UPF/pods → Prometheus
arr_curved(ax, 10.0, 9.0, 2.85, 5.8, rad=-0.2, color=C["obs"])

# ── ML Pipeline ───────────────────────────────────────────────────────────────
box(ax, 6.5, 5.8, 1.7, 0.75, C["ml"], "IF Anomaly", "contamination=0.15\nrecall 93.3%")
box(ax, 8.5, 5.8, 1.7, 0.75, C["ml"], "ARIMA FC", "MAPE 12.93%\n12-step ahead")
box(ax, 6.5, 4.5, 1.7, 0.75, C["ml"], "k-Means", "k=2  sil=0.634\n6 states")
box(ax, 8.5, 4.5, 1.7, 0.75, C["ml"], "SHAP", "upf_rep=0.962\nfeature imp.")
box(ax, 7.5, 3.2, 1.8, 0.75, C["ml"], "Closed-Loop", "30s poll\nDETECT→ACT")

arr(ax, 4.85, 5.8, 5.62, 5.8, C["ml"])
arr(ax, 6.5, 5.42, 6.5, 4.88, C["ml"])
arr(ax, 8.5, 5.42, 8.5, 4.88, C["ml"])
arr(ax, 6.5, 4.12, 7.1, 3.58, C["ml"])
arr(ax, 8.5, 4.12, 7.9, 3.58, C["ml"])

# ── Network Query API (local) ─────────────────────────────────────────────────
box(ax, 10.5, 3.5, 1.9, 0.75, C["ue"], "Query API", "Flask REST\n6 endpoints")
arr(ax, 8.4, 3.2, 9.55, 3.5, C["ue"])

# Closed-loop → UPF (kubectl scale)
arr_curved(ax, 7.5, 2.82, 10.0, 9.0, rad=0.15, color=C["ml"])
ax.text(8.2, 6.0, "kubectl\nscale", fontsize=6.5, color=C["ml"],
        ha="center", rotation=85, zorder=6)

# ── AWS side ──────────────────────────────────────────────────────────────────
# AMP
box(ax, 15.5, 11.5, 2.0, 0.85, C["aws"], "Amazon\nManaged\nPrometheus", "2.66 GB\n22 targets")
box(ax, 18.5, 11.5, 2.0, 0.85, C["aws"], "Amazon\nGrafana", "Remote write\ndashboards")
arr(ax, 16.5, 11.5, 17.5, 11.5, C["aws"])

# ECR
box(ax, 15.5, 9.8, 2.0, 0.75, C["aws"], "ECR", "15 images\nOpen5GS built")

# SageMaker
box(ax, 18.5, 9.8, 2.0, 0.85, C["aws"], "SageMaker\nBYOC", "3 endpoints\nIF/ARIMA/KM")

# Bedrock
box(ax, 15.5, 8.1, 2.0, 0.85, C["aws"], "Amazon\nBedrock", "Claude Sonnet\nHaiku·Nova")
box(ax, 18.5, 8.1, 2.0, 0.75, C["aws"], "S3", "Model artefacts\n.pkl files")

# IAM / IRSA
box(ax, 17.0, 6.5, 2.0, 0.75, C["aws"], "IAM / IRSA", "Pod identity\nno static creds")

# SNS
box(ax, 15.5, 5.1, 2.0, 0.75, C["aws"], "SNS", "Alerts &\nnotifications")
box(ax, 18.5, 5.1, 2.0, 0.75, C["aws"], "CloudWatch", "Container\nInsights")

# AWS arrows
arr(ax, 16.5, 9.8, 17.5, 9.8, C["aws"])
arr(ax, 15.5, 9.42, 15.5, 8.53, C["aws"])
arr(ax, 18.5, 9.42, 18.5, 8.88, C["aws"])
arr(ax, 17.0, 6.12, 16.0, 5.48, C["aws"])
arr(ax, 17.0, 6.12, 18.5, 5.48, C["aws"])

# Cross-boundary: Prometheus → AMP (remote_write)
arr_curved(ax, 2.85, 5.43, 14.5, 11.5, rad=-0.08, color=C["obs"], lw=1.8)
ax.text(8.5, 7.3, "remote_write", fontsize=7, color=C["obs"],
        ha="center", style="italic", zorder=6)

# Closed-loop → Bedrock
arr_curved(ax, 8.4, 3.2, 14.5, 8.5, rad=-0.1, color=C["aws"], lw=1.8)
ax.text(11.5, 4.5, "Bedrock API", fontsize=7, color=C["aws"],
        ha="center", style="italic", zorder=6)

# Closed-loop → SageMaker
arr_curved(ax, 8.4, 3.5, 17.5, 9.4, rad=-0.05, color=C["ml"], lw=1.8)
ax.text(13.5, 5.5, "SageMaker\ninvoke", fontsize=7, color=C["ml"],
        ha="center", style="italic", zorder=6)

# Query API → Bedrock
arr_curved(ax, 11.45, 3.5, 14.5, 8.1, rad=0.15, color=C["aws"], lw=1.2)

# ── legend ────────────────────────────────────────────────────────────────────
legend_items = [
    (C["ue"],   "UE / RAN / Control"),
    (C["core"], "5GC Network Functions"),
    (C["db"],   "Data Store"),
    (C["obs"],  "Observability"),
    (C["ml"],   "ML / AI"),
    (C["aws"],  "AWS Managed Services"),
]
for i, (c, label) in enumerate(legend_items):
    lx = 0.6 + i * 3.5
    ax.add_patch(mpatches.Rectangle((lx, 0.55), 0.45, 0.30,
                 facecolor=c+"55", edgecolor=c, linewidth=1.2, zorder=6))
    ax.text(lx + 0.55, 0.70, label, fontsize=7.5, color=C["label"],
            va="center", zorder=6)

ax.text(11, 0.2, "Figure 3.1  ·  Cloud-Native 5G SA Core — Full System Architecture",
        ha="center", fontsize=8, color=C["sub"], style="italic")

plt.tight_layout(pad=0)
fig.savefig(OUT + ".svg", format="svg", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
fig.savefig(OUT + ".png", format="png", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
plt.close(fig)
print(f"Saved {OUT}.svg + .png")
