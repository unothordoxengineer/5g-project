"""
ue_status.py — GET /ue-status/{imsi}

Queries Open5GS MongoDB (read-only) to surface UE registration and session
state for a given IMSI.

On AWS: Lambda calls NEF service inside VPC; NEF queries DocumentDB
        (MongoDB-compatible) for the same collection schema.
        AMF SBI query is attempted first for live state; MongoDB is the fallback.
"""
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.auth import require_scope, SCOPE_UE_STATUS, TokenPayload
from ..core.config import get_settings
from ..core.database import get_open5gs_db

log = logging.getLogger("nef.ue_status")
settings = get_settings()
router = APIRouter(prefix="/ue-status", tags=["UE Status"])


# ── Response schema ───────────────────────────────────────────────────────────
class PDUSession(BaseModel):
    pdu_session_id: int
    apn: str
    pdu_type: str
    ue_ip: str | None = None


class UEStatusResponse(BaseModel):
    imsi: str
    registered: bool
    registration_state: str    # REGISTERED | DEREGISTERED | UNKNOWN
    pdu_sessions: list[PDUSession]
    last_seen: int | None      # Unix timestamp from MongoDB, if available
    source: str                # "amf_sbi" | "mongodb" | "not_found"
    query_ts: int


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _query_amf_sbi(imsi: str) -> dict[str, Any] | None:
    """
    Attempt to query AMF SBI for live registration context.
    AMF exposes Namf_Communication (TS 29.518) — GET /namf-comm/v1/ue-contexts/{ueContextId}.
    UE context ID format:  imsi-<imsi>
    """
    url = f"{settings.amf_sbi_url}/namf-comm/v1/ue-contexts/imsi-{imsi}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            log.debug("AMF SBI returned %d for imsi=%s", resp.status_code, imsi)
    except Exception as exc:
        log.debug("AMF SBI query failed imsi=%s err=%s", imsi, exc)
    return None


async def _query_mongodb(imsi: str) -> dict[str, Any] | None:
    """
    Query Open5GS subscribers collection for subscriber profile + session state.
    Collection: open5gs.subscribers
    Key field:  imsi  (string, e.g. "999700000000001")
    """
    try:
        db = get_open5gs_db()
        doc = await db["subscribers"].find_one({"imsi": imsi})
        return doc
    except Exception as exc:
        log.warning("MongoDB query failed imsi=%s err=%s", imsi, exc)
    return None


def _parse_mongodb_doc(imsi: str, doc: dict[str, Any]) -> UEStatusResponse:
    """Extract UE status from the Open5GS subscriber document."""
    smd = doc.get("session_management_subscription_data", [])
    pdu_sessions = []
    for i, s in enumerate(smd):
        apn = s.get("dnn", "internet")
        pdu_type = {
            1: "IPv4", 2: "IPv6", 3: "IPv4v6"
        }.get(s.get("pdu_session_types", {}).get("default_session_type", 1), "IPv4")
        pdu_sessions.append(PDUSession(
            pdu_session_id=i + 1,
            apn=apn,
            pdu_type=pdu_type,
            ue_ip=None,           # IP assigned at session establishment, not in profile
        ))

    registered = len(smd) > 0
    return UEStatusResponse(
        imsi=imsi,
        registered=registered,
        registration_state="REGISTERED" if registered else "DEREGISTERED",
        pdu_sessions=pdu_sessions,
        last_seen=None,
        source="mongodb",
        query_ts=int(time.time()),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.get("/{imsi}", response_model=UEStatusResponse,
            summary="Query UE registration and session state")
async def get_ue_status(
    imsi: str,
    client: TokenPayload = Depends(require_scope(SCOPE_UE_STATUS)),
):
    """
    Returns the current registration and PDU session state for the given IMSI.

    Query order:
    1. AMF SBI (`Namf_Communication`) — live state, lowest latency
    2. Open5GS MongoDB `subscribers` collection — authoritative profile store
    3. 404 if not provisioned

    **imsi**: 15-digit IMSI string, e.g. `999700000000001`
    """
    # Validate IMSI format
    if not imsi.isdigit() or len(imsi) != 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="IMSI must be a 15-digit numeric string",
        )

    # 1. Try AMF SBI for live context
    amf_data = await _query_amf_sbi(imsi)
    if amf_data:
        log.info("UE status from AMF SBI imsi=%s", imsi)
        # AMF returns ueContextId and connection state
        ue_state = amf_data.get("ueState", "REGISTERED")
        return UEStatusResponse(
            imsi=imsi,
            registered=True,
            registration_state=ue_state,
            pdu_sessions=[],   # detailed sessions live in SMF context
            last_seen=int(time.time()),
            source="amf_sbi",
            query_ts=int(time.time()),
        )

    # 2. Fall back to MongoDB subscriber profile
    doc = await _query_mongodb(imsi)
    if doc:
        log.info("UE status from MongoDB imsi=%s", imsi)
        return _parse_mongodb_doc(imsi, doc)

    # 3. Not found
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"IMSI {imsi!r} not provisioned in this 5G core",
    )
