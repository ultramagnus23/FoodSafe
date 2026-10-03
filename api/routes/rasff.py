"""
FoodSafe India — EU RASFF routes
GET /v1/rasff/summary    counts by year, hazard category, product category, top hazards
GET /v1/rasff            notifications (with their hazards), filterable and paginated
GET /v1/rasff/countries  every origin country side by side (notifications, serious share, hazard mix)

`origin` (ISO-2, default IN; 'ALL' for every origin) filters by country of
origin. The tables hold every origin since schema_migration_023; every query
here filters explicitly, so the default view is still India's record.

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


_ORIGIN = r"^([A-Z]{2}|ALL)$"
_N_FILTER = "($1 = 'ALL' OR $1 = ANY(n.origin_countries))"


@rasff_router.get("/summary", response_model=RasffSummary)
async def rasff_summary(origin: str = Query("IN", pattern=_ORIGIN)):
    pool = get_pool()
    async with pool.acquire() as conn:
        head = await conn.fetchrow(
            f"""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE has_detail) AS d,
                      MIN(validation_date)::text AS first, MAX(validation_date)::text AS last
               FROM rasff_notifications n WHERE {_N_FILTER}""", origin)
        hazards = await conn.fetchval(
            f"""SELECT COUNT(*) FROM rasff_hazards h JOIN rasff_notifications n USING (notif_id)
                WHERE {_N_FILTER}""", origin)
        by_year = await conn.fetch(
            f"""SELECT EXTRACT(YEAR FROM validation_date)::int::text AS k, COUNT(*) AS n
               FROM rasff_notifications n WHERE {_N_FILTER} GROUP BY 1 ORDER BY 1""", origin)
        by_cat = await conn.fetch(
            f"""SELECT COALESCE(h.hazard_category, 'unclassified') AS c, COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE h.exceedance_ratio IS NOT NULL OR h.exceeds_limit IS NOT NULL) AS m,
                      COUNT(*) FILTER (WHERE h.exceeds_limit) AS x
               FROM rasff_hazards h JOIN rasff_notifications n USING (notif_id)
               WHERE {_N_FILTER} GROUP BY 1 ORDER BY n DESC""", origin)
        by_product = await conn.fetch(
            f"""SELECT COALESCE(product_category, 'unclassified') AS k, COUNT(*) AS n
               FROM rasff_notifications n WHERE {_N_FILTER} GROUP BY 1 ORDER BY n DESC LIMIT 12""", origin)
        top = await conn.fetch(
            f"""SELECT LOWER(h.hazard) AS k, COUNT(*) AS n FROM rasff_hazards h JOIN rasff_notifications n USING (notif_id)
                WHERE {_N_FILTER} GROUP BY 1 ORDER BY n DESC, k LIMIT 15""", origin)
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
    origin: str = Query("IN", pattern=_ORIGIN),
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
          AND ($7 = 'ALL' OR $7 = ANY(n.origin_countries))
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM rasff_notifications n {where.replace('$7', '$5')}", hc, pc, year, exceeds_only, origin)
        rows = await conn.fetch(
            f"""SELECT n.notif_id, n.reference, n.validation_date::text AS validation_date, n.subject,
                       n.notifying_country, n.classification, n.risk_decision, n.product_category,
                       n.product_name, n.basis, n.actions_taken, n.has_detail, n.source_url
                FROM rasff_notifications n {where}
                ORDER BY n.validation_date DESC, n.notif_id DESC
                LIMIT $5 OFFSET $6""",
            hc, pc, year, exceeds_only, limit, offset, origin,
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


class CountryRow(BaseModel):
    origin: str
    notifications: int
    serious: int
    serious_share: Optional[float]
    border_rejections: int
    first_year: Optional[int]
    last_year: Optional[int]
    top_hazard_categories: list[CountBy]
    top_hazards: list[CountBy]


class CountriesResponse(BaseModel):
    countries: list[CountryRow]
    total_notifications: int
    scope: list[str]


@rasff_router.get("/countries", response_model=CountriesResponse)
async def rasff_countries(min_notifications: int = Query(20, ge=1, le=10000), year: Optional[int] = Query(None, ge=2000,
                                                                                                           le=2100)):
    """Every origin country side by side: how many EU notifications its food drew,
    how many were classed 'serious', and its hazard mix. A notification counts for
    each origin it lists. Counts reflect EU import volumes and targeting as much as
    food safety in the origin country — they are not prevalence and not a ranking of
    whose food is safer."""
    pool = get_pool()
    async with pool.acquire() as conn:
        heads = await conn.fetch(
            """SELECT o AS origin, COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE risk_decision = 'serious') AS serious,
                      COUNT(*) FILTER (WHERE risk_decision IS NOT NULL) AS decided,
                      COUNT(*) FILTER (WHERE classification ILIKE 'border rejection%') AS rejections,
                      MIN(EXTRACT(YEAR FROM validation_date))::int AS fy, MAX(EXTRACT(YEAR FROM validation_date))::int AS ly
               FROM rasff_notifications, unnest(origin_countries) AS o
               WHERE ($1::int IS NULL OR EXTRACT(YEAR FROM validation_date) = $1)
               GROUP BY o HAVING COUNT(*) >= $2 ORDER BY n DESC""", year, min_notifications)
        cats = await conn.fetch(
            """SELECT o AS origin, COALESCE(h.hazard_category, 'unclassified') AS k, COUNT(DISTINCT n.notif_id) AS c
               FROM rasff_notifications n CROSS JOIN LATERAL unnest(n.origin_countries) AS o
               JOIN rasff_hazards h ON h.notif_id = n.notif_id
               WHERE ($1::int IS NULL OR EXTRACT(YEAR FROM n.validation_date) = $1)
               GROUP BY 1, 2""", year)
        hz = await conn.fetch(
            """SELECT o AS origin, LOWER(h.hazard) AS k, COUNT(DISTINCT n.notif_id) AS c
               FROM rasff_notifications n CROSS JOIN LATERAL unnest(n.origin_countries) AS o
               JOIN rasff_hazards h ON h.notif_id = n.notif_id
               WHERE ($1::int IS NULL OR EXTRACT(YEAR FROM n.validation_date) = $1)
               GROUP BY 1, 2""", year)
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM rasff_notifications WHERE ($1::int IS NULL OR EXTRACT(YEAR FROM validation_date) = $1)",
            year)
    by_cat: dict[str, list] = {}
    for r in cats:
        by_cat.setdefault(r["origin"], []).append(CountBy(key=r["k"], notifications=r["c"]))
    by_hz: dict[str, list] = {}
    for r in hz:
        by_hz.setdefault(r["origin"], []).append(CountBy(key=r["k"], notifications=r["c"]))
    out = []
    for h in heads:
        o = h["origin"]
        out.append(CountryRow(
            origin=o, notifications=h["n"], serious=h["serious"],
            serious_share=round(h["serious"] / h["decided"], 4) if h["decided"] else None,
            border_rejections=h["rejections"], first_year=h["fy"], last_year=h["ly"],
            top_hazard_categories=sorted(by_cat.get(o, []), key=lambda c: (-c.notifications, c.key))[:6],
            top_hazards=sorted(by_hz.get(o, []), key=lambda c: (-c.notifications, c.key))[:6]))
    return CountriesResponse(countries=out, total_notifications=total or 0,
                             scope=["EU/EEA border and market checks, risk-targeted: counts reflect trade volume and "
                                    "targeting, not the safety of food eaten in the origin country.",
                                    *SOURCES["rasff"].scope[1:]])
