# Security Architecture — Cloud-Native 5G Core

## 1. Overview

This document describes the security hardening applied to the Open5GS 5G Standalone
Core deployment on Kubernetes.  The model follows three concentric layers:

```
┌───────────────────────────────────────────────────────────────┐
│  Layer 3 — Identity & Authorisation (RBAC + ServiceAccounts)  │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │   Layer 2 — Network Segmentation (NetworkPolicies)        │ │
│ │ ┌───────────────────────────────────────────────────────┐ │ │
│ │ │  Layer 1 — Secrets Management (Kubernetes Secrets)    │ │ │
│ │ │               Open5GS NFs                             │ │ │
│ │ └───────────────────────────────────────────────────────┘ │ │
│ └───────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

| Layer | Mechanism | File |
|-------|-----------|------|
| Network segmentation | Kubernetes NetworkPolicy | `k8s/security/network-policies.yaml` |
| Secrets management | Kubernetes Secret (Opaque) | `k8s/security/secrets.yaml` |
| Identity & RBAC | ServiceAccount + Role + RoleBinding | `k8s/security/rbac.yaml` |

---

## 2. NetworkPolicy Rules

### 2.1 Default Deny All

```yaml
podSelector: {}   # matches every pod
policyTypes: [Ingress, Egress]
```

**Why:** Zero-trust baseline.  A 5G core carries subscriber PII (SUPI/IMSI,
authentication vectors) and must not allow lateral movement between NFs that
have no legitimate reason to communicate.  Explicitly permitting each required
flow forces the author to justify every traffic path.

### 2.2 Communication Matrix

The following matrix defines allowed flows.  `→` = initiates connection.

| Source | Destination | Port / Protocol | Reason |
|--------|-------------|-----------------|--------|
| Any NF | NRF | 80 TCP | NF registration, heartbeat, discovery |
| NRF | Any NF | 80 TCP | Push notifications / NF-status callbacks |
| gNB | AMF | 38412 SCTP | N2 NGAP — UE registration, handover |
| AMF | AUSF | 80 TCP | 5G-AKA authentication |
| AMF | UDM | 80 TCP | Subscriber profile fetch |
| AMF | PCF | 80 TCP | AM policy association |
| AMF | SMF | 80 TCP | PDU session creation |
| AMF | NSSF | 80 TCP | Slice selection |
| AMF | NRF | 80 TCP | NF discovery |
| SMF | UPF | 8805 UDP | N4 PFCP — session establishment |
| SMF | PCF | 80 TCP | SM policy association |
| SMF | UDM | 80 TCP | Subscriber session data |
| UPF | SMF | 8805 UDP | PFCP session reports |
| gNB | UPF | 2152 UDP | N3 GTP-U — user-plane traffic |
| UPF | 0.0.0.0/0 | any | N6 data plane to internet |
| UDR | MongoDB | 27017 TCP | Subscriber CRUD |
| UDM | UDR | 80 TCP | Unified Data access |
| PCF | UDR | 80 TCP | Policy data |
| BSF | UDR | 80 TCP | Binding data |
| Prometheus | Any NF | 9090 TCP | Metrics scraping |

**Why each restriction exists:**

- **MongoDB ← UDR only**: MongoDB holds subscriber credentials (K, OPc),
  SUPI/IMSI, and session records.  Direct access by AMF or SMF is never
  required — UDM/UDR abstract it.  Restricting to UDR alone limits the
  blast radius of a compromised NF.

- **UPF N6 exception only to non-RFC1918**: The UPF must forward subscriber
  data packets to the internet but must NOT reach other pods directly
  (that would bypass NetworkPolicies).  The `except` block keeps intra-cluster
  traffic blocked while allowing external forwarding.

- **AMF ↔ SMF/AUSF/UDM/PCF/NSSF only**: The AMF has the widest attack surface
  (it terminates NGAP from the RAN).  Limiting its egress to exactly the NFs it
  needs prevents a compromised AMF from reaching MongoDB or the UPF directly.

- **DNS egress for all**: kube-dns is required for service-name resolution
  (`nrf`, `amf`, etc.).  Without it every NF fails on startup.

### 2.3 CNI Enforcement — kindnet nfqueue

This cluster uses **kindnet** (KinD's default CNI).  Versions of kindnet
shipped with KinD ≥ 0.23 include a built-in NetworkPolicy controller that
enforces policies via **nfqueue** (Netfilter queue 101).

The enforcement path is:

```
nftables table inet kindnet-network-policies
  chain postrouting  (priority srcnat-5)
    ct state established,related → ACCEPT
    ip saddr @podips-v4          → QUEUE flags bypass to 101
  chain prerouting   (priority dstnat+5, i.e. after kube-proxy DNAT)
    ip daddr @podips-v4          → QUEUE flags bypass to 101
```

A userspace daemon evaluates each queued packet against the namespace's
NetworkPolicy objects and accepts or drops it.  Traffic between
non-pod IPs (e.g. kubelet probes from the node gateway `10.244.x.1`) is
**not** queued and bypasses policy evaluation.

**Practical consequence:** every pod that is subject to the `default-deny-all`
policy **must** have explicit Ingress and Egress rules, or all its traffic
will be silently dropped.  This was confirmed in Phase 8: new pods
(`ml-serving-api`, `closed-loop-engine`) deployed without NetworkPolicies
could not communicate with any other pod until `allow-ml-serving-api-ingress`
and `allow-closed-loop-egress` were added.

In a production environment (AKS, EKS, GKE, bare-metal), the cloud CNI
(Azure CNI + Calico, AWS VPC CNI, or Cilium) enforces NetworkPolicies natively
at the kernel data-plane level (eBPF or iptables), which is more performant
than nfqueue for high-throughput workloads.

---

## 3. Secrets Management

### 3.1 Current Approach

| Secret | Name | Contents |
|--------|------|----------|
| MongoDB credentials | `mongodb-credentials` | Root username + password + URI |
| NRF signing key | `nrf-api-key` | Future OAuth2 token signing |
| Subscriber-init creds | `subscriber-init-credentials` | Scoped MongoDB URI |

Secrets are stored as Kubernetes `Opaque` objects (base64-encoded, stored in
etcd).  The base64 encoding is **NOT encryption** — it is encoding only.

### 3.2 Integration with MongoDB

MongoDB currently runs without authentication (no `--auth` flag), matching the
existing `db_uri: mongodb://mongodb/open5gs` in UDR's config.  The
`secrets.yaml` file provides a reference implementation for enabling auth:

```bash
# Step 1 — backup existing data
kubectl exec -n open5gs mongodb-0 -- mongodump --out /tmp/dump
kubectl cp open5gs/mongodb-0:/tmp/dump ./mongodb-dump

# Step 2 — delete StatefulSet (keep PVC)
kubectl delete statefulset mongodb -n open5gs

# Step 3 — apply secrets and updated StatefulSet with --auth flag
kubectl apply -f k8s/security/secrets.yaml
kubectl patch statefulset mongodb -n open5gs ... # (see secrets.yaml annotations)

# Step 4 — restore
kubectl exec -n open5gs mongodb-0 -- mongorestore /tmp/dump
```

### 3.3 Production Hardening Recommendations

| Recommendation | Tool | Priority |
|----------------|------|----------|
| Encrypt Secrets at rest | etcd encryption config | High |
| External secrets management | HashiCorp Vault + vault-agent-injector | High |
| GitOps-safe secret storage | Bitnami Sealed Secrets or SOPS+age | High |
| Automatic credential rotation | Vault dynamic secrets | Medium |
| Secret scanning in CI | truffleHog / gitleaks | High |

### 3.4 What Is NOT in Git

The `secrets.yaml` file contains **example credentials** for demonstration.
In a real deployment:

- Never commit real credentials to git
- Use `git-secrets` or a pre-commit hook to block accidental commits
- Rotate any credentials that have ever been committed

---

## 4. Kubernetes RBAC Model

### 4.1 Principle of Least Privilege

Each NF gets a dedicated `ServiceAccount` with `automountServiceAccountToken: false`.
This means:

- No kube-apiserver credentials are injected into the pod filesystem
- A compromised NF container cannot enumerate or modify Kubernetes resources
- Each NF has a distinct identity for audit logging

```
NF Pod ──► ServiceAccount (nf-sa)
                │
                ├──► Role: configmap-reader  (get/list ConfigMaps)
                └──► [no other permissions]
```

### 4.2 ServiceAccount Inventory

| ServiceAccount | API Permissions | Token Mounted |
|----------------|-----------------|---------------|
| `nrf-sa` | configmap-reader | No |
| `amf-sa` | configmap-reader | No |
| `smf-sa` | configmap-reader | No |
| `upf-sa` | configmap-reader | No |
| `udr-sa` | configmap-reader, secret-reader (mongodb-credentials) | No |
| `udm-sa` | configmap-reader | No |
| `ausf-sa` | configmap-reader | No |
| `pcf-sa` | configmap-reader | No |
| `bsf-sa` | configmap-reader | No |
| `nssf-sa` | configmap-reader | No |
| `scp-sa` | configmap-reader | No |
| `mongodb-sa` | none | No |
| `gnb-sa` | none | No |
| `ue-sa` | none | No |
| `subscriber-init-sa` | none | No |
| `closed-loop-sa` | upf-scaler (patch upf Deployment), pod-reader | **Yes** |

### 4.3 Exception — Closed-Loop Engine

The ML autoscaler (`closed-loop-engine`) legitimately needs to scale the UPF
Deployment.  Its ServiceAccount (`closed-loop-sa`) has:

- `patch`/`update` on `apps/deployments` — **scoped to `upf` resource name only**
- `get`/`list`/`watch` on `pods` — read-only health monitoring

This is the most permissive account in the system, and its permissions are
still tightly scoped: it cannot modify any NF other than UPF, cannot read
Secrets, and cannot delete any resource.

### 4.4 Activating RBAC

The ServiceAccounts are created by applying `rbac.yaml`, but the NF Deployments
must also reference them.  To bind a ServiceAccount to an existing Deployment:

```bash
kubectl patch deployment amf -n open5gs \
  -p '{"spec":{"template":{"spec":{"serviceAccountName":"amf-sa"}}}}'
```

Or add to the Deployment manifest:
```yaml
spec:
  template:
    spec:
      serviceAccountName: amf-sa
      automountServiceAccountToken: false
```

---

## 5. What mTLS Would Add

The current deployment uses plaintext HTTP/2 for SBI (Service-Based Interface)
between NFs.  Mutual TLS (mTLS) would add:

### 5.1 Benefits

| Benefit | Mechanism |
|---------|-----------|
| NF identity verification | Each NF presents an X.509 certificate; peers reject unknown identities |
| In-transit encryption | TLS 1.3 encrypts all SBI messages (SUPI, AUTN, auth vectors) |
| Certificate-based authorisation | AMF certificate scoped to AMF functions only |
| Replay attack prevention | TLS record MAC + sequence numbers |

### 5.2 Implementation Design (not implemented)

```
Option A — Istio service mesh
  ├── Inject sidecar proxies alongside each NF container
  ├── Automatic mTLS between all sidecar pairs (PeerAuthentication: STRICT)
  ├── Certificate rotation every 24h via SPIFFE/SPIRE
  └── AuthorizationPolicy for L7 path-level control (e.g. /namf-comm/v1/*)

Option B — Open5GS native TLS
  ├── Configure server.tls in each NF's YAML (Open5GS v2.7+ supports this)
  ├── Generate per-NF certificates signed by a cluster CA
  ├── Mount certs via Secrets / cert-manager
  └── Requires cert-manager + a ClusterIssuer

Recommended path: Istio ambient mode (no sidecar injection needed)
  kubectl label namespace open5gs istio.io/dataplane-mode=ambient
```

### 5.3 3GPP Alignment

3GPP TS 33.501 §13.1 specifies TLS 1.2+ for SBI communications in production
5G networks.  mTLS with certificate-based NF authentication directly maps to
the NF-to-NF security requirements in TS 33.501 §13.3 (NF Service Consumer
authorisation).

---

## 6. Verification

### Apply all security resources

```bash
kubectl apply -f k8s/security/rbac.yaml
kubectl apply -f k8s/security/secrets.yaml
kubectl apply -f k8s/security/network-policies.yaml
```

### Verify NetworkPolicies are stored

```bash
kubectl get networkpolicy -n open5gs
# Expected: 20+ policies listed
```

### Verify NF communication is intact after applying policies

```bash
# Check all pods are Running
kubectl get pods -n open5gs

# UE should be registered (PDU session on uesimtun0)
kubectl logs -n open5gs deploy/ue | grep "PDU Session establishment is successful"

# AMF should show successful registrations
kubectl logs -n open5gs deploy/amf | grep "Registration"

# NRF should have all NFs registered
kubectl exec -n open5gs deploy/nrf -- \
  curl -s --http2-prior-knowledge http://localhost/nnrf-nfm/v1/nf-instances \
  | python3 -c "import sys,json; nfs=json.load(sys.stdin); print(f'{len(nfs[\"nfInstances\"])} NFs registered')"
```

### Verify RBAC

```bash
# NF ServiceAccounts should exist
kubectl get serviceaccounts -n open5gs | grep "\-sa"

# amf-sa should NOT be able to list pods
kubectl auth can-i list pods -n open5gs --as=system:serviceaccount:open5gs:amf-sa
# Expected: no

# closed-loop-sa should be able to patch upf deployment
kubectl auth can-i patch deployment/upf -n open5gs \
  --as=system:serviceaccount:open5gs:closed-loop-sa
# Expected: yes
```

---

## 7. Security Posture Summary

| Control | Status | Note |
|---------|--------|------|
| Default deny NetworkPolicy | ✅ Applied & enforced | kindnet nfqueue enforces from v0.23+ |
| Per-NF NetworkPolicies | ✅ Applied | 23 policies covering all NFs + ml-serving-api + closed-loop |
| MongoDB credential Secret | ✅ Created | Auth migration required to activate |
| Dedicated ServiceAccounts | ✅ Created | Need to patch Deployments to reference them |
| automountServiceAccountToken: false | ✅ All NFs | Token injection disabled |
| Least-privilege RBAC | ✅ Defined | NFs: read-only; autoscaler: upf-patch only |
| Secrets at rest encryption | ❌ Not configured | Requires etcd encryption config |
| mTLS between NFs | ❌ Design only | Requires Istio or Open5GS TLS config |
| CNI NetworkPolicy enforcement | ✅ kindnet nfqueue | Enforced; nfqueue userspace daemon active |
| Secret scanning in CI | ✅ Configured | gitleaks pre-commit hook installed |
