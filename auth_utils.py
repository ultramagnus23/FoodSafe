"""
FoodSafe India — Auth Utilities
JWT token creation + verification + rate limiting + tier enforcement.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import jwt

from api.db import get_pool

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
                SELECT ak.user_id, ak.tier, ak.rate_limit_per_day, ak.revoked_at
                FROM api_keys ak
                WHERE ak.key_hash = $1
                """,
                key_hash,
            )
        if not row or row["revoked_at"] is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        user_id = str(row["user_id"])
        tier    = row["tier"]

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
