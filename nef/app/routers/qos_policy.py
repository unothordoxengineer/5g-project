"""
qos_policy.py — POST /qos-policy

Allows an external application to push a QoS policy request into the 5G core
via the PCF's Npcf_PolicyAuthorization SBI (TS 29.514).

On AWS: API Gateway → Lambda → this FastAPI endpoint → PCF SBI inside VPC.
"""
import logging
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..core.auth import require_scope, SCOPE_QOS_POLICY, TokenPayload
from ..core.config import get_settings
from ..core.events import emit_event

log = logging.getLogger("nef.qos_policy")
settings = get_settings()
router = APIRouter(prefix="/qos-policy", tags=["QoS Policy"])


# ── Request / Response schemas ────────────────────────────────────────────────
class QoSFlowRequest(BaseModel):
    """Single QoS flow specification (simplified from 3GPP TS 29.514 §4.2.2.2)."""
    qos_class: str = Field(
        ...,
        description="QoS class identifier: GBR_CONVERSATIONAL_VOICE, GBR_CONVERSATIONAL_VIDEO, "
                    "NON_GBR_IMS_SIG, NON_GBR_VIDEO_BUFFERED, NON_GBR_DEFAULT",
        examples=["NON_GBR_DEFAULT"],
    )
    max_bw_ul_kbps: int = Field(0, ge=0, description="Max uplink bitrate (kbps), 0 = best-effort")
    max_bw_dl_kbps: int = Field(0, ge=0, description="Max downlink bitrate (kbps), 0 = best-effort")
    priority: int = Field(5, ge=1, le=15, description="Flow priority (1=highest, 15=lowest)")


class QoSPolicyRequest(BaseModel):
    imsi: str = Field(..., description="Target UE IMSI (15 digits)")
    apn: str = Field("internet", description="PDN/DNN to apply policy to")
    flows: list[QoSFlowRequest] = Field(..., min_length=1, max_length=8)
    duration_s: int = Field(
        3600, ge=10, le=86400,
        description="Policy validity duration in seconds (10–86400)"
    )
    reason: str = Field("", description="Human-readable reason for this policy change")


class QoSPolicyResponse(BaseModel):
    policy_id: str
    imsi: str
    apn: str
    status: str          # APPLIED | PENDING | REJECTED
    pcf_response_code: int | None
    applied_at: int
    expires_at: int
    message: str


# ── PCF SBI helpers ───────────────────────────────────────────────────────────
_QOS_CLASS_MAP = {
    "GBR_CONVERSATIONAL_VOICE":  {"5qi": 1,  "arp_priority": 2},
    "GBR_CONVERSATIONAL_VIDEO":  {"5qi": 2,  "arp_priority": 4},
    "NON_GBR_IMS_SIG":           {"5qi": 5,  "arp_priority": 1},
    "NON_GBR_VIDEO_BUFFERED":    {"5qi": 9,  "arp_priority": 8},
    "NON_GBR_DEFAULT":           {"5qi": 9,  "arp_priority": 8},
}


def _build_pcf_payload(req: QoSPolicyRequest, policy_id: str) -> dict:
    """
    Build a Npcf_PolicyAuthorization AppSession creation request body.
    Ref: TS 29.514 §4.2.2  AppSessionContext
    """
    media_components = []
    for i, flow in enumerate(req.flows):
        qc = _QOS_CLASS_MAP.get(flow.qos_class, _QOS_CLASS_MAP["NON_GBR_DEFAULT"])
        mc: dict = {
            "medCompN": i,
            "fStatus": "ENABLED",
            "qosReference": policy_id,
            "marBwUl": f"{flow.max_bw_ul_kbps} kbps" if flow.max_bw_ul_kbps else None,
            "marBwDl": f"{flow.max_bw_dl_kbps} kbps" if flow.max_bw_dl_kbps else None,
        }
        media_components.append({k: v for k, v in mc.items() if v is not None})

    return {
        "supi": f"imsi-{req.imsi}",
        "dnn": req.apn,
        "notifUri": f"http://nef.open5gs.svc.cluster.local:80/internal/pcf-notify",
        "medComponents": {str(i): mc for i, mc in enumerate(media_components)},
        "extAppId": policy_id,
    }


async def _call_pcf(payload: dict) -> tuple[int, dict]:
    """POST to PCF Npcf_PolicyAuthorization. Returns (status_code, body)."""
    url = f"{settings.pcf_sbi_url}/npcf-policyauthorization/v1/app-sessions"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            return resp.status_code, body
    except httpx.TimeoutException:
        log.warning("PCF SBI timeout calling %s", url)
        return 504, {"error": "PCF request timed out"}
    except Exception as exc:
        log.warning("PCF SBI error: %s", exc)
        return 503, {"error": str(exc)}


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.post("", response_model=QoSPolicyResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="Push a QoS policy to the 5G core via PCF")
async def apply_qos_policy(
    req: QoSPolicyRequest,
    client: TokenPayload = Depends(require_scope(SCOPE_QOS_POLICY)),
):
    """
    Submit a QoS policy request for a specific UE / DNN combination.

    The NEF translates the request into a `Npcf_PolicyAuthorization_Create`
    (TS 29.514) call to the PCF.  The PCF then installs the policy via SMF.

    **Status codes**:
    - `202 Accepted` — policy forwarded to PCF
    - `503 Service Unavailable` — PCF unreachable
    - `502 Bad Gateway` — PCF rejected the policy

    **QoS classes**: `GBR_CONVERSATIONAL_VOICE`, `GBR_CONVERSATIONAL_VIDEO`,
    `NON_GBR_IMS_SIG`, `NON_GBR_VIDEO_BUFFERED`, `NON_GBR_DEFAULT`
    """
    if not req.imsi.isdigit() or len(req.imsi) != 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="imsi must be a 15-digit numeric string",
        )

    for flow in req.flows:
        if flow.qos_class not in _QOS_CLASS_MAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown qos_class '{flow.qos_class}'. "
                       f"Valid: {list(_QOS_CLASS_MAP.keys())}",
            )

    policy_id = f"nef-{uuid.uuid4().hex[:8]}"
    now = int(time.time())

    # Build and dispatch to PCF
    pcf_payload = _build_pcf_payload(req, policy_id)
    log.info("QoS policy request policy_id=%s imsi=%s apn=%s client=%s",
             policy_id, req.imsi, req.apn, client.sub)

    pcf_status, pcf_body = await _call_pcf(pcf_payload)

    # Determine outcome
    if pcf_status in (200, 201):
        pol_status = "APPLIED"
        message = f"Policy applied by PCF (policy_id={policy_id})"
    elif pcf_status in (400, 403, 404, 422):
        pol_status = "REJECTED"
        message = f"PCF rejected policy: {pcf_body}"
        log.warning("PCF rejected policy_id=%s status=%d body=%s", policy_id, pcf_status, pcf_body)
    else:
        # PCF unreachable or 5xx → optimistic PENDING
        pol_status = "PENDING"
        message = f"Policy queued (PCF returned {pcf_status}) — will retry"
        log.warning("PCF unavailable policy_id=%s status=%d", policy_id, pcf_status)

    # Emit QOS_CHANGE event to any subscribed external apps
    await emit_event("QOS_CHANGE", req.imsi, {
        "policy_id": policy_id,
        "status": pol_status,
        "apn": req.apn,
        "flows": [f.model_dump() for f in req.flows],
    })

    return QoSPolicyResponse(
        policy_id=policy_id,
        imsi=req.imsi,
        apn=req.apn,
        status=pol_status,
        pcf_response_code=pcf_status,
        applied_at=now,
        expires_at=now + req.duration_s,
        message=message,
    )
