"""
FoodSafe India — Alert Subscription Management
POST   /v1/subscriptions          create (consumer_premium+ required)
GET    /v1/subscriptions          list current user's subscriptions
PATCH  /v1/subscriptions/{id}     update alert_types/severity_threshold/active
DELETE /v1/subscriptions/{id}     remove

Email is the only notification channel in this pass — see
models/notifications.py for the actual sending logic (WhatsApp explicitly
out of scope).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import require_tier, CurrentUser
from api.db import get_pool

logger = logging.getLogger("foodsafe.routes.subscriptions")

subscriptions_router = APIRouter()

VALID_ALERT_TYPES = {"twi_exceedance", "codex_exceedance_fssai_compliant", "trend_worsening"}
VALID_SEVERITIES = {"moderate", "high", "critical"}


class SubscriptionCreate(BaseModel):
    district_id: Optional[int] = None
    commodity_id: Optional[int] = None
    contaminant_id: Optional[int] = None
    alert_types: list[str] = ["twi_exceedance", "codex_exceedance_fssai_compliant"]
    severity_threshold: str = "moderate"


class SubscriptionUpdate(BaseModel):
    alert_types: Optional[list[str]] = None
    severity_threshold: Optional[str] = None
    active: Optional[bool] = None


class SubscriptionOut(BaseModel):
    id: int
    district_id: Optional[int]
    district_name: Optional[str]
    commodity_id: Optional[int]
    commodity_name: Optional[str]
    contaminant_id: Optional[int]
    contaminant_name: Optional[str]
    alert_types: list[str]
    severity_threshold: str
    active: bool
    created_at: str
    last_notified_at: Optional[str]


def _validate(alert_types: list[str], severity: str):
    bad_types = set(alert_types) - VALID_ALERT_TYPES
    if bad_types:
        raise HTTPException(400, f"Invalid alert_types: {bad_types}")
    if severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"severity_threshold must be one of {VALID_SEVERITIES}")


@subscriptions_router.post("", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    body: SubscriptionCreate,
    user: CurrentUser = Depends(require_tier("consumer_premium", "fmcg", "insurance")),
):
    _validate(body.alert_types, body.severity_threshold)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alert_subscriptions (user_id, district_id, commodity_id, contaminant_id, alert_types, severity_threshold)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, created_at
            """,
            user.user_id, body.district_id, body.commodity_id, body.contaminant_id,
            body.alert_types, body.severity_threshold,
        )
        return await _fetch_subscription(conn, row["id"])


@subscriptions_router.get("", response_model=list[SubscriptionOut])
async def list_subscriptions(user: CurrentUser = Depends(require_tier("consumer_premium", "fmcg", "insurance"))):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.district_id, d.name_canonical AS district_name,
                   s.commodity_id, c.name_canonical AS commodity_name,
                   s.contaminant_id, cnt.name_canonical AS contaminant_name,
                   s.alert_types, s.severity_threshold, s.active, s.created_at, s.last_notified_at
            FROM alert_subscriptions s
            LEFT JOIN districts d ON d.id = s.district_id
            LEFT JOIN commodities c ON c.id = s.commodity_id
            LEFT JOIN contaminants cnt ON cnt.id = s.contaminant_id
            WHERE s.user_id = $1
            ORDER BY s.created_at DESC
            """,
            user.user_id,
        )
    return [_row_to_model(r) for r in rows]


@subscriptions_router.patch("/{sub_id}", response_model=SubscriptionOut)
async def update_subscription(
    sub_id: int, body: SubscriptionUpdate,
    user: CurrentUser = Depends(require_tier("consumer_premium", "fmcg", "insurance")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM alert_subscriptions WHERE id = $1 AND user_id = $2", sub_id, user.user_id)
        if not existing:
            raise HTTPException(404, "Subscription not found")

        if body.alert_types is not None or body.severity_threshold is not None:
            _validate(
                body.alert_types if body.alert_types is not None else list(VALID_ALERT_TYPES),
                body.severity_threshold if body.severity_threshold is not None else "moderate",
            )

        await conn.execute(
            """
            UPDATE alert_subscriptions SET
                alert_types = COALESCE($1, alert_types),
                severity_threshold = COALESCE($2, severity_threshold),
                active = COALESCE($3, active)
            WHERE id = $4
            """,
            body.alert_types, body.severity_threshold, body.active, sub_id,
        )
        return await _fetch_subscription(conn, sub_id)


@subscriptions_router.delete("/{sub_id}")
async def delete_subscription(sub_id: int, user: CurrentUser = Depends(require_tier("consumer_premium", "fmcg", "insurance"))):
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM alert_subscriptions WHERE id = $1 AND user_id = $2", sub_id, user.user_id)
        if not existing:
            raise HTTPException(404, "Subscription not found")
        await conn.execute("DELETE FROM alert_subscriptions WHERE id = $1", sub_id)
    return {"id": sub_id, "deleted": True}


async def _fetch_subscription(conn, sub_id: int) -> SubscriptionOut:
    row = await conn.fetchrow(
        """
        SELECT s.id, s.district_id, d.name_canonical AS district_name,
               s.commodity_id, c.name_canonical AS commodity_name,
               s.contaminant_id, cnt.name_canonical AS contaminant_name,
               s.alert_types, s.severity_threshold, s.active, s.created_at, s.last_notified_at
        FROM alert_subscriptions s
        LEFT JOIN districts d ON d.id = s.district_id
        LEFT JOIN commodities c ON c.id = s.commodity_id
        LEFT JOIN contaminants cnt ON cnt.id = s.contaminant_id
        WHERE s.id = $1
        """,
        sub_id,
    )
    return _row_to_model(row)


def _row_to_model(row) -> SubscriptionOut:
    return SubscriptionOut(
        id=row["id"], district_id=row["district_id"], district_name=row["district_name"],
        commodity_id=row["commodity_id"], commodity_name=row["commodity_name"],
        contaminant_id=row["contaminant_id"], contaminant_name=row["contaminant_name"],
        alert_types=list(row["alert_types"]), severity_threshold=row["severity_threshold"],
        active=row["active"], created_at=str(row["created_at"]),
        last_notified_at=str(row["last_notified_at"]) if row["last_notified_at"] else None,
    )
