#!/usr/bin/env python3
"""
main.py — 5G Network Exposure Function (NEF) — External API Layer
=================================================================
Exposes selected 5G Core capabilities to authenticated external applications.

Endpoints:
  POST /auth/token              — OAuth2 client_credentials token issuance (local)
                                  On AWS: replaced by Cognito /oauth2/token
  POST /subscribe               — Register UE event webhook subscription
  GET  /subscribe               — List own subscriptions
  DELETE /subscribe/{id}        — Remove subscription
  GET  /ue-status/{imsi}        — Query UE registration + PDU session state
  POST /qos-policy              — Push QoS policy to PCF

  GET  /health                  — Liveness probe
  GET  /metrics                 — Prometheus metrics (scraped by existing stack)
  GET  /                        — API index

Security:
  All /subscribe, /ue-status, /qos-policy endpoints require a valid Bearer JWT.
  Local: HS256 token from /auth/token.
  AWS:   RS256 Cognito token (set NEF_COGNITO_JWKS_URL env var to activate).

Rate limiting:
  100 req/min per client (mirrors API Gateway usage plan).

Deployment:
  Local/KinD:  docker build + kubectl apply -f k8s/nef/
  AWS/EKS:     same image + API Gateway → Lambda (Mangum) → NEF service in VPC
"""
import asyncio
import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from .core.config import get_settings
from .core.auth import issue_token
from .core.database import connect_db, disconnect_db, get_open5gs_db
from .core.events import poll_amf_events
from .routers import subscribe, ue_status, qos_policy

# ── Config & logging ──────────────────────────────────────────────────────────
settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("nef")

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "nef_requests_total",
    "Total NEF API requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "nef_request_duration_seconds",
    "NEF API request latency",
    ["endpoint"],
)
AUTH_FAILURES = Counter("nef_auth_failures_total", "JWT validation failures")
EVENT_DISPATCHES = Counter("nef_events_dispatched_total", "Webhook events dispatched", ["event_type"])

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI application ───────────────────────────────────────────────────────
app = FastAPI(
    title="5G NEF — Network Exposure Function",
    description=__doc__,
    version=settings.version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten to API Gateway domain on AWS
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(subscribe.router)
app.include_router(ue_status.router)
app.include_router(qos_policy.router)

# ── Request instrumentation middleware ────────────────────────────────────────
@app.middleware("http")
async def instrument(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    path = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=path,
        status_code=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(endpoint=path).observe(elapsed)

    # Surface latency header for easy curl testing
    response.headers["X-Response-Time-Ms"] = f"{elapsed * 1000:.1f}"
    return response


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    log.info("NEF starting up — env=%s version=%s", settings.environment, settings.version)
    await connect_db()
    # Start background AMF event poller
    asyncio.create_task(poll_amf_events(get_open5gs_db()))
    log.info("AMF event poller started")


@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()
    log.info("NEF shutdown complete")


# ── Auth endpoint (local token issuance) ──────────────────────────────────────
from fastapi import Form

@app.post("/auth/token", tags=["Authentication"],
          summary="Issue a Bearer JWT (local OAuth2 client_credentials)")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def token(
    request: Request,
    grant_type: str = Form(default="client_credentials"),
    client_id: str = Form(...),
    client_secret: str = Form(...),
):
    """
    OAuth2 `client_credentials` flow — returns a signed JWT.

    **On AWS**: this endpoint is replaced by the Cognito `/oauth2/token` endpoint.
    The JWT structure (sub, scopes, exp) remains identical so all client code
    is portable without modification.

    Demo credentials (local only):
    - `client_id=demo-app` / `client_secret=demo-secret-2026`
    - `client_id=test-client` / `client_secret=test-secret-2026`
    """
    if grant_type != "client_credentials":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type",
                     "error_description": "Only client_credentials is supported"},
        )
    return issue_token(client_id, client_secret)


# ── Internal PCF notify callback ──────────────────────────────────────────────
@app.post("/internal/pcf-notify", include_in_schema=False)
async def pcf_notify(request: Request):
    """Receives policy update notifications from PCF (internal cluster only)."""
    body = await request.json()
    log.info("PCF notify received: %s", body)
    return {"status": "acknowledged"}


# ── Health & metrics ──────────────────────────────────────────────────────────
@app.get("/health", tags=["Operations"], summary="Liveness probe")
async def health():
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "uptime_s": int(time.time()),
    }


@app.get("/metrics", tags=["Operations"],
         summary="Prometheus metrics endpoint",
         response_class=Response)
async def metrics():
    """Scraped by the existing prometheus-prometheus stack in the monitoring namespace."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Root index ────────────────────────────────────────────────────────────────
@app.get("/", tags=["Operations"], summary="API index")
async def root():
    return {
        "service": "5G NEF — Network Exposure Function",
        "version": settings.version,
        "environment": settings.environment,
        "docs": "/docs",
        "endpoints": {
            "auth":       "POST /auth/token",
            "subscribe":  "POST /subscribe",
            "ue_status":  "GET  /ue-status/{imsi}",
            "qos_policy": "POST /qos-policy",
            "health":     "GET  /health",
            "metrics":    "GET  /metrics",
        },
        "aws_note": (
            "On AWS: /auth/token → Cognito /oauth2/token | "
            "API Gateway enforces throttle + WAF | "
            "Lambda wraps this app via Mangum"
        ),
    }
