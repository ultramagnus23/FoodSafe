"""
FoodSafe India — B2B API Key Management
POST   /v1/keys              generate a new key (shown once, never again)
GET    /v1/keys               list this user's keys (prefix only)
DELETE /v1/keys/{id}          revoke a key
GET    /v1/keys/{id}/usage    calls/day for the last 30 days

Requires fmcg or insurance tier. Auth for these endpoints is always the JWT
(cookie/bearer) flow — you can't use an API key to manage API keys.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import require_tier, hash_token, CurrentUser
from api.db import user_scoped

logger = logging.getLogger("foodsafe.routes.api_keys")

api_keys_router = APIRouter()

KEY_TIER_LIMITS = {"fmcg": 5000, "insurance": 10000}


class CreateKeyRequest(BaseModel):
    name: Optional[str] = None
    expires_in_days: Optional[int] = None


class CreateKeyResponse(BaseModel):
    id: str
    key: str  # full key — shown exactly once
    key_prefix: str
    name: Optional[str]
    tier: str
    rate_limit_per_day: int
    expires_at: Optional[str]
    warning: str = "This is the only time the full key will be shown. Store it securely."


class KeySummary(BaseModel):
    id: str
    key_prefix: str
    name: Optional[str]
    tier: str
    rate_limit_per_day: int
    created_at: str
    last_used: Optional[str]
    expires_at: Optional[str]
    revoked: bool


@api_keys_router.post("", response_model=CreateKeyResponse)
async def create_key(body: CreateKeyRequest, user: CurrentUser = Depends(require_tier("fmcg", "insurance"))):
    raw_key = f"fs_{user.tier}_{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:16]
    key_hash = hash_token(raw_key)
    rate_limit = KEY_TIER_LIMITS.get(user.tier, 1000)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days else None
    )

    async with user_scoped(user.user_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (user_id, key_hash, key_prefix, name, tier, rate_limit_per_day, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, created_at
            """,
            user.user_id, key_hash, key_prefix, body.name, user.tier, rate_limit, expires_at,
        )

    return CreateKeyResponse(
        id=str(row["id"]), key=raw_key, key_prefix=key_prefix, name=body.name,
        tier=user.tier, rate_limit_per_day=rate_limit,
        expires_at=expires_at.isoformat() if expires_at else None,
    )


@api_keys_router.get("", response_model=list[KeySummary])
async def list_keys(user: CurrentUser = Depends(require_tier("fmcg", "insurance"))):
    async with user_scoped(user.user_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, key_prefix, name, tier, rate_limit_per_day, created_at,
                   last_used, expires_at, revoked_at
            FROM api_keys
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user.user_id,
        )
    return [
        KeySummary(
            id=str(r["id"]), key_prefix=r["key_prefix"] or "", name=r["name"], tier=r["tier"],
            rate_limit_per_day=r["rate_limit_per_day"], created_at=str(r["created_at"]),
            last_used=str(r["last_used"]) if r["last_used"] else None,
            expires_at=str(r["expires_at"]) if r["expires_at"] else None,
            revoked=r["revoked_at"] is not None,
        )
        for r in rows
    ]


@api_keys_router.delete("/{key_id}")
async def revoke_key(key_id: str, user: CurrentUser = Depends(require_tier("fmcg", "insurance"))):
    async with user_scoped(user.user_id) as conn:
        row = await conn.fetchrow("SELECT id FROM api_keys WHERE id = $1::uuid AND user_id = $2", key_id, user.user_id)
        if not row:
            raise HTTPException(404, "API key not found")
        await conn.execute("UPDATE api_keys SET revoked_at = NOW() WHERE id = $1::uuid", key_id)
    return {"id": key_id, "revoked": True}


class UsageDay(BaseModel):
    day: str
    calls: int


@api_keys_router.get("/{key_id}/usage", response_model=list[UsageDay])
async def key_usage(key_id: str, user: CurrentUser = Depends(require_tier("fmcg", "insurance"))):
    async with user_scoped(user.user_id) as conn:
        row = await conn.fetchrow("SELECT id FROM api_keys WHERE id = $1::uuid AND user_id = $2", key_id, user.user_id)
        if not row:
            raise HTTPException(404, "API key not found")
        rows = await conn.fetch(
            """
            SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS calls
            FROM api_key_usage
            WHERE key_id = $1::uuid AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day ORDER BY day
            """,
            key_id,
        )
    return [UsageDay(day=r["day"].isoformat(), calls=r["calls"]) for r in rows]
