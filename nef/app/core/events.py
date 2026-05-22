"""
events.py — In-memory subscription store + webhook dispatcher.

On AWS this would be backed by DynamoDB (subscriptions) and SQS/EventBridge
(fan-out).  For local/KinD the in-memory store is sufficient for a single
NEF replica.

Flow:
  UE attaches → AMF writes to MongoDB subscribers collection
  NEF polls the collection every POLL_INTERVAL_S seconds
  When state changes, NEF dispatches a POST to each matching webhook
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("nef.events")
settings = get_settings()

# ── Subscription model ────────────────────────────────────────────────────────
VALID_EVENT_TYPES = {
    "UE_ATTACH",
    "UE_DETACH",
    "PDU_SESSION_ESTABLISHED",
    "PDU_SESSION_RELEASED",
    "QOS_CHANGE",
}


@dataclass
class Subscription:
    subscription_id: str
    client_id: str
    event_types: list[str]
    callback_url: str
    imsi_filter: str | None    # None = all UEs
    created_at: float = field(default_factory=time.time)
    active: bool = True


# ── In-memory store ───────────────────────────────────────────────────────────
_subscriptions: dict[str, Subscription] = {}
_ue_state_cache: dict[str, dict[str, Any]] = {}  # imsi → last known state


def create_subscription(
    client_id: str,
    event_types: list[str],
    callback_url: str,
    imsi_filter: str | None = None,
) -> Subscription:
    invalid = set(event_types) - VALID_EVENT_TYPES
    if invalid:
        raise ValueError(f"Unknown event type(s): {invalid}")
    sub_id = str(uuid.uuid4())
    sub = Subscription(
        subscription_id=sub_id,
        client_id=client_id,
        event_types=event_types,
        callback_url=callback_url,
        imsi_filter=imsi_filter,
    )
    _subscriptions[sub_id] = sub
    log.info("Subscription created id=%s client=%s events=%s", sub_id, client_id, event_types)
    return sub


def get_subscription(sub_id: str) -> Subscription | None:
    return _subscriptions.get(sub_id)


def list_subscriptions(client_id: str) -> list[Subscription]:
    return [s for s in _subscriptions.values() if s.client_id == client_id]


def delete_subscription(sub_id: str, client_id: str) -> bool:
    sub = _subscriptions.get(sub_id)
    if sub and sub.client_id == client_id:
        del _subscriptions[sub_id]
        return True
    return False


# ── Webhook delivery ──────────────────────────────────────────────────────────
async def _dispatch_webhook(callback_url: str, payload: dict) -> None:
    """POST event payload to subscriber callback with retries."""
    headers = {
        "Content-Type": "application/json",
        "X-NEF-Event": payload.get("event_type", "UNKNOWN"),
        "X-NEF-Timestamp": str(int(time.time())),
    }
    for attempt in range(1, settings.webhook_max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_s) as client:
                resp = await client.post(callback_url, json=payload, headers=headers)
                resp.raise_for_status()
                log.info("Webhook delivered url=%s status=%d attempt=%d",
                         callback_url, resp.status_code, attempt)
                return
        except Exception as exc:
            log.warning("Webhook attempt %d failed url=%s err=%s", attempt, callback_url, exc)
            if attempt < settings.webhook_max_retries:
                await asyncio.sleep(2 ** attempt)
    log.error("Webhook delivery failed after %d attempts url=%s", settings.webhook_max_retries, callback_url)


async def emit_event(event_type: str, imsi: str, data: dict) -> None:
    """
    Fan out an event to all matching active subscriptions.
    Called by the AMF poller or triggered directly by QoS/session events.
    """
    if event_type not in VALID_EVENT_TYPES:
        log.warning("Unknown event type: %s", event_type)
        return

    payload = {
        "event_type": event_type,
        "imsi": imsi,
        "timestamp": int(time.time()),
        "data": data,
    }

    tasks = []
    for sub in _subscriptions.values():
        if not sub.active:
            continue
        if event_type not in sub.event_types:
            continue
        if sub.imsi_filter and sub.imsi_filter != imsi:
            continue
        tasks.append(_dispatch_webhook(sub.callback_url, payload))

    if tasks:
        log.info("Emitting %s for imsi=%s to %d subscriber(s)", event_type, imsi, len(tasks))
        await asyncio.gather(*tasks, return_exceptions=True)


# ── AMF state poller ──────────────────────────────────────────────────────────
async def poll_amf_events(db) -> None:
    """
    Periodic coroutine: diff Open5GS subscribers collection against cache,
    emit UE_ATTACH / UE_DETACH events on state changes.

    Open5GS writes each subscriber's session state into the 'subscribers'
    collection under the 'access_and_mobility_subscription_data' subdocument
    and the 'session_management_subscription_data' array.
    """
    POLL_INTERVAL = 10  # seconds

    while True:
        try:
            cursor = db["subscribers"].find({}, {
                "imsi": 1,
                "access_and_mobility_subscription_data": 1,
                "session_management_subscription_data": 1,
            })
            async for doc in cursor:
                imsi = doc.get("imsi", "")
                if not imsi:
                    continue

                # Derive a simple "has active session" state
                smd = doc.get("session_management_subscription_data", [])
                has_session = len(smd) > 0

                prev = _ue_state_cache.get(imsi, {})
                prev_session = prev.get("has_session", None)

                if prev_session is None:
                    # First time seen — store without emitting
                    _ue_state_cache[imsi] = {"has_session": has_session}
                elif has_session and not prev_session:
                    _ue_state_cache[imsi] = {"has_session": True}
                    await emit_event("UE_ATTACH", imsi, {"source": "amf_poll"})
                elif not has_session and prev_session:
                    _ue_state_cache[imsi] = {"has_session": False}
                    await emit_event("UE_DETACH", imsi, {"source": "amf_poll"})

        except Exception as exc:
            log.warning("AMF poll error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL)
