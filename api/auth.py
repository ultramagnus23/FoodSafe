"""
FoodSafe India — Auth Routes
POST /v1/auth/register
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from api.auth_utils import (
    create_access_token,
    create_refresh_token,
    hash_token,
    _verify_token,
    REFRESH_TTL,
)
from api.db import get_pool

auth_router = APIRouter()

DISCLAIMER = (
    "This platform provides statistical risk estimates based on public government "
    "enforcement data. Not a substitute for laboratory testing or professional advice."
)


# ============================================================
# SCHEMAS
# ============================================================

class RegisterRequest(BaseModel):
    email:           str
    password:        str
    phone:           str | None = None
    home_district_id: int | None = None


class LoginRequest(BaseModel):
    email:    str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    tier:          str
    user_id:       str
    disclaimer:    str = DISCLAIMER


# ============================================================
# HELPERS
# ============================================================

def _hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


# ============================================================
# ROUTES
# ============================================================

@auth_router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1", body.email
        )
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = _hash_password(body.password)
        user_id = str(uuid.uuid4())

        await conn.execute(
            """
            INSERT INTO users (id, email, phone, password_hash, tier, home_district_id)
            VALUES ($1, $2, $3, $4, 'consumer_free', $5)
            """,
            user_id,
            body.email.lower().strip(),
            body.phone,
            pw_hash,
            body.home_district_id,
        )

    access  = create_access_token(user_id, "consumer_free")
    refresh = create_refresh_token(user_id)

    # Store refresh token hash
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            str(uuid.uuid4()),
            user_id,
            hash_token(refresh),
            datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TTL),
        )

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        tier="consumer_free",
        user_id=user_id,
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, tier FROM users WHERE email = $1",
            body.email.lower().strip(),
        )

    if not row or not _check_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id = str(row["id"])
    tier    = row["tier"]

    access  = create_access_token(user_id, tier)
    refresh = create_refresh_token(user_id)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            str(uuid.uuid4()),
            user_id,
            hash_token(refresh),
            datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TTL),
        )
        await conn.execute(
            "UPDATE users SET last_login = NOW() WHERE id = $1", user_id
        )

    return TokenResponse(access_token=access, refresh_token=refresh, tier=tier, user_id=user_id)


@auth_router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest):
    payload = _verify_token(body.refresh_token, "refresh")
    user_id = payload["sub"]

    pool = get_pool()
    async with pool.acquire() as conn:
        rt_row = await conn.fetchrow(
            """
            SELECT id, revoked_at FROM refresh_tokens
            WHERE token_hash = $1 AND user_id = $2 AND expires_at > NOW()
            """,
            hash_token(body.refresh_token),
            user_id,
        )
        if not rt_row or rt_row["revoked_at"] is not None:
            raise HTTPException(status_code=401, detail="Refresh token invalid or expired")

        user_row = await conn.fetchrow("SELECT tier FROM users WHERE id = $1", user_id)
        tier = user_row["tier"]

        # Rotate: revoke old, issue new
        await conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = $1", rt_row["id"]
        )

        new_refresh = create_refresh_token(user_id)
        await conn.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            str(uuid.uuid4()),
            user_id,
            hash_token(new_refresh),
            datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TTL),
        )

    return TokenResponse(
        access_token=create_access_token(user_id, tier),
        refresh_token=new_refresh,
        tier=tier,
        user_id=user_id,
    )


@auth_router.post("/logout", status_code=204)
async def logout(body: RefreshRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = $1",
            hash_token(body.refresh_token),
        )
