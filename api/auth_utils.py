"""
FoodSafe India — Auth Utilities
JWT token creation + verification + rate limiting + tier enforcement.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import jwt

from api.db import get_pool

logger = logging.getLogger("foodsafe.auth_utils")

SECRET_KEY  = os.environ.get("JWT_SECRET", "change-me-in-production-use-env")
ALGORITHM   = "HS256"
ACCESS_TTL  = 15 * 60        # 15 minutes
REFRESH_TTL = 30 * 24 * 3600 # 30 days

# Requests/day per tier (enforced via Redis in production; checked in DB here for simplicity)
TIER_LIMITS = {
    "consumer_free":    100,
    "consumer_premium": 1000,
    "fmcg":             5000,
    "insurance":        999_999,
}

bearer_scheme = HTTPBearer(auto_error=False)


# ---- Token creation ----

def create_access_token(user_id: str, tier: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  user_id,
        "tier": tier,
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(seconds=ACCESS_TTL)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  user_id,
        "iat":  int(now.timestamp()),
        "exp":  int((now + timedelta(seconds=REFRESH_TTL)).timestamp()),
        "type": "refresh",
        # jti: without this, two logins within the same second produce an
        # identical token (same claims -> same signature), which collides
        # on refresh_tokens.token_hash's UNIQUE constraint and 500s.
        "jti":  secrets.token_hex(8),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _verify_token(token: str, token_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != token_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return payload


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- FastAPI dependency ----

class CurrentUser:
    def __init__(self, user_id: str, tier: str):
        self.user_id = user_id
        self.tier    = tier
        self.limit   = TIER_LIMITS.get(tier, 100)


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    """
    Extract + verify JWT. Also checks API key header for machine clients.
    Raises 401 if not authenticated, 429 if rate limit exceeded.
    """
    token = None

    # Try Bearer token
    if creds and creds.credentials:
        token = creds.credentials
        payload = _verify_token(token, "access")
        user_id = payload["sub"]
        tier    = payload["tier"]

    # Try X-API-Key header
    elif api_key := request.headers.get("X-API-Key"):
        pool = get_pool()
        key_hash = hash_token(api_key)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT ak.id, ak.user_id, ak.tier, ak.rate_limit_per_day, ak.revoked_at, ak.expires_at
                FROM api_keys ak
                WHERE ak.key_hash = $1
                """,
                key_hash,
            )
            if not row or row["revoked_at"] is not None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
            if row["expires_at"] is not None and row["expires_at"] < datetime.now(timezone.utc):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
            user_id = str(row["user_id"])
            tier    = row["tier"]

            # Rate limit: count actual calls in the trailing 24h against
            # rate_limit_per_day (backed by api_key_usage, populated below —
            # persists across restarts, unlike the in-memory limiter used
            # for JWT/anonymous requests in api/main.py's middleware).
            calls_today = await conn.fetchval(
                "SELECT COUNT(*) FROM api_key_usage WHERE key_id = $1 AND created_at >= NOW() - INTERVAL '24 hours'",
                row["id"],
            )
            if calls_today >= row["rate_limit_per_day"]:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"API key rate limit exceeded ({row['rate_limit_per_day']}/day)",
                )

            # Usage tracking for the B2B dashboard — best-effort, never blocks
            # or fails the actual request.
            try:
                await conn.execute("UPDATE api_keys SET last_used = NOW() WHERE id = $1", row["id"])
                await conn.execute(
                    "INSERT INTO api_key_usage (key_id, endpoint, method) VALUES ($1, $2, $3)",
                    row["id"], request.url.path, request.method,
                )
            except Exception:
                logger.warning("Failed to record API key usage for key %s", row["id"], exc_info=True)

    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(user_id=user_id, tier=tier)


def require_tier(*allowed_tiers: str):
    """Dependency factory: require specific tier(s)."""
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.tier not in allowed_tiers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires tier: {', '.join(allowed_tiers)}",
            )
        return user
    return _check
