#!/usr/bin/env bash
# =============================================================================
# restore-and-deploy-nef.sh
# Run this after Docker Desktop restarts to restore the cluster context and
# deploy the NEF API layer.
#
# Usage:
#   bash ~/5g-project/scripts/restore-and-deploy-nef.sh
# =============================================================================
set -euo pipefail

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $*"; }
fail() { echo "[$(date '+%H:%M:%S')] ❌ $*" >&2; exit 1; }

log "Restoring kubeconfig from KinD cluster..."
kind get kubeconfig --name open5gs > ~/.kube/config
ok "kubeconfig restored"

log "Verifying cluster access..."
kubectl cluster-info | head -2
kubectl get nodes

log "Building and deploying NEF..."
bash "$(dirname "$0")/build-nef.sh"
