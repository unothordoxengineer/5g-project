"""
AWS Deployment diagram — VPC → EKS → ECR → AMP → Grafana →
SageMaker → Bedrock → S3 → SNS with IRSA connections.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

OUT = "/Users/nigelkadzunga/5g-project/docs/figures/aws_deployment"

C = {
    "bg":     "#0D1117",
    "panel":  "#161B22",
    "vpc":    "#FF9900",
    "eks":    "#1F6FEB",
    "ecr":    "#F78166",
    "amp":    "#D29922",
    "sm":     "#A371F7",
    "bd":     "#3FB950",
    "iam":    "#58A6FF",
    "s3":     "#E6A817",
    "sns":    "#FF4444",
    "cw":     "#2EA043",
    "arrow":  "#8B949E",
    "arrowhi":"#58A6FF",
    "white":  "#E6EDF3",
    "dim":    "#8B949E",
    "border": "#30363D",
}

def rbox(ax, x, y, w, h, color, lines, fs=8.2, zorder=3):
    ax.add_patch(FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle="round,pad=0,rounding_size=0.25",
        linewidth=2, edgecolor=color, facecolor=color + "22",
        zorder=zorder,
    ))
    n = len(lines)
    for i, (txt, bold) in enumerate(lines):
        dy = (n - 1) * 0.17 / 2 - i * 0.17
        ax.text(x, y + dy, txt, ha="center", va="center",
                fontsize=fs if bold else fs - 1.5,
                fontweight="bold" if bold else "normal",
                color=C["white"] if bold else C["dim"], zorder=zorder+1)

def panel(ax, x, y, w, h, color, label, zorder=1, dash=False):
    ls = (5, 3) if dash else None
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0,rounding_size=0.5",
        linewidth=2.5, edgecolor=color, facecolor=color + "0A",
        zorder=zorder, linestyle="--" if dash else "-",
    )
    ax.add_patch(p)
    ax.text(x + 0.35, y + h - 0.25, label,
            fontsize=8.5, fontweight="bold", color=color,
            va="top", zorder=zorder+1)

def arr(ax, x0, y0, x1, y1, color=None, lw=1.5, rad=0.0, label="", bi=False):
    color = color or C["arrow"]
    style = "<|-|>" if bi else "-|>"
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                connectionstyle=f"arc3,rad={rad}",
                                mutation_scale=11),
                zorder=5)
    if label:
        mx, my = (x0+x1)/2, (y0+y1)/2
        ax.text(mx, my + 0.12, label, ha="center", fontsize=6,
                color=color, style="italic", zorder=6)

def irsa(ax, x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="<->", color=C["iam"], lw=1.2,
                                linestyle="dashed",
                                connectionstyle="arc3,rad=0.0",
                                mutation_scale=9),
                zorder=5)

fig, ax = plt.subplots(figsize=(22, 14))
fig.patch.set_facecolor(C["bg"])
ax.set_facecolor(C["bg"])
ax.set_xlim(0, 22); ax.set_ylim(0, 14)
ax.axis("off")

ax.text(11, 13.6, "AWS Cloud Deployment — 5G Core Infrastructure (us-east-1)",
        ha="center", fontsize=14, fontweight="bold", color=C["white"])
ax.text(11, 13.15,
        "EKS 1.29  ·  2 × t3.medium  ·  IRSA (no static credentials)  ·  $32.36 / 7-day pilot",
        ha="center", fontsize=9, color=C["dim"])

# ── VPC outer ────────────────────────────────────────────────────────────────
panel(ax, 0.4, 0.4, 21.2, 12.3, C["vpc"], "VPC  10.0.0.0/16  —  us-east-1", zorder=1)

# ── Public / Private subnets ──────────────────────────────────────────────────
panel(ax, 0.8, 0.7, 9.5, 11.5, C["eks"],  "Private Subnets  (AZ a + b)", zorder=2)
panel(ax, 11.0, 0.7, 10.2, 11.5, C["vpc"], "AWS Managed Services", zorder=2)

# ── EKS cluster ──────────────────────────────────────────────────────────────
panel(ax, 1.1, 1.0, 8.9, 11.0, C["eks"], "EKS Cluster  ·  Kubernetes 1.29", zorder=3)

# Control plane (managed)
rbox(ax, 3.0, 11.2, 3.5, 0.75, C["eks"],
     [("EKS Control Plane", True), ("AWS-managed  ·  HA", False)], zorder=4)

# Worker nodes
rbox(ax, 2.2, 9.8, 2.8, 0.9, C["eks"],
     [("Node 1", True), ("t3.medium", False), ("4 vCPU  8 GB", False)], zorder=4)
rbox(ax, 5.4, 9.8, 2.8, 0.9, C["eks"],
     [("Node 2", True), ("t3.medium", False), ("4 vCPU  8 GB", False)], zorder=4)

arr(ax, 2.2, 11.2, 2.2, 10.25, C["eks"])
arr(ax, 5.4, 11.2, 5.4, 10.25, C["eks"])

# Open5GS pods
NFS = [
    ("AMF", 1.5, 8.4), ("SMF", 2.8, 8.4), ("UPF", 4.1, 8.4),
    ("NRF", 5.4, 8.4), ("UDM", 6.7, 8.4), ("UDR", 8.0, 8.4),
    ("AUSF", 1.5, 7.3), ("PCF", 2.8, 7.3), ("BSF", 4.1, 7.3),
    ("NSSF", 5.4, 7.3), ("SCP", 6.7, 7.3),
]
for name, x, y in NFS:
    ax.add_patch(FancyBboxPatch(
        (x - 0.52, y - 0.28), 1.04, 0.56,
        boxstyle="round,pad=0,rounding_size=0.15",
        linewidth=1.2, edgecolor=C["eks"], facecolor=C["eks"]+"20", zorder=4,
    ))
    ax.text(x, y, name, ha="center", va="center",
            fontsize=7.5, fontweight="bold", color=C["white"], zorder=5)

# MongoDB
rbox(ax, 3.8, 6.1, 2.4, 0.8, C["ecr"],
     [("MongoDB", True), ("Subscriber DB", False), ("StatefulSet", False)], zorder=4)

# Prometheus in-cluster
rbox(ax, 7.0, 6.1, 2.0, 0.8, C["amp"],
     [("Prometheus", True), ("in-cluster", False), ("22 targets", False)], zorder=4)

# Fluent Bit / cAdvisor
rbox(ax, 3.8, 5.0, 2.0, 0.75, C["cw"] if False else C["dim"],
     [("cAdvisor", True), ("container metrics", False)], zorder=4)
rbox(ax, 6.5, 5.0, 2.4, 0.75, C["cw"] if False else C["dim"],
     [("kube-state", True), ("-metrics", False)], zorder=4)

# Service Account / IRSA pod
rbox(ax, 5.0, 3.8, 4.0, 0.85, C["iam"],
     [("5G AI Service Account", True),
      ("IRSA annotations", False),
      ("sts:AssumeRoleWithWebIdentity", False)], zorder=4)

arr(ax, 5.0, 4.22, 5.0, 4.97, C["iam"])

# ECR
rbox(ax, 12.5, 11.5, 3.0, 0.9, C["ecr"],
     [("Amazon ECR", True), ("15 container images", False), ("Open5GS + ML serving", False)])
arr(ax, 9.7, 9.8, 11.2, 11.5, C["ecr"], label="pull images", rad=-0.05)

# AMP
rbox(ax, 16.5, 11.5, 3.0, 0.9, C["amp"],
     [("Amazon Managed\nPrometheus (AMP)", True), ("2.66 GB metrics", False)])
arr(ax, 8.0, 6.1, 11.2, 11.5, C["amp"], label="remote_write", rad=-0.08)

# Amazon Grafana
rbox(ax, 20.0, 11.5, 1.6, 0.9, C["amp"],
     [("Amazon\nGrafana", True), ("7 boards", False)])
arr(ax, 18.0, 11.5, 19.2, 11.5, C["amp"])

# SageMaker
rbox(ax, 12.5, 9.5, 3.5, 1.1, C["sm"],
     [("Amazon SageMaker", True),
      ("BYOC — scikit-learn 1.8.0", False),
      ("anomaly-detector  ·  traffic-forecaster", False),
      ("state-classifier", False)])
arr(ax, 5.0, 3.8, 11.2, 9.5, C["sm"], label="invoke_endpoint", rad=0.12)

# Bedrock
rbox(ax, 17.0, 9.5, 4.0, 1.1, C["bd"],
     [("Amazon Bedrock", True),
      ("Claude Sonnet 4.6 → Haiku 4.5", False),
      ("→ Nova Lite → Nova Micro", False),
      ("4-tier cascade  ·  score 77/100", False)])
arr(ax, 5.0, 3.8, 15.0, 9.5, C["bd"], label="Bedrock API", rad=0.2)

# S3
rbox(ax, 12.5, 7.8, 3.0, 0.9, C["s3"],
     [("Amazon S3", True), ("ML model artefacts", False), (".pkl  ·  training data", False)])
arr(ax, 12.5, 9.0, 12.5, 8.25, C["s3"])
arr(ax, 14.0, 9.5, 13.7, 8.25, C["s3"], rad=0.1)

# SNS
rbox(ax, 17.5, 7.8, 2.5, 0.9, C["sns"],
     [("Amazon SNS", True), ("Alert notifications", False), ("email  ·  pager", False)])
arr(ax, 17.0, 9.0, 17.5, 8.25, C["sns"])

# CloudWatch
rbox(ax, 20.5, 7.8, 1.8, 0.9, C["cw"],
     [("CloudWatch", True), ("Container\nInsights", False)])
arr(ax, 18.7, 7.8, 19.6, 7.8, C["cw"])

# IAM / IRSA  (central)
rbox(ax, 15.5, 6.0, 4.0, 1.1, C["iam"],
     [("IAM  /  IRSA", True),
      ("No static AWS credentials", False),
      ("Pod-level role assumption", False),
      ("sts.amazonaws.com  WebIdentity", False)])

irsa(ax, 6.0, 3.8, 13.5, 6.0)
ax.text(10.5, 4.8, "IRSA", fontsize=7, color=C["iam"],
        ha="center", style="italic", zorder=6)

arr(ax, 15.5, 6.55, 13.8, 9.0,  C["iam"])
arr(ax, 16.5, 6.55, 17.0, 9.0,  C["iam"])
arr(ax, 14.5, 6.0,  13.0, 8.25, C["iam"])
arr(ax, 17.5, 5.5,  17.5, 7.35, C["iam"])

# Cost badge
ax.add_patch(FancyBboxPatch((0.6, 0.55), 4.5, 0.55,
    boxstyle="round,pad=0,rounding_size=0.2",
    linewidth=1.5, edgecolor=C["vpc"], facecolor=C["vpc"]+"20", zorder=8))
ax.text(2.85, 0.82,
        "7-day pilot cost: $32.36  ·  TCO reduction vs on-prem: 99.4%  ·  Break-even: 70 subscribers",
        ha="center", va="center", fontsize=7.5, color=C["vpc"], fontweight="bold", zorder=9)

ax.text(11, 0.2,
        "Figure 3.4  ·  AWS Cloud Infrastructure — EKS Deployment with IRSA, "
        "AMP, SageMaker BYOC, Bedrock, S3, and SNS",
        ha="center", fontsize=7.5, color=C["dim"], style="italic")

# ── legend ────────────────────────────────────────────────────────────────────
legend = [
    (C["eks"],  "EKS / Compute"),
    (C["ecr"],  "Container Registry"),
    (C["amp"],  "Monitoring"),
    (C["sm"],   "ML / SageMaker"),
    (C["bd"],   "Bedrock AI"),
    (C["iam"],  "IAM / IRSA"),
    (C["s3"],   "Storage"),
    (C["sns"],  "Notifications"),
]
for i, (col, lbl) in enumerate(legend):
    lx = 5.5 + i * 2.2
    ax.add_patch(mpatches.Rectangle(
        (lx, 0.15), 0.4, 0.28,
        facecolor=col+"44", edgecolor=col, linewidth=1.2, zorder=8,
    ))
    ax.text(lx + 0.48, 0.29, lbl, fontsize=7, color=C["dim"],
            va="center", zorder=8)

plt.tight_layout(pad=0)
fig.savefig(OUT + ".svg", format="svg", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
fig.savefig(OUT + ".png", format="png", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
plt.close(fig)
print(f"Saved {OUT}.svg + .png")
