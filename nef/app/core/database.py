"""
database.py — Async MongoDB client (Motor).

The open5gs namespace MongoDB at mongodb.open5gs.svc.cluster.local:27017
holds subscriber state written by the Open5GS NFs.  NEF queries it
read-only for UE status lookups.

Subscriptions are stored in a lightweight in-memory dict for local/dev.
On AWS/EKS, swap NEF_MONGODB_URI to point to DocumentDB.
"""
from __future__ import annotations

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from .config import get_settings

log = logging.getLogger("nef.db")
settings = get_settings()

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    global _client
    log.info("Connecting to MongoDB: %s", settings.mongodb_uri)
    _client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    # Ping to surface connection errors early
    try:
        await _client.admin.command("ping")
        log.info("MongoDB connection established")
    except Exception as exc:
        log.warning("MongoDB ping failed (%s) — UE status queries will fail", exc)


async def disconnect_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        log.info("MongoDB connection closed")


def get_open5gs_db() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client not initialised — call connect_db() first")
    return _client["open5gs"]
