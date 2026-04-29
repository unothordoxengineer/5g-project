#!/usr/bin/env python3
"""
architecture_diagram.py — Phase 7
Generates ~/5g-project/docs/architecture.png

A publication-quality system architecture diagram showing all layers:
  RAN → 5G Core → Observability → AI/ML → Closed-Loop Automation → AWS (future)
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe
import numpy as np

OUT = os.path.join(os.path.dirname(__file__), 'architecture.png')

# ── Colour palette ────────────────────────────────────────────────────────────
C = dict(
    ran        = '#1565C0',   # deep blue
    core       = '#2E7D32',   # deep green
    obs        = '#E65100',   # deep orange
    aiml       = '#6A1B9A',   # deep purple
    loop       = '#AD1457',   # deep pink
    aws        = '#BF360C',   # burnt orange (future)
    k8s        = '#01579B',   # k8s blue
    arrow      = '#546E7A',
    bg_ran     = '#E3F2FD',
    bg_core    = '#E8F5E9',
    bg_obs     = '#FFF3E0',
    bg_aiml    = '#F3E5F5',
    bg_loop    = '#FCE4EC',
    bg_aws     = '#FBE9E7',
    bg_k8s     = '#E1F5FE',
    text_dark  = '#212121',
    text_light = '#FFFFFF',
    border     = '#90A4AE',
)

fig, ax = plt.subplots(1, 1, figsize=(20, 13))
ax.set_xlim(0, 20); ax.set_ylim(0, 13)
ax.axis('off')
fig.patch.set_facecolor('#F8F9FA')
ax.set_facecolor('#F8F9FA')

# ── Helper functions ──────────────────────────────────────────────────────────
def box(ax, x, y, w, h, facecolor, edgecolor, label, sublabel='',
        fontsize=9, labelsize=10, radius=0.25, alpha=0.92, zorder=2):
    patch = FancyBboxPatch((x, y), w, h,
                            boxstyle=f"round,pad=0.0,rounding_size={radius}",
                            facecolor=facecolor, edgecolor=edgecolor,
                            linewidth=1.5, zorder=zorder, alpha=alpha)
    ax.add_patch(patch)
    cx, cy = x + w/2, y + h/2
    ax.text(cx, cy + (0.12 if sublabel else 0), label,
            ha='center', va='center', fontsize=labelsize, fontweight='bold',
            color=C['text_dark'], zorder=zorder+1)
    if sublabel:
        ax.text(cx, cy - 0.18, sublabel,
                ha='center', va='center', fontsize=fontsize,
                color='#424242', style='italic', zorder=zorder+1)

def section_header(ax, x, y, w, h, color, title, fontsize=11):
    patch = FancyBboxPatch((x, y), w, h,
                            boxstyle="round,pad=0.0,rounding_size=0.18",
                            facecolor=color, edgecolor=color,
                            linewidth=0, zorder=3, alpha=0.95)
    ax.add_patch(patch)
    ax.text(x + w/2, y + h/2, title,
            ha='center', va='center', fontsize=fontsize, fontweight='bold',
            color='white', zorder=4)

def layer_bg(ax, x, y, w, h, color, label, zorder=1):
    patch = FancyBboxPatch((x, y), w, h,
                            boxstyle="round,pad=0.0,rounding_size=0.3",
                            facecolor=color, edgecolor=C['border'],
                            linewidth=1.0, zorder=zorder, alpha=0.5)
    ax.add_patch(patch)
    ax.text(x + 0.15, y + h - 0.22, label,
            ha='left', va='top', fontsize=8, color='#607D8B',
            fontstyle='italic', zorder=zorder+1)

def arrow(ax, x1, y1, x2, y2, color=C['arrow'], lw=1.8,
          style='->', bidirectional=False, label='', zorder=5):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                 arrowprops=dict(arrowstyle='->' if not bidirectional else '<->',
                                 color=color, lw=lw,
                                 connectionstyle='arc3,rad=0.0'),
                 zorder=zorder)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.12, label, ha='center', va='bottom',
                fontsize=7, color=color, zorder=zorder+1)

# ── Title ─────────────────────────────────────────────────────────────────────
ax.text(10, 12.6, 'Cloud-Native 5G SA Core — System Architecture',
        ha='center', va='center', fontsize=16, fontweight='bold',
        color=C['text_dark'])
ax.text(10, 12.25, 'Open5GS v2.7.2  ·  kind Kubernetes  ·  Phase 7  ·  HIT Final Year Project',
        ha='center', va='center', fontsize=10, color='#546E7A', style='italic')

# ════════════════════════════════════════════════════════════════════════════
# LAYER 1 — RAN (left column)
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 0.2, 8.2, 3.2, 3.6, C['bg_ran'], 'RAN / UE Simulator')
section_header(ax, 0.2, 11.4, 3.2, 0.4, C['ran'], 'Radio Access Network')

box(ax, 0.4, 10.5, 2.8, 0.7, 'white', C['ran'],
    'UERANSIM', 'UE + gNB simulator', fontsize=8)
box(ax, 0.4, 9.6, 1.3, 0.7, 'white', C['ran'],
    'UE ×200', 'sessions', fontsize=7, labelsize=9)
box(ax, 1.85, 9.6, 1.35, 0.7, 'white', C['ran'],
    'gNB', 'base station', fontsize=7, labelsize=9)
box(ax, 0.4, 8.5, 2.8, 0.8, C['bg_ran'], C['ran'],
    'N1/N2 Interfaces', 'registration + PDU session', fontsize=7, labelsize=8)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 2 — 5G Core (middle, large)
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 3.7, 5.9, 8.7, 5.9, C['bg_core'], '5G SA Core — Open5GS v2.7.2')
section_header(ax, 3.7, 11.4, 8.7, 0.4, C['core'], '5G Stand-Alone Core Network Functions')

# Control plane NFs
NF_CTRL = [
    ('AMF', 'access & mobility', 3.9, 10.3),
    ('SMF', 'session mgmt', 5.5, 10.3),
    ('UDM', 'unified data', 7.1, 10.3),
    ('AUSF', 'authentication', 8.7, 10.3),
    ('PCF', 'policy ctrl', 10.3, 10.3),
    ('NRF', 'NF registry', 3.9,  9.3),
    ('UDR', 'data repo',   5.5,  9.3),
    ('NSSF', 'slice select', 7.1, 9.3),
    ('BSF', 'binding',      8.7, 9.3),
    ('SCP', 'comm proxy',  10.3, 9.3),
]
for name, desc, nx, ny in NF_CTRL:
    box(ax, nx, ny, 1.4, 0.7, 'white', C['core'], name, desc, fontsize=6.5, labelsize=8.5)

# UPF — larger, important
box(ax, 5.0, 7.9, 5.5, 1.1, C['bg_core'], C['core'],
    'UPF  (User Plane Function)', 'GTP-U · HPA 1–5 replicas · CPU target 70%',
    fontsize=8.5, labelsize=10, radius=0.2)

# MongoDB
box(ax, 3.9, 7.9, 0.9, 1.1, 'white', C['core'], 'DB', 'MongoDB', fontsize=7, labelsize=8)

# Kubernetes layer
layer_bg(ax, 3.75, 6.1, 8.6, 1.55, C['bg_k8s'], 'Kubernetes (kind)')
box(ax, 3.9, 6.3, 2.5, 1.1, 'white', C['k8s'], 'HPA', 'UPF autoscaler\nmin=1 max=5', fontsize=7.5, labelsize=8.5)
box(ax, 6.6, 6.3, 2.3, 1.1, 'white', C['k8s'], 'Deployments', '14 NF pods\nopen5gs ns', fontsize=7.5, labelsize=8.5)
box(ax, 9.1, 6.3, 3.1, 1.1, 'white', C['k8s'], 'Control Plane', '3 worker nodes\nkind cluster', fontsize=7.5, labelsize=8.5)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Observability (right column, top)
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 12.7, 8.2, 7.0, 3.6, C['bg_obs'], 'Observability Stack')
section_header(ax, 12.7, 11.4, 7.0, 0.4, C['obs'], 'Monitoring & Observability')

box(ax, 12.9, 10.5, 3.1, 0.7, 'white', C['obs'], 'Prometheus', 'metrics scrape 15s', fontsize=7.5)
box(ax, 16.2, 10.5, 3.3, 0.7, 'white', C['obs'], 'Grafana', '4 dashboards · alerts', fontsize=7.5)
box(ax, 12.9, 9.6, 2.0, 0.7, 'white', C['obs'], 'kube-state', 'metrics', fontsize=7.5, labelsize=8)
box(ax, 15.1, 9.6, 2.0, 0.7, 'white', C['obs'], 'node-exporter', 'CPU/mem', fontsize=7, labelsize=8)
box(ax, 17.3, 9.6, 2.2, 0.7, 'white', C['obs'], 'AlertManager', 'alerts', fontsize=7.5)
box(ax, 12.9, 8.5, 6.6, 0.8, C['bg_obs'], C['obs'],
    'Prometheus HTTP API — PromQL queries every 30 s',
    fontsize=7.5, labelsize=8.5, radius=0.15)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 4 — AI / ML (middle-left, bottom half)
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 0.2, 2.0, 9.2, 3.6, C['bg_aiml'], 'AI / ML Analytics (Phase 5–7)')
section_header(ax, 0.2, 5.2, 9.2, 0.4, C['aiml'], 'AI/ML Model Serving — FastAPI')

box(ax, 0.4, 4.1, 2.8, 0.8, 'white', C['aiml'],
    'Isolation Forest', 'anomaly detection\nRecall 90.3% · FPR 3.4%', fontsize=7, labelsize=8.5)
box(ax, 3.4, 4.1, 2.8, 0.8, 'white', C['aiml'],
    'ARIMA(3,0,1)', 'UE load forecast\nMAPE 3.64%', fontsize=7, labelsize=8.5)
box(ax, 6.4, 4.1, 2.8, 0.8, 'white', C['aiml'],
    'k-Means (k=2)', 'state classify\nSilhouette 0.503', fontsize=7, labelsize=8.5)

box(ax, 0.4, 3.1, 8.8, 0.75, C['bg_aiml'], C['aiml'],
    'FastAPI Serving  ·  /predict/anomaly  ·  /predict/forecast  ·  /predict/cluster',
    fontsize=8, labelsize=8.5, radius=0.15)

box(ax, 0.4, 2.2, 4.1, 0.65, 'white', C['aiml'],
    'Models: IF · k-Means · ARIMA pkl', 'trained Phase 5 · joblib serialised',
    fontsize=6.5, labelsize=7.5)
box(ax, 4.7, 2.2, 4.5, 0.65, 'white', C['aiml'],
    'Docker → kind cluster', 'NodePort 30800 · readiness probe',
    fontsize=6.5, labelsize=7.5)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 5 — Closed-Loop (middle-right, bottom half)
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 9.6, 2.0, 7.5, 3.6, C['bg_loop'], 'Closed-Loop Automation (Phase 7)')
section_header(ax, 9.6, 5.2, 7.5, 0.4, C['loop'], 'Closed-Loop Control Engine')

box(ax, 9.8, 4.1, 7.1, 0.8, 'white', C['loop'],
    'Closed-Loop Engine (closed_loop.py)',
    'poll 30 s → detect → decide → act → log', fontsize=8, labelsize=8.5)

box(ax, 9.8, 3.1, 2.1, 0.75, 'white', C['loop'], 'DETECT',   'anomaly score', fontsize=7, labelsize=8.5)
box(ax, 12.1, 3.1, 2.2, 0.75, 'white', C['loop'], 'DECIDE',   'threshold rule', fontsize=7, labelsize=8.5)
box(ax, 14.5, 3.1, 2.1, 0.75, 'white', C['loop'], 'ACT',      'kubectl scale', fontsize=7, labelsize=8.5)
box(ax, 9.8, 2.2, 6.8, 0.65, 'white', C['loop'],
    'Event log: closed_loop.log  ·  Kubernetes Deployment (always-on)',
    fontsize=7, labelsize=7.5)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 6 — AWS (future) — bottom strip
# ════════════════════════════════════════════════════════════════════════════
layer_bg(ax, 0.2, 0.2, 19.6, 1.55, C['bg_aws'], 'AWS Cloud (Phase 8 — Future)')
section_header(ax, 0.2, 1.55, 3.5, 0.3, C['aws'], 'AWS EKS', fontsize=9)
section_header(ax, 3.9, 1.55, 3.5, 0.3, C['aws'], 'EC2 (t3.medium)', fontsize=9)
section_header(ax, 7.6, 1.55, 3.5, 0.3, C['aws'], 'CloudWatch', fontsize=9)
section_header(ax, 11.3, 1.55, 3.5, 0.3, C['aws'], 'ECR Registry', fontsize=9)
section_header(ax, 15.0, 1.55, 4.6, 0.3, C['aws'], 'AWS Auto Scaling Group', fontsize=9)

for lx, lbl in [(0.2,'EKS cluster'),(3.9,'worker nodes'),(7.6,'monitoring'),(11.3,'images'),(15.0,'HPA cloud')]:
    ax.text(lx + (3.5 if lx < 14 else 4.6)/2, 0.95, lbl,
            ha='center', va='center', fontsize=7.5, color='#6D4C41', style='italic')

ax.text(10, 0.35, '← Plug-in AWS credentials to migrate kind → EKS with zero code changes →',
        ha='center', va='center', fontsize=8, color='#8D6E63', style='italic')

# ════════════════════════════════════════════════════════════════════════════
# ARROWS  (data flow)
# ════════════════════════════════════════════════════════════════════════════

# RAN → Core (N1/N2)
arrow(ax, 3.4, 9.85, 3.7+0.05, 9.85, color=C['ran'], lw=2.2, label='N1/N2')

# Core UPF → Observability scrape
arrow(ax, 12.4, 8.5, 12.7, 9.0, color=C['obs'], lw=1.8, label='scrape')

# Prometheus → Closed-loop engine
arrow(ax, 14.2, 8.5, 13.0, 5.2+0.3, color=C['loop'], lw=1.8, label='PromQL')

# Observability → AI/ML (metrics export)
arrow(ax, 9.1, 8.35, 8.9, 5.6+0.3, color=C['aiml'], lw=1.6, label='CSV/API')

# FastAPI → Closed-loop (predictions)
arrow(ax, 9.2, 3.5, 9.6, 3.55, color=C['loop'], lw=2.0,
      bidirectional=True, label='HTTP')

# Closed-loop → k8s HPA (kubectl scale)
arrow(ax, 16.6, 3.1, 9.8+5.5/2, 7.4, color=C['loop'], lw=2.0, label='kubectl scale')

# CI/CD label
ax.text(10, 12.0, '', ha='center')  # placeholder

# ── GitHub Actions badge ──
box(ax, 16.5, 11.8, 3.3, 0.5, '#24292E', '#24292E',
    'GitHub Actions CI/CD', 'build → test → push → log', fontsize=6.5, labelsize=7.5)
ax.annotate('', xy=(16.5, 12.05), xytext=(16.0, 11.4),
             arrowprops=dict(arrowstyle='->', color='#24292E', lw=1.3), zorder=5)

# ── Legend ────────────────────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(color=C['ran'],  label='RAN / UERANSIM'),
    mpatches.Patch(color=C['core'], label='5G Core (Open5GS)'),
    mpatches.Patch(color=C['obs'],  label='Observability'),
    mpatches.Patch(color=C['aiml'], label='AI/ML Serving'),
    mpatches.Patch(color=C['loop'], label='Closed-Loop Engine'),
    mpatches.Patch(color=C['aws'],  label='AWS (future)'),
    mpatches.Patch(color=C['k8s'],  label='Kubernetes'),
]
ax.legend(handles=legend_items, loc='lower right',
          bbox_to_anchor=(0.995, 0.005), ncol=7,
          fontsize=8, framealpha=0.9,
          title='Component Key', title_fontsize=8)

plt.tight_layout(pad=0.3)
fig.savefig(OUT, dpi=150, bbox_inches='tight', facecolor='#F8F9FA')
plt.close(fig)
print(f"Architecture diagram saved → {OUT}")
