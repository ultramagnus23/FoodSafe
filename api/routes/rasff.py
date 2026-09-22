"""
FoodSafe India — EU RASFF routes (India-origin food notifications)
GET /v1/rasff/summary   counts by year, hazard category, product category, top hazards
GET /v1/rasff           notifications (with their hazards), filterable and paginated

Public reference data (no auth), backed by pipeline/sources/rasff.py — the
European Commission's own public RASFF Window feed, filtered to origin = India.
See schema_migration_021.sql and api/source_registry.py.

Every response carries the source's confidence and, separately, its `scope`
limits: these are consignments checked by EU authorities (risk-targeted), not a
sample of food eaten in India, so no rate here is a prevalence.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool
from api.source_registry import SOURCES, row_confidence

rasff_router = APIRouter()

_INT4_MAX = 2_147_483_647
_MAX_OFFSET = 1_000_000


class Hazard(BaseModel):
    hazard: str
    hazard_category: Optional[str]
    result_raw: Optional[str]
    result_value: Optional[float]
    result_qualifier: Optional[str]
    result_unit: Optional[str]
    limit_value: Optional[float]
    limit_unit: Optional[str]
    exceedance_ratio: Optional[float]
    exceeds_limit: Optional[bool]
    sampling_date: Optional[str]


class Notification(BaseModel):
    notif_id: int
    reference: Optional[str]
    validation_date: str
    subject: Optional[str]
    notifying_country: Optional[str]
    classification: Optional[str]
    risk_decision: Optional[str]
    product_category: Optional[str]
    product_name: Optional[str]
    basis: Optional[str]
    actions_taken: list[str]
    has_detail: bool
    source_url: str
    hazards: list[Hazard]
    source_id: str
    confidence_level: str
    confidence_reasons: list[str]


class RasffListResponse(BaseModel):
    results: list[Notification]
    total: int
    scope: list[str]


class CountBy(BaseModel):
    key: str
    notifications: int


class HazardCategoryCount(BaseModel):
    category: str
    hazards: int
    with_measurement: int      # a result and a limit in the same unit
    exceeding_limit: int


class RasffSummary(BaseModel):
    notifications: int
    with_detail: int
    hazards: int
    first_date: Optional[str]
    last_date: Optional[str]
    by_year: list[CountBy]
    by_hazard_category: list[HazardCategoryCount]
    by_product_category: list[CountBy]
    top_hazards: list[CountBy]
    source_id: str
    confidence_level: str
    scope: list[str]
    caveats: list[str]


@rasff_router.get("/summary", response_model=RasffSummary)
async def rasff_summary():
    pool = get_pool()
    async with pool.acquire() as conn:
        head = await conn.fetchrow(
            """SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE has_detail) AS d,
                      MIN(validation_date)::text AS first, MAX(validation_date)::text AS last
               FROM rasff_notifications""")
        hazards = await conn.fetchval("SELECT COUNT(*) FROM rasff_hazards")
        by_year = await conn.fetch(
            """SELECT EXTRACT(YEAR FROM validation_date)::int::text AS k, COUNT(*) AS n
               FROM rasff_notifications GROUP BY 1 ORDER BY 1""")
        by_cat = await conn.fetch(
            """SELECT COALESCE(hazard_category, 'unclassified') AS c, COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE exceedance_ratio IS NOT NULL OR exceeds_limit IS NOT NULL) AS m,
                      COUNT(*) FILTER (WHERE exceeds_limit) AS x
               FROM rasff_hazards GROUP BY 1 ORDER BY n DESC""")
        by_product = await conn.fetch(
            """SELECT COALESCE(product_category, 'unclassified') AS k, COUNT(*) AS n
               FROM rasff_notifications GROUP BY 1 ORDER BY n DESC LIMIT 12""")
        top = await conn.fetch(
            """SELECT LOWER(hazard) AS k, COUNT(*) AS n FROM rasff_hazards GROUP BY 1 ORDER BY n DESC, k LIMIT 15""")
    src = SOURCES["rasff"]
    conf = row_confidence("rasff")
    return RasffSummary(
        notifications=head["n"] or 0, with_detail=head["d"] or 0, hazards=hazards or 0,
        first_date=head["first"], last_date=head["last"],
        by_year=[CountBy(key=r["k"], notifications=r["n"]) for r in by_year],
        by_hazard_category=[HazardCategoryCount(category=r["c"], hazards=r["n"], with_measurement=r["m"],
                                                exceeding_limit=r["x"]) for r in by_cat],
        by_product_category=[CountBy(key=r["k"], notifications=r["n"]) for r in by_product],
        top_hazards=[CountBy(key=r["k"], notifications=r["n"]) for r in top],
        source_id="rasff", confidence_level=conf.level, scope=list(src.scope), caveats=list(src.caveats),
    )


@rasff_router.get("", response_model=RasffListResponse)
async def list_rasff(
    hazard_category: Optional[str] = Query(None, max_length=80),
    product_category: Optional[str] = Query(None, max_length=80),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    exceeds_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=_MAX_OFFSET),
):
    hc = (hazard_category or "").replace("\x00", "").strip() or None
    pc = (product_category or "").replace("\x00", "").strip() or None
    where = """
        WHERE ($1::text IS NULL OR EXISTS (SELECT 1 FROM rasff_hazards h WHERE h.notif_id = n.notif_id AND h.hazard_category = $1))
          AND ($2::text IS NULL OR n.product_category = $2)
          AND ($3::int  IS NULL OR EXTRACT(YEAR FROM n.validation_date) = $3)
          AND (NOT $4 OR EXISTS (SELECT 1 FROM rasff_hazards h WHERE h.notif_id = n.notif_id AND h.exceeds_limit))
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM rasff_notifications n {where}", hc, pc, year, exceeds_only)
        rows = await conn.fetch(
            f"""SELECT n.notif_id, n.reference, n.validation_date::text AS validation_date, n.subject,
                       n.notifying_country, n.classification, n.risk_decision, n.product_category,
                       n.product_name, n.basis, n.actions_taken, n.has_detail, n.source_url
                FROM rasff_notifications n {where}
                ORDER BY n.validation_date DESC, n.notif_id DESC
                LIMIT $5 OFFSET $6""",
            hc, pc, year, exceeds_only, limit, offset,
        )
        ids = [r["notif_id"] for r in rows]
        hz = await conn.fetch(
            """SELECT notif_id, hazard, hazard_category, result_raw, result_value::float AS result_value,
                      result_qualifier, result_unit, limit_value::float AS limit_value, limit_unit,
                      exceedance_ratio::float AS exceedance_ratio, exceeds_limit, sampling_date::text AS sampling_date
               FROM rasff_hazards WHERE notif_id = ANY($1::bigint[]) ORDER BY notif_id, id""",
            ids,
        ) if ids else []
    by_notif: dict[int, list[Hazard]] = {}
    for h in hz:
        d = dict(h)
        by_notif.setdefault(d.pop("notif_id"), []).append(Hazard(**d))
    conf = row_confidence("rasff")
    return RasffListResponse(
        results=[
            Notification(**dict(r), hazards=by_notif.get(r["notif_id"], []), source_id="rasff",
                         confidence_level=conf.level, confidence_reasons=conf.reasons)
            for r in rows
        ],
        total=total or 0,
        scope=list(SOURCES["rasff"].scope),
    )
