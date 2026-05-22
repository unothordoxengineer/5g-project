"""
auth.py — JWT authentication layer.

Local mode:  issues + validates HS256 tokens via /auth/token (client_credentials).
AWS mode:    when NEF_COGNITO_JWKS_URL is set, validates Cognito RS256 JWT instead
             (just swap _decode_cognito() into the Depends chain — no code changes
             to routers needed).

The Depends(get_current_client) pattern is identical in both modes so all
existing endpoint code is fully AWS-portable.
"""
from __future__ import annotations

import time
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from .config import get_settings

log = logging.getLogger("nef.auth")
settings = get_settings()

# ── Password hashing (client_secret) ─────────────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Registered API clients (local only — on AWS use Cognito App Clients) ──────
# Format: { client_id: hashed_secret }
# Generate hash:  python -c "from passlib.context import CryptContext; print(CryptContext(['bcrypt']).hash('secret'))"
_CLIENTS: dict[str, str] = {
    "demo-app":     _pwd_ctx.hash("demo-secret-2026"),
    "test-client":  _pwd_ctx.hash("test-secret-2026"),
}

# Scopes a client must have to call each endpoint group
SCOPE_SUBSCRIBE  = "nef:subscribe"
SCOPE_UE_STATUS  = "nef:ue_status"
SCOPE_QOS_POLICY = "nef:qos_policy"

# ── Token models ──────────────────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class TokenPayload(BaseModel):
    sub: str              # client_id
    scopes: list[str]
    exp: int

# ── OAuth2 bearer scheme ──────────────────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=True)


# ── Token issuance (local /auth/token — maps to Cognito /oauth2/token on AWS) ─
def issue_token(client_id: str, client_secret: str) -> TokenResponse:
    """Validate client credentials and return a signed JWT."""
    hashed = _CLIENTS.get(client_id)
    if not hashed or not _pwd_ctx.verify(client_secret, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client_id or client_secret",
        )
    exp = int(time.time()) + settings.jwt_expire_minutes * 60
    payload = {
        "sub": client_id,
        "scopes": [SCOPE_SUBSCRIBE, SCOPE_UE_STATUS, SCOPE_QOS_POLICY],
        "exp": exp,
        "iat": int(time.time()),
        "iss": f"nef-local/{settings.environment}",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    log.info("Token issued for client=%s exp=%s", client_id, exp)
    return TokenResponse(access_token=token, expires_in=settings.jwt_expire_minutes * 60)


# ── Token validation ──────────────────────────────────────────────────────────
def _decode_local(token: str) -> TokenPayload:
    """Validate HS256 local token."""
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return TokenPayload(
            sub=data["sub"],
            scopes=data.get("scopes", []),
            exp=data["exp"],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalid or expired: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_cognito(token: str) -> TokenPayload:  # pragma: no cover
    """
    Validate Cognito RS256 token.  Activated when NEF_COGNITO_JWKS_URL is set.
    Uses python-jose with JWKS key auto-fetch.
    """
    import urllib.request, json as _json
    jwks = _json.loads(urllib.request.urlopen(settings.cognito_jwks_url).read())
    try:
        data = jwt.decode(token, jwks, algorithms=["RS256"],
                          audience=settings.cognito_client_id)
        return TokenPayload(
            sub=data.get("client_id") or data["sub"],
            scopes=data.get("scope", "").split(),
            exp=data["exp"],
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f"Cognito token invalid: {exc}",
                            headers={"WWW-Authenticate": "Bearer"})


def _validate_token(token: str) -> TokenPayload:
    """Route to Cognito or local validation depending on config."""
    if settings.cognito_jwks_url:
        return _decode_cognito(token)
    return _decode_local(token)


# ── FastAPI dependency ─────────────────────────────────────────────────────────
async def get_current_client(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    return _validate_token(token)


def require_scope(scope: str):
    """
    Returns a FastAPI dependency that enforces a specific OAuth2 scope.

    Usage:  Depends(require_scope(SCOPE_UE_STATUS))
    """
    async def _check(client: TokenPayload = Depends(get_current_client)):
        if scope not in client.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token missing required scope: {scope}",
            )
        return client
    return _check
