"""
FoodSafe India — Admin Data Management Routes
GET   /v1/admin/stats               platform-wide counters
GET   /v1/admin/records             filtered enforcement record list
PATCH /v1/admin/records/{id}        manual confidence override (verify/flag)
POST  /v1/admin/aggregate           recompute agg_district_commodity_risk/agg_brand_safety_profile
POST  /v1/admin/disease-burden      recompute disease_burden_estimates/exposure_alerts
GET   /v1/admin/pipeline-runs       last run per ingest source (H1.3 scraper health)

Gated behind users.is_superuser (see _require_admin in api/routes/disputes.py).

Ingestion triggers (FSSAI/USFDA scrapers) are intentionally NOT exposed here —
they depend on the heavy pipeline stack (Playwright, spaCy...) deliberately
kept out of requirements-api.txt so Render's web service stays light; those
already run on a schedule via .github/workflows/ingest.yml. Live SSE log
streaming is also out of scope for this pass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import get_pool
from api.routes.disputes import _require_admin
from api.auth_utils import CurrentUser

logger = logging.getLogger("foodsafe.routes.admin_panel")

admin_panel_router = APIRouter()


class PlatformStats(BaseModel):
    total_records: int
    districts_covered: int
    commodities_tracked: int
    contaminants_tracked: int
    avg_confidence_score: Optional[float]
    records_last_30d: int
    pending_disputes: int
    flagged_labs: int
    active_alerts: int


@admin_panel_router.get("/stats", response_model=PlatformStats)
async def platform_stats(admin: CurrentUser = Depends(_require_admin)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM enforcement_records WHERE is_duplicate = FALSE AND is_retracted = FALSE) AS total_records,
                (SELECT COUNT(DISTINCT district_id) FROM enforcement_records WHERE district_id IS NOT NULL) AS districts_covered,
                (SELECT COUNT(*) FROM commodities) AS commodities_tracked,
                (SELECT COUNT(*) FROM contaminants) AS contaminants_tracked,
                (SELECT AVG(confidence_score) FROM enforcement_records WHERE is_duplicate = FALSE AND is_retracted = FALSE) AS avg_confidence_score,
                (SELECT COUNT(*) FROM enforcement_records WHERE parsed_at >= NOW() - INTERVAL '30 days') AS records_last_30d,
                (SELECT COUNT(*) FROM brand_disputes WHERE status = 'pending') AS pending_disputes,
                (SELECT COUNT(*) FROM labs WHERE flagged_suspicious = TRUE) AS flagged_labs,
                (SELECT COUNT(*) FROM exposure_alerts WHERE active = TRUE) AS active_alerts
            """
        )
    return PlatformStats(
        total_records=row["total_records"],
        districts_covered=row["districts_covered"],
        commodities_tracked=row["commodities_tracked"],
        contaminants_tracked=row["contaminants_tracked"],
        avg_confidence_score=round(float(row["avg_confidence_score"]), 3) if row["avg_confidence_score"] is not None else None,
        records_last_30d=row["records_last_30d"],
        pending_disputes=row["pending_disputes"],
        flagged_labs=row["flagged_labs"],
        active_alerts=row["active_alerts"],
    )


class RecordRow(BaseModel):
    id: int
    test_date: str
    commodity: str
    contaminant: str
    district: Optional[str]
    value_ppb: float
    pass_fail: Optional[bool]
    source_type: str
    confidence_score: float
    is_duplicate: bool


@admin_panel_router.get("/records", response_model=list[RecordRow])
async def list_records(
    source_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    is_duplicate: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    admin: CurrentUser = Depends(_require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT er.id, er.test_date::text, c.name_canonical AS commodity,
                   cnt.name_canonical AS contaminant, d.name_canonical AS district,
                   er.raw_value_ppb, er.pass_fail, er.source_type,
                   er.confidence_score, er.is_duplicate
            FROM enforcement_records er
            JOIN commodities c ON c.id = er.commodity_id
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            LEFT JOIN districts d ON d.id = er.district_id
            WHERE ($1::text IS NULL OR er.source_type = $1)
              AND ($2::numeric IS NULL OR er.confidence_score >= $2)
              AND ($3::numeric IS NULL OR er.confidence_score <= $3)
              AND ($4::boolean IS NULL OR er.is_duplicate = $4)
            ORDER BY er.test_date DESC
            LIMIT $5 OFFSET $6
            """,
            source_type, min_confidence, max_confidence, is_duplicate, limit, offset,
        )
    return [
        RecordRow(
            id=r["id"], test_date=r["test_date"], commodity=r["commodity"], contaminant=r["contaminant"],
            district=r["district"], value_ppb=float(r["raw_value_ppb"]), pass_fail=r["pass_fail"],
            source_type=r["source_type"], confidence_score=float(r["confidence_score"]), is_duplicate=r["is_duplicate"],
        )
        for r in rows
    ]


class RecordOverride(BaseModel):
    action: str  # 'verify' (boost +0.15, cap 1.0) | 'flag' (set confidence to 0.0)


@admin_panel_router.patch("/records/{record_id}")
async def override_record(record_id: int, body: RecordOverride, admin: CurrentUser = Depends(_require_admin)):
    if body.action not in ("verify", "flag"):
        raise HTTPException(400, "action must be 'verify' or 'flag'")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, confidence_score, test_date FROM enforcement_records WHERE id = $1", record_id)
        if not row:
            raise HTTPException(404, "Record not found")

        if body.action == "verify":
            new_score = min(1.0, float(row["confidence_score"]) + 0.15)
        else:
            new_score = 0.0

        await conn.execute(
            "UPDATE enforcement_records SET confidence_score = $1 WHERE id = $2 AND test_date = $3",
            new_score, record_id, row["test_date"],
        )
        await conn.execute(
            "INSERT INTO audit_log (user_id, action, resource, metadata) VALUES ($1, $2, 'enforcement_records', $3::jsonb)",
            admin.user_id, f"record_{body.action}",
            f'{{"record_id": {record_id}, "new_confidence_score": {new_score}}}',
        )
    return {"record_id": record_id, "action": body.action, "new_confidence_score": new_score}


class TriggerResult(BaseModel):
    summary: dict
    message: str


@admin_panel_router.post("/aggregate", response_model=TriggerResult)
async def trigger_aggregate(admin: CurrentUser = Depends(_require_admin)):
    def _run():
        from pipeline.config import pg_connect
        from models.aggregate import run_aggregation

        conn = pg_connect()
        try:
            return run_aggregation(conn)
        finally:
            conn.close()

    summary = await asyncio.to_thread(_run)
    return TriggerResult(summary=summary, message="Aggregation recomputed")


@admin_panel_router.post("/disease-burden", response_model=TriggerResult)
async def trigger_disease_burden(admin: CurrentUser = Depends(_require_admin)):
    def _run():
        from models.disease_burden import DiseaseBurdenEstimator

        estimator = DiseaseBurdenEstimator()
        try:
            return estimator.compute_all()
        finally:
            estimator.close()

    summary = await asyncio.to_thread(_run)
    return TriggerResult(summary=summary, message="Disease burden estimates recomputed")


class PipelineRunStatus(BaseModel):
    source: str
    status: str  # 'running' | 'success' | 'expected_failure' | 'failed' | 'never_run'
    rows_ingested: Optional[int]
    error_detail: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]


# Kept in sync with pipeline/run_and_log.py's SOURCES — the sources the
# scheduled ingest.yml actually runs.
_KNOWN_SOURCES = ["openfda", "agmarknet", "fssai_recall"]


@admin_panel_router.get("/pipeline-runs", response_model=list[PipelineRunStatus])
async def pipeline_run_status(admin: CurrentUser = Depends(_require_admin)):
    """Last run per ingest source, so the operator can tell 'FoSCoS blocked
    as expected' apart from 'openFDA broke' without reading workflow logs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (source)
                source, status, rows_ingested, error_detail,
                started_at::text, finished_at::text
            FROM pipeline_runs
            WHERE source = ANY($1::text[])
            ORDER BY source, started_at DESC
            """,
            _KNOWN_SOURCES,
        )
    by_source = {r["source"]: r for r in rows}
    return [
        PipelineRunStatus(
            source=source,
            status=(by_source[source]["status"] if source in by_source else "never_run"),
            rows_ingested=by_source[source]["rows_ingested"] if source in by_source else None,
            error_detail=by_source[source]["error_detail"] if source in by_source else None,
            started_at=by_source[source]["started_at"] if source in by_source else None,
            finished_at=by_source[source]["finished_at"] if source in by_source else None,
        )
        for source in _KNOWN_SOURCES
    ]
