"""
FoodSafe India — Brand Dispute Routes
POST /v1/disputes/submit
GET  /v1/disputes/{dispute_id}
GET  /v1/disputes/brand/{brand_id}
POST /v1/disputes/{dispute_id}/review   (admin only)
GET  /v1/admin/disputes                 (admin only)
GET  /v1/admin/fraud/labs               (admin only)
GET  /v1/admin/fraud/records            (admin only)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool

logger = logging.getLogger("foodsafe.routes.disputes")

disputes_router = APIRouter()
admin_router    = APIRouter()


# ============================================================
# SCHEMAS
# ============================================================

class DisputeSubmit(BaseModel):
    brand_id:               int
    commodity_id:           Optional[int]    = None
    district_id:            Optional[int]    = None
    enforcement_record_id:  Optional[int]    = None
    submitted_by_email:     str
    dispute_type:           str              = "incorrect_data"
    notes:                  Optional[str]    = None
    lab_evidence_url:       Optional[str]    = None
    counter_lab_name:       Optional[str]    = None
    counter_lab_accred:     Optional[str]    = None
    counter_value_ppb:      Optional[float]  = None
    counter_test_date:      Optional[str]    = None


class DisputeReview(BaseModel):
    outcome:        str     # 'resolved_removed' | 'resolved_kept' | 'resolved_flagged'
    resolver_notes: str


class DisputeResponse(BaseModel):
    id:                     int
    brand_id:               int
    brand_name:             str
    dispute_type:           str
    status:                 str
    submitted_by_email:     str
    notes:                  Optional[str]
    lab_evidence_url:       Optional[str]
    counter_lab_name:       Optional[str]
    counter_value_ppb:      Optional[float]
    counter_test_date:      Optional[str]
    flagged_on_platform:    bool
    submitted_at:           str
    resolved_at:            Optional[str]
    resolver_notes:         Optional[str]


class LabFraudSummary(BaseModel):
    lab_id:             int
    lab_name:           str
    lab_tier:           int
    state:              Optional[str]
    reliability_score:  Optional[float]
    pass_rate:          Optional[float]
    deviation_z_score:  Optional[float]
    flagged_suspicious: bool
    flag_reason:        Optional[str]
    last_evaluated:     Optional[str]


class FraudRecordSummary(BaseModel):
    record_id:          int
    test_date:          str
    commodity:          str
    contaminant:        str
    value_ppb:          float
    district:           Optional[str]
    lab_name:           Optional[str]
    fraud_score:        float
    fraud_flags:        list[dict]
    value_is_round:     bool
    lab_flagged:        bool


# ============================================================
# DISPUTE ROUTES
# ============================================================

@disputes_router.post("/submit", status_code=201)
async def submit_dispute(body: DisputeSubmit):
    """
    Any brand or member of the public can submit a dispute.
    No auth required — we want to make this easy.
    Dispute is flagged on platform within 48 hours per spec.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        brand = await conn.fetchrow(
            "SELECT id, name_canonical FROM brands WHERE id = $1", body.brand_id
        )
        if not brand:
            raise HTTPException(404, "Brand not found")

        row = await conn.fetchrow("""
            INSERT INTO brand_disputes (
                brand_id, commodity_id, district_id, enforcement_record_id,
                submitted_by_email, dispute_type, notes, lab_evidence_url,
                counter_lab_name, counter_lab_accred, counter_value_ppb, counter_test_date,
                status, flagged_on_platform
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11, $12::date,
                'pending', FALSE
            ) RETURNING id, submitted_at
        """,
            body.brand_id, body.commodity_id, body.district_id, body.enforcement_record_id,
            body.submitted_by_email, body.dispute_type, body.notes, body.lab_evidence_url,
            body.counter_lab_name, body.counter_lab_accred, body.counter_value_ppb,
            body.counter_test_date,
        )

        dispute_id   = row["id"]
        submitted_at = row["submitted_at"]

        # Flag on platform immediately — shown on brand card as "Under dispute"
        await conn.execute("""
            UPDATE brand_disputes SET flagged_on_platform = TRUE WHERE id = $1
        """, dispute_id)

        # Update brand safety profile to note dispute
        await conn.execute("""
            UPDATE agg_brand_safety_profile
            SET dispute_count  = COALESCE(dispute_count, 0) + 1,
                under_dispute  = TRUE,
                last_updated   = NOW()
            WHERE brand_id = $1
        """, body.brand_id)

        # Audit log
        await conn.execute("""
            INSERT INTO audit_log (action, resource, metadata)
            VALUES ('dispute_submitted', 'brand_disputes', $1::jsonb)
        """, f'{{"dispute_id": {dispute_id}, "brand_id": {body.brand_id}}}')

    return {
        "dispute_id":   dispute_id,
        "status":       "pending",
        "flagged_on_platform": True,
        "message":      "Dispute received. Your submission has been flagged on the platform. We will review within 48 hours.",
        "submitted_at": str(submitted_at),
    }


@disputes_router.get("/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(dispute_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT bd.*, b.name_canonical AS brand_name
            FROM brand_disputes bd
            JOIN brands b ON b.id = bd.brand_id
            WHERE bd.id = $1
        """, dispute_id)
    if not row:
        raise HTTPException(404, "Dispute not found")
    return _dispute_row_to_model(row)


@disputes_router.get("/brand/{brand_id}", response_model=list[DisputeResponse])
async def brand_disputes(brand_id: int):
    """Public: list disputes for a brand (status visible, emails redacted)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT bd.*, b.name_canonical AS brand_name
            FROM brand_disputes bd
            JOIN brands b ON b.id = bd.brand_id
            WHERE bd.brand_id = $1
            ORDER BY bd.submitted_at DESC
        """, brand_id)
    return [_dispute_row_to_model(r, redact_email=True) for r in rows]


def _dispute_row_to_model(row, redact_email: bool = False) -> DisputeResponse:
    email = row["submitted_by_email"]
    if redact_email and email:
        parts = email.split("@")
        email = parts[0][:2] + "***@" + (parts[1] if len(parts) > 1 else "***")
    return DisputeResponse(
        id                  = row["id"],
        brand_id            = row["brand_id"],
        brand_name          = row["brand_name"],
        dispute_type        = row["dispute_type"],
        status              = row["status"],
        submitted_by_email  = email,
        notes               = row["notes"],
        lab_evidence_url    = row["lab_evidence_url"],
        counter_lab_name    = row["counter_lab_name"],
        counter_value_ppb   = float(row["counter_value_ppb"]) if row["counter_value_ppb"] else None,
        counter_test_date   = str(row["counter_test_date"]) if row["counter_test_date"] else None,
        flagged_on_platform = row["flagged_on_platform"],
        submitted_at        = str(row["submitted_at"]),
        resolved_at         = str(row["resolved_at"]) if row["resolved_at"] else None,
        resolver_notes      = row["resolver_notes"],
    )


# ============================================================
# ADMIN ROUTES
# ============================================================

async def _require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.tier not in ("fmcg", "insurance"):
        raise HTTPException(403, "Admin access required")
    return user


@admin_router.get("/disputes", response_model=list[DisputeResponse])
async def admin_list_disputes(
    status: Optional[str] = "pending",
    limit: int = 50,
    admin: CurrentUser = Depends(_require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT bd.*, b.name_canonical AS brand_name
            FROM brand_disputes bd
            JOIN brands b ON b.id = bd.brand_id
            WHERE ($1::text IS NULL OR bd.status = $1)
            ORDER BY bd.submitted_at ASC
            LIMIT $2
        """, status, limit)
    return [_dispute_row_to_model(r) for r in rows]


@admin_router.post("/disputes/{dispute_id}/review")
async def review_dispute(
    dispute_id: int,
    body: DisputeReview,
    admin: CurrentUser = Depends(_require_admin),
):
    valid = {"resolved_removed", "resolved_kept", "resolved_flagged"}
    if body.outcome not in valid:
        raise HTTPException(400, f"outcome must be one of {valid}")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM brand_disputes WHERE id = $1", dispute_id
        )
        if not row:
            raise HTTPException(404, "Dispute not found")

        await conn.execute("""
            UPDATE brand_disputes SET
                status         = $1,
                resolver_notes = $2,
                resolved_at    = NOW()
            WHERE id = $3
        """, body.outcome, body.resolver_notes, dispute_id)

        # If resolved_removed, flag the enforcement record
        if body.outcome == "resolved_removed" and row["enforcement_record_id"]:
            await conn.execute("""
                UPDATE enforcement_records SET confidence_score = 0.0
                WHERE id = $1
            """, row["enforcement_record_id"])

        # If no more open disputes for this brand, clear the flag
        remaining = await conn.fetchval("""
            SELECT COUNT(*) FROM brand_disputes
            WHERE brand_id = $1 AND status = 'pending'
        """, row["brand_id"])

        if remaining == 0:
            await conn.execute("""
                UPDATE agg_brand_safety_profile
                SET under_dispute = FALSE
                WHERE brand_id = $1
            """, row["brand_id"])

        await conn.execute("""
            INSERT INTO audit_log (user_id, action, resource, metadata)
            VALUES ($1, 'dispute_reviewed', 'brand_disputes', $2::jsonb)
        """, admin.user_id, f'{{"dispute_id": {dispute_id}, "outcome": "{body.outcome}"}}')

    return {"dispute_id": dispute_id, "outcome": body.outcome, "message": "Dispute resolved"}


# ============================================================
# FRAUD ADMIN ROUTES
# ============================================================

@admin_router.get("/fraud/labs", response_model=list[LabFraudSummary])
async def fraud_labs(
    flagged_only: bool = True,
    limit: int = 50,
    admin: CurrentUser = Depends(_require_admin),
):
    """Return labs with reliability scores, optionally filtered to flagged only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, tier, state,
                   reliability_score, pass_rate, deviation_z_score,
                   flagged_suspicious, flag_reason, last_evaluated
            FROM labs
            WHERE ($1 = FALSE OR flagged_suspicious = TRUE)
            ORDER BY reliability_score ASC NULLS LAST
            LIMIT $2
        """, flagged_only, limit)

    return [
        LabFraudSummary(
            lab_id             = r["id"],
            lab_name           = r["name"],
            lab_tier           = r["tier"],
            state              = r["state"],
            reliability_score  = float(r["reliability_score"]) if r["reliability_score"] else None,
            pass_rate          = float(r["pass_rate"]) if r["pass_rate"] else None,
            deviation_z_score  = float(r["deviation_z_score"]) if r["deviation_z_score"] else None,
            flagged_suspicious = r["flagged_suspicious"],
            flag_reason        = r["flag_reason"],
            last_evaluated     = str(r["last_evaluated"]) if r["last_evaluated"] else None,
        )
        for r in rows
    ]


@admin_router.get("/fraud/records", response_model=list[FraudRecordSummary])
async def fraud_records(
    min_fraud_score: float = 0.20,
    limit: int = 100,
    admin: CurrentUser = Depends(_require_admin),
):
    """Return enforcement records with fraud signals above threshold."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                er.id, er.test_date::text, er.raw_value_ppb,
                er.fraud_score, er.fraud_flags, er.value_is_round, er.lab_flagged,
                c.name_canonical  AS commodity,
                cnt.name_canonical AS contaminant,
                d.name_canonical  AS district,
                l.name            AS lab_name
            FROM enforcement_records er
            JOIN commodities c    ON c.id = er.commodity_id
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            LEFT JOIN districts d ON d.id = er.district_id
            LEFT JOIN labs l      ON l.id = er.lab_id
            WHERE er.fraud_score >= $1
              AND er.is_duplicate = FALSE
            ORDER BY er.fraud_score DESC
            LIMIT $2
        """, min_fraud_score, limit)

    import json
    return [
        FraudRecordSummary(
            record_id    = r["id"],
            test_date    = r["test_date"],
            commodity    = r["commodity"],
            contaminant  = r["contaminant"],
            value_ppb    = float(r["raw_value_ppb"]),
            district     = r["district"],
            lab_name     = r["lab_name"],
            fraud_score  = float(r["fraud_score"] or 0),
            fraud_flags  = json.loads(r["fraud_flags"]) if r["fraud_flags"] else [],
            value_is_round = r["value_is_round"],
            lab_flagged  = r["lab_flagged"],
        )
        for r in rows
    ]
