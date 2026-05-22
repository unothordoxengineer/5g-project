"""
subscribe.py — POST /subscribe  /  GET /subscribe  /  DELETE /subscribe/{id}

Allows external applications to register webhook callbacks for 5G UE events.
Maps to 3GPP TS 29.122 §5.2 (T8 Northbound API — simplified).

On AWS: this router runs unchanged inside Lambda (via Mangum adapter).
        Subscription state would be persisted to DynamoDB instead of
        the in-memory dict in events.py.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl, field_validator

from ..core.auth import require_scope, SCOPE_SUBSCRIBE, TokenPayload
from ..core.events import (
    create_subscription,
    get_subscription,
    list_subscriptions,
    delete_subscription,
    VALID_EVENT_TYPES,
)

log = logging.getLogger("nef.subscribe")
router = APIRouter(prefix="/subscribe", tags=["Event Subscriptions"])


# ── Request / Response schemas ────────────────────────────────────────────────
class SubscribeRequest(BaseModel):
    event_types: list[str]
    callback_url: str          # HttpUrl causes issues with local http URLs, keep as str
    imsi_filter: str | None = None

    @field_validator("event_types")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        unknown = set(v) - VALID_EVENT_TYPES
        if unknown:
            raise ValueError(f"Unknown event type(s): {unknown}. Valid: {VALID_EVENT_TYPES}")
        if not v:
            raise ValueError("event_types must not be empty")
        return v


class SubscribeResponse(BaseModel):
    subscription_id: str
    client_id: str
    event_types: list[str]
    callback_url: str
    imsi_filter: str | None
    created_at: float
    active: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=SubscribeResponse, status_code=status.HTTP_201_CREATED,
             summary="Register a new event subscription")
async def create_event_subscription(
    req: SubscribeRequest,
    client: TokenPayload = Depends(require_scope(SCOPE_SUBSCRIBE)),
):
    """
    Register a webhook callback for one or more UE event types.

    **event_types** (one or more of):
    - `UE_ATTACH` — UE successfully registered with the network
    - `UE_DETACH` — UE deregistered or lost connectivity
    - `PDU_SESSION_ESTABLISHED` — Data session established (uesimtun0 up)
    - `PDU_SESSION_RELEASED` — Data session torn down
    - `QOS_CHANGE` — PCF pushed a QoS policy change

    **callback_url**: HTTPS URL that receives a `POST` with the event payload.

    **imsi_filter** (optional): restrict to a single IMSI (e.g. `999700000000001`).
    """
    try:
        sub = create_subscription(
            client_id=client.sub,
            event_types=req.event_types,
            callback_url=req.callback_url,
            imsi_filter=req.imsi_filter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    log.info("New subscription id=%s client=%s", sub.subscription_id, client.sub)
    return SubscribeResponse(
        subscription_id=sub.subscription_id,
        client_id=sub.client_id,
        event_types=sub.event_types,
        callback_url=sub.callback_url,
        imsi_filter=sub.imsi_filter,
        created_at=sub.created_at,
        active=sub.active,
    )


@router.get("", response_model=list[SubscribeResponse],
            summary="List your active subscriptions")
async def list_event_subscriptions(
    client: TokenPayload = Depends(require_scope(SCOPE_SUBSCRIBE)),
):
    """Return all active subscriptions owned by the authenticated client."""
    subs = list_subscriptions(client.sub)
    return [
        SubscribeResponse(
            subscription_id=s.subscription_id,
            client_id=s.client_id,
            event_types=s.event_types,
            callback_url=s.callback_url,
            imsi_filter=s.imsi_filter,
            created_at=s.created_at,
            active=s.active,
        )
        for s in subs
    ]


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a subscription")
async def delete_event_subscription(
    subscription_id: str,
    client: TokenPayload = Depends(require_scope(SCOPE_SUBSCRIBE)),
):
    """Delete a subscription by ID. Only the owning client can delete."""
    deleted = delete_subscription(subscription_id, client.sub)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id!r} not found or not owned by you",
        )
    log.info("Subscription deleted id=%s client=%s", subscription_id, client.sub)
