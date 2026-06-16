"""
ML Pipeline diagram — Prometheus metrics → feature extraction →
4 models → ensemble decisions → closed-loop action → HPA.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

OUT = "/Users/nigelkadzunga/5g-project/docs/figures/ml_pipeline"

C = {
    "bg":    "#0D1117",
    "panel": "#161B22",
    "data":  "#1F6FEB",
    "feat":  "#2EA043",
    "model": "#A371F7",
    "ens":   "#D29922",
    "act":   "#F78166",
    "hpa":   "#3FB950",
    "arrow": "#58A6FF",
    "dim":   "#8B949E",
    "white": "#E6EDF3",
    "sub":   "#8B949E",
}

def rbox(ax, x, y, w, h, color, lines, fontsize=8.5):
    ax.add_patch(FancyBboxPatch(
        (x - w/2, y - h/2), w, h,
        boxstyle="round,pad=0,rounding_size=0.2",
        linewidth=2, edgecolor=color, facecolor=color + "25", zorder=3,
    ))
    total = len(lines)
    for i, line in enumerate(lines):
        dy = (total - 1) * 0.13 / 2 - i * 0.13
        bold = (i == 0)
        ax.text(x, y + dy, line, ha="center", va="center",
                fontsize=fontsize if bold else fontsize - 1.5,
                fontweight="bold" if bold else "normal",
                color=C["white"] if bold else C["dim"], zorder=4)

def arrow(ax, x0, y0, x1, y1, label="", color=None, lw=1.6, rad=0.0):
    color = color or C["arrow"]
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                connectionstyle=f"arc3,rad={rad}",
                                mutation_scale=12),
                zorder=5)
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2 + 0.08
        ax.text(mx, my, label, ha="center", fontsize=6.5, color=color,
                style="italic", zorder=6)

fig, ax = plt.subplots(figsize=(20, 9))
fig.patch.set_facecolor(C["bg"])
ax.set_facecolor(C["bg"])
ax.set_xlim(0, 20); ax.set_ylim(0, 9)
ax.axis("off")

ax.text(10, 8.6, "5G Core AI/ML Pipeline — From Metrics to Autonomous Action",
        ha="center", fontsize=13, fontweight="bold", color=C["white"])
ax.text(10, 8.2, "30-second poll interval  ·  DETECT → DECIDE → ACT",
        ha="center", fontsize=9, color=C["dim"])

# ── Stage 1: Data Ingestion ───────────────────────────────────────────────────
rbox(ax, 1.5, 5.5, 2.2, 1.0, C["data"],
     ["Prometheus", "22 targets · 2.66 GB", "30s scrape interval"], 9)
rbox(ax, 1.5, 3.8, 2.2, 1.0, C["data"],
     ["AMP Remote", "Amazon Managed", "Prometheus"], 9)

arrow(ax, 2.6, 5.5, 3.7, 5.5)
arrow(ax, 2.6, 3.8, 3.7, 3.8)

# ── Stage 2: Feature Extraction ──────────────────────────────────────────────
rbox(ax, 4.6, 5.5, 1.9, 1.0, C["feat"],
     ["Raw Metrics", "cpu_upf  cpu_amf", "upf_replicas  UEs"], 8.5)
rbox(ax, 4.6, 3.8, 1.9, 1.0, C["feat"],
     ["Feature Eng.", "14 NF CPU cols", "5 scalar cols  →  19"], 8.5)
rbox(ax, 4.6, 2.1, 1.9, 1.0, C["feat"],
     ["Preprocessing", "StandardScaler", "PCA  (k-Means)"], 8.5)

arrow(ax, 5.55, 5.5, 6.55, 5.5)
arrow(ax, 5.55, 3.8, 6.55, 3.8)
arrow(ax, 4.6, 4.3, 4.6, 3.3)
arrow(ax, 4.6, 3.3, 4.6, 2.6, label="→ k-Means path")

# Stage label
ax.text(4.6, 7.0, "② Feature\nExtraction", ha="center", fontsize=8,
        color=C["feat"], fontweight="bold")

# ── Stage 3: Four Models ──────────────────────────────────────────────────────
ax.text(9.0, 7.0, "③ ML Models", ha="center", fontsize=8,
        color=C["model"], fontweight="bold")

# IsolationForest
rbox(ax, 7.7, 6.5, 2.1, 1.3, C["model"],
     ["Isolation Forest", "contamination=0.15",
      "Recall 93.3% ±8.2%", "THRESHOLD=0.5849"], 8)
# SARIMA+Prophet
rbox(ax, 10.3, 6.5, 2.1, 1.3, C["model"],
     ["SARIMA+Prophet", "Ensemble forecast",
      "MAPE 12.93%", "12-step ahead"], 8)
# k-Means
rbox(ax, 7.7, 4.5, 2.1, 1.3, C["model"],
     ["k-Means (k=2)", "silhouette=0.634",
      "ARI=0.997±0.002", "6 network states"], 8)
# SHAP
rbox(ax, 10.3, 4.5, 2.1, 1.3, C["model"],
     ["SHAP Explainer", "TreeExplainer",
      "upf_rep=0.962", "cpu_amf=0.856"], 8)

arrow(ax, 5.55, 5.5, 6.65, 6.5, label="3-feat")
arrow(ax, 5.55, 5.5, 6.65, 4.5, label="→ state")
arrow(ax, 5.55, 3.8, 9.25, 6.5, label="sessions[]", rad=-0.1)
arrow(ax, 5.55, 3.8, 9.25, 4.5, label="feature vec", rad=0.1)

# ── Stage 4: SageMaker Endpoints ─────────────────────────────────────────────
ax.text(9.0, 7.0, "③ ML Models", ha="center", fontsize=8,
        color=C["model"], fontweight="bold")

rbox(ax, 7.7, 2.5, 2.1, 0.8, C["ens"],
     ["anomaly-detector", "SageMaker BYOC", "scikit-learn 1.8.0"], 8)
rbox(ax, 10.3, 2.5, 2.1, 0.8, C["ens"],
     ["traffic-forecaster", "SageMaker BYOC", "ARIMA endpoint"], 8)

arrow(ax, 7.7, 4.88, 7.7, 2.9)
arrow(ax, 10.3, 4.88, 10.3, 2.9)

# ── Stage 5: Ensemble Decision ────────────────────────────────────────────────
rbox(ax, 12.5, 5.5, 2.2, 1.6, C["ens"],
     ["Ensemble Decision", "anom_score > 0.6?", "forecast > 150 UEs?",
      "state transition?", "Bedrock cascade"], 8.5)

arrow(ax, 8.75, 6.5, 11.4, 5.8)
arrow(ax, 11.35, 6.5, 11.4, 5.5)
arrow(ax, 8.75, 4.5, 11.4, 5.2)
arrow(ax, 8.75, 2.5, 11.4, 4.8, rad=-0.05)
arrow(ax, 11.35, 2.5, 11.4, 4.7, rad=0.05)

ax.text(12.5, 7.0, "④ Ensemble\nDecision", ha="center", fontsize=8,
        color=C["ens"], fontweight="bold")

# ── Stage 6: Closed-Loop Actions ─────────────────────────────────────────────
rbox(ax, 15.1, 6.5, 2.1, 1.0, C["act"],
     ["Scale UPF Up", "kubectl scale", "min=1  max=5  +1"], 8.5)
rbox(ax, 15.1, 5.0, 2.1, 1.0, C["act"],
     ["Bedrock Alert", "Claude Sonnet 4.6", "Root cause + plan"], 8.5)
rbox(ax, 15.1, 3.5, 2.1, 1.0, C["act"],
     ["Network Query", "Flask API /ask", "NLP interface"], 8.5)
rbox(ax, 15.1, 2.0, 2.1, 1.0, C["act"],
     ["Daily Report", "Bedrock summary", "8-hour digest"], 8.5)

arrow(ax, 13.6, 5.8, 14.05, 6.5)
arrow(ax, 13.6, 5.5, 14.05, 5.0)
arrow(ax, 13.6, 5.2, 14.05, 3.5)
arrow(ax, 13.6, 4.8, 14.05, 2.0, rad=0.05)

ax.text(15.1, 7.0, "⑤ Autonomous\nActions", ha="center", fontsize=8,
        color=C["act"], fontweight="bold")

# ── Stage 7: HPA Outcomes ────────────────────────────────────────────────────
rbox(ax, 18.3, 6.5, 2.0, 0.9, C["hpa"],
     ["HPA Scale-Up", "UPF replicas +1", "CPU 70% trigger"])
rbox(ax, 18.3, 5.0, 2.0, 0.9, C["hpa"],
     ["SLA Maintained", "p99 < 2 ms", "URLLC slice ok"])
rbox(ax, 18.3, 3.5, 2.0, 0.9, C["hpa"],
     ["Operator UI", "Query API", "6 endpoints"])
rbox(ax, 18.3, 2.0, 2.0, 0.9, C["hpa"],
     ["Audit Log", "structured JSON", "DETECT→DECIDE→ACT"])

arrow(ax, 16.15, 6.5, 17.3, 6.5, color=C["hpa"])
arrow(ax, 16.15, 5.0, 17.3, 5.0, color=C["hpa"])
arrow(ax, 16.15, 3.5, 17.3, 3.5, color=C["hpa"])
arrow(ax, 16.15, 2.0, 17.3, 2.0, color=C["hpa"])

ax.text(18.3, 7.0, "⑥ Outcomes", ha="center", fontsize=8,
        color=C["hpa"], fontweight="bold")

# ── stage labels bottom ───────────────────────────────────────────────────────
stages = [
    (1.5, "① Data\nIngestion"),
    (4.6, "② Feature\nExtraction"),
]
for x, lbl in stages:
    ax.text(x, 7.0, lbl, ha="center", fontsize=8,
            color=C["data"], fontweight="bold")

ax.text(10, 0.4,
        "Figure 3.2  ·  AI/ML Pipeline — Prometheus → Feature Engineering → "
        "ML Models → Ensemble → Closed-Loop → HPA",
        ha="center", fontsize=7.5, color=C["dim"], style="italic")

plt.tight_layout(pad=0)
fig.savefig(OUT + ".svg", format="svg", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
fig.savefig(OUT + ".png", format="png", dpi=150, bbox_inches="tight",
            facecolor=C["bg"])
plt.close(fig)
print(f"Saved {OUT}.svg + .png")
