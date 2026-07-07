"""
FoodSafe India — Consumer Report Intake (H2.4)
POST /v1/reports              submit a report (public, no auth)
GET  /v1/admin/reports        list reports (admin only)
PATCH /v1/admin/reports/{id}  publish/reject a report (admin only)

Consumer reports are a distinct, low-credibility, high-volume signal —
never auto-published, never surfaced with the same visual weight as a
lab-verified enforcement record, and never used to name a brand as unsafe.
They queue for admin review before any public surfacing (defamation
safeguard: a rejected report never appears anywhere).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_utils import CurrentUser
from api.db import get_pool
from api.routes.disputes import _require_admin

logger = logging.getLogger("foodsafe.routes.reports")

reports_router = APIRouter()
admin_reports_router = APIRouter()


class ReportSubmit(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    reporter_email: Optional[str] = None
    commodity_id: Optional[int] = None
    district_id: Optional[int] = None
    brand_id: Optional[int] = None
    contaminant_suspected: Optional[str] = Field(None, max_length=200)


class ReportOut(BaseModel):
    id: int
    submitted_at: str
    description: str
    reporter_email: Optional[str]
    commodity_id: Optional[int]
    district_id: Optional[int]
    brand_id: Optional[int]
    contaminant_suspected: Optional[str]
    review_status: str
    reviewer_notes: Optional[str]


class ReportReview(BaseModel):
    action: str  # 'publish' | 'reject'
    reviewer_notes: Optional[str] = None


def _row_to_model(row) -> ReportOut:
    return ReportOut(
        id=row["id"],
        submitted_at=str(row["submitted_at"]),
        description=row["description"],
        reporter_email=row["reporter_email"],
        commodity_id=row["commodity_id"],
        district_id=row["district_id"],
        brand_id=row["brand_id"],
        contaminant_suspected=row["contaminant_suspected"],
        review_status=row["review_status"],
        reviewer_notes=row["reviewer_notes"],
    )


@reports_router.post("", status_code=201)
async def submit_report(body: ReportSubmit):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO consumer_reports
                (description, reporter_email, commodity_id, district_id, brand_id, contaminant_suspected)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, submitted_at
            """,
            body.description, body.reporter_email, body.commodity_id,
            body.district_id, body.brand_id, body.contaminant_suspected,
        )
    return {
        "report_id": row["id"],
        "submitted_at": str(row["submitted_at"]),
        "status": "pending",
        "message": "Report received. It will be reviewed before appearing anywhere on the platform.",
    }


@admin_reports_router.get("/reports", response_model=list[ReportOut])
async def admin_list_reports(
    status: Optional[str] = "pending",
    limit: int = 50,
    admin: CurrentUser = Depends(_require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM consumer_reports
            WHERE ($1::text IS NULL OR review_status = $1)
            ORDER BY submitted_at ASC
            LIMIT $2
            """,
            status, limit,
        )
    return [_row_to_model(r) for r in rows]


@admin_reports_router.patch("/reports/{report_id}")
async def review_report(
    report_id: int,
    body: ReportReview,
    admin: CurrentUser = Depends(_require_admin),
):
    if body.action not in ("publish", "reject"):
        raise HTTPException(400, "action must be 'publish' or 'reject'")
    new_status = "published" if body.action == "publish" else "rejected"

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM consumer_reports WHERE id = $1", report_id)
        if not row:
            raise HTTPException(404, "Report not found")

        await conn.execute(
            """UPDATE consumer_reports
               SET review_status = $1, reviewed_by = $2, reviewed_at = NOW(), reviewer_notes = $3
               WHERE id = $4""",
            new_status, admin.user_id, body.reviewer_notes, report_id,
        )
        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, metadata) VALUES ($1, $2, 'consumer_reports', $3::jsonb)",
            admin.user_id, f"report_{body.action}", f'{{"report_id": {report_id}}}',
        )
    return {"report_id": report_id, "status": new_status}
