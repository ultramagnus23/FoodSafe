"""
FoodSafe India — Risk Routes
GET /v1/risk/district/{district_id}/commodity/{commodity_id}
GET /v1/risk/brand/{brand_id}/product/{product_id}/district/{district_id}
GET /v1/risk/map  — district-level heatmap data (all districts, one commodity)
GET /v1/risk/alerts — recent national enforcement events
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool
from api.provenance import (
    ProvenanceSummary,
    EMPTY_PROVENANCE,
    fetch_provenance,
    fetch_provenance_by_district,
)

logger = logging.getLogger("foodsafe.routes.risk")

risk_router = APIRouter()

DISCLAIMER = (
    "Statistical model estimate based on public enforcement data. "
    "Not a laboratory test result. Not medical or legal advice."
)


def build_disclaimer(commodity: Optional[str] = None, district: Optional[str] = None) -> str:
    """Legal disclaimer required on every risk/disease response. Geographic
    framing only — never names a brand, manufacturer, or batch."""
    scope = ""
    if commodity and district:
        scope = f" for {commodity} sourced from {district}"
    elif commodity:
        scope = f" for {commodity}"
    return (
        f"Statistical estimate based on public enforcement records{scope}. "
        "Not a product test result. Not a verdict on any specific brand, "
        "manufacturer, or batch. Not medical or legal advice."
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class EnforcementEvent(BaseModel):
    test_date:       str
    contaminant:     str
    value_ppb:       float
    legal_limit_ppb: Optional[float]
    pass_fail:       Optional[bool]
    source_url:      Optional[str]
    source_type:     str
    lab_name:        Optional[str]


class DistrictRiskResponse(BaseModel):
    district_id:       int
    district_name:     str
    state:             str
    commodity_id:      int
    commodity_name:    str
    risk_score:        Optional[float]
    ci_lower:          Optional[float]
    ci_upper:          Optional[float]
    n_tests:           int
    fail_rate:         Optional[float]
    top_factors:       list[dict]
    top_contaminants:  list[dict]
    enforcement_events: list[EnforcementEvent]
    inference_type:    str   # "direct_test" | "insufficient_data"
    codex_compliant_fraction: Optional[float]
    eu_compliant_fraction:    Optional[float]
    twi_exceedance_fraction:  Optional[float]
    fssai_vs_codex_flag:      Optional[bool]
    provenance:        ProvenanceSummary
    disclaimer:        str
    last_updated:      Optional[str]


class BrandRiskResponse(BaseModel):
    brand_id:          int
    brand_name:        str
    commodity_id:      int
    commodity_name:    str
    district_id:       int
    district_name:     str
    estimated_ppb:     Optional[float]
    risk_score:        Optional[float]
    ci_lower:          Optional[float]
    ci_upper:          Optional[float]
    n_tests:           int
    inference_type:    str   # "direct_test" | "propagated" | "insufficient_data"
    inference_label:   str
    supply_chain:      list[dict]
    enforcement_events: list[EnforcementEvent]
    provenance:        ProvenanceSummary
    disclaimer:        str


class MapDataPoint(BaseModel):
    district_id:    int
    district_name:  str
    state:          str
    latitude:       Optional[float]
    longitude:      Optional[float]
    risk_score:     Optional[float]
    n_tests:        int
    provenance:     ProvenanceSummary


class AlertEvent(BaseModel):
    id:              int
    test_date:       str
    commodity:       str
    contaminant:     str
    value_ppb:       float
    legal_limit_ppb: Optional[float]
    district:        Optional[str]
    state:           Optional[str]
    brand:           Optional[str]
    source_type:     str
    source_url:      Optional[str]


# ============================================================
# DISTRICT RISK
# ============================================================

@risk_router.get("/district/{district_id}/commodity/{commodity_id}", response_model=DistrictRiskResponse)
async def district_risk(
    district_id:  int,
    commodity_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        # District + commodity info
        district = await conn.fetchrow(
            "SELECT id, name_canonical, state, latitude, longitude, "
            "water_quality_index, industrial_proximity_score "
            "FROM districts WHERE id = $1",
            district_id,
        )
        if not district:
            raise HTTPException(404, "District not found")

        commodity = await conn.fetchrow(
            "SELECT id, name_canonical FROM commodities WHERE id = $1",
            commodity_id,
        )
        if not commodity:
            raise HTTPException(404, "Commodity not found")

        # Aggregated risk from latest quarter
        agg = await conn.fetchrow(
            """
            SELECT risk_score, ci_lower, ci_upper, n_tests, fail_rate,
                   top_contaminants, last_updated,
                   codex_compliant_fraction, eu_compliant_fraction,
                   twi_exceedance_fraction, fssai_vs_codex_flag
            FROM agg_district_commodity_risk
            WHERE district_id = $1 AND commodity_id = $2
            ORDER BY quarter DESC LIMIT 1
            """,
            district_id, commodity_id,
        )

        # Recent enforcement events (last 24 months)
        events_rows = await conn.fetch(
            """
            SELECT
                er.test_date::text,
                cnt.name_canonical  AS contaminant,
                er.raw_value_ppb,
                er.legal_limit_ppb,
                er.pass_fail,
                er.source_url,
                er.source_type,
                l.name              AS lab_name
            FROM enforcement_records er
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            LEFT JOIN labs l ON l.id = er.lab_id
            WHERE
                er.district_id = $1
                AND er.commodity_id = $2
                AND er.confidence_score >= 0.75
                AND er.is_duplicate = FALSE
                AND er.test_date >= NOW() - INTERVAL '24 months'
            ORDER BY er.test_date DESC
            LIMIT 50
            """,
            district_id, commodity_id,
        )

        provenance = await fetch_provenance(
            conn, "district_id = $1 AND commodity_id = $2", district_id, commodity_id,
        )

    events = [
        EnforcementEvent(
            test_date       = r["test_date"],
            contaminant     = r["contaminant"],
            value_ppb       = float(r["raw_value_ppb"]),
            legal_limit_ppb = float(r["legal_limit_ppb"]) if r["legal_limit_ppb"] else None,
            pass_fail       = r["pass_fail"],
            source_url      = r["source_url"],
            source_type     = r["source_type"],
            lab_name        = r["lab_name"],
        )
        for r in events_rows
    ]

    n_tests = agg["n_tests"] if agg else len(events)
    inference_type = "direct_test" if n_tests >= 3 else "insufficient_data"

    import json
    top_contaminants = []
    if agg and agg["top_contaminants"]:
        raw_tc = agg["top_contaminants"]
        if isinstance(raw_tc, str):
            top_contaminants = json.loads(raw_tc)
        else:
            top_contaminants = list(raw_tc) if raw_tc else []

    # Contributing risk factors, derived from the aggregation + district
    # context. These are the real signals the score is built from (the
    # aggregation methodology lives in models/aggregate.py).
    top_factors: list[dict] = []
    if agg and agg["fail_rate"] is not None:
        top_factors.append({
            "factor": "12-month fail rate",
            "value": round(float(agg["fail_rate"]) * 100, 1),
            "unit": "%",
            "effect": "increases risk",
        })
    top_factors.append({
        "factor": "sample size",
        "value": n_tests or 0,
        "unit": "tests",
        "effect": "narrows confidence interval",
    })
    if district["water_quality_index"] is not None:
        top_factors.append({
            "factor": "water quality index",
            "value": float(district["water_quality_index"]),
            "unit": "0-100 (higher = cleaner)",
            "effect": "lower water quality raises risk",
        })
    if district["industrial_proximity_score"] is not None:
        top_factors.append({
            "factor": "industrial proximity",
            "value": float(district["industrial_proximity_score"]),
            "unit": "0-100 (higher = more industrial)",
            "effect": "higher proximity raises risk",
        })
    top_factors = top_factors[:3]

    return DistrictRiskResponse(
        district_id       = district_id,
        district_name     = district["name_canonical"],
        state             = district["state"],
        commodity_id      = commodity_id,
        commodity_name    = commodity["name_canonical"],
        risk_score        = float(agg["risk_score"]) if agg and agg["risk_score"] is not None else None,
        ci_lower          = float(agg["ci_lower"]) if agg and agg["ci_lower"] is not None else None,
        ci_upper          = float(agg["ci_upper"]) if agg and agg["ci_upper"] is not None else None,
        n_tests           = n_tests or 0,
        fail_rate         = float(agg["fail_rate"]) if agg and agg["fail_rate"] is not None else None,
        top_factors       = top_factors,
        top_contaminants  = top_contaminants,
        enforcement_events = events,
        inference_type    = inference_type,
        codex_compliant_fraction = float(agg["codex_compliant_fraction"]) if agg and agg["codex_compliant_fraction"] is not None else None,
        eu_compliant_fraction    = float(agg["eu_compliant_fraction"]) if agg and agg["eu_compliant_fraction"] is not None else None,
        twi_exceedance_fraction  = float(agg["twi_exceedance_fraction"]) if agg and agg["twi_exceedance_fraction"] is not None else None,
        fssai_vs_codex_flag      = agg["fssai_vs_codex_flag"] if agg else None,
        provenance        = provenance,
        disclaimer        = build_disclaimer(commodity["name_canonical"], district["name_canonical"]),
        last_updated      = str(agg["last_updated"]) if agg else None,
    )


# ============================================================
# BRAND RISK
# ============================================================

@risk_router.get("/brand/{brand_id}/product/{commodity_id}/district/{district_id}", response_model=BrandRiskResponse)
async def brand_risk(
    brand_id:     int,
    commodity_id: int,
    district_id:  int,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        brand = await conn.fetchrow("SELECT id, name_canonical FROM brands WHERE id = $1", brand_id)
        if not brand:
            raise HTTPException(404, "Brand not found")

        commodity = await conn.fetchrow("SELECT id, name_canonical FROM commodities WHERE id = $1", commodity_id)
        if not commodity:
            raise HTTPException(404, "Commodity not found")

        district = await conn.fetchrow("SELECT id, name_canonical FROM districts WHERE id = $1", district_id)
        if not district:
            raise HTTPException(404, "District not found")

        # Brand aggregated profile
        agg = await conn.fetchrow(
            """
            SELECT n_tests, n_failures, avg_ppb, risk_score, ci_lower, ci_upper, inference_type
            FROM agg_brand_safety_profile
            WHERE brand_id = $1 AND commodity_id = $2
            """,
            brand_id, commodity_id,
        )

        # Direct enforcement records for this brand
        events_rows = await conn.fetch(
            """
            SELECT
                er.test_date::text,
                cnt.name_canonical AS contaminant,
                er.raw_value_ppb,
                er.legal_limit_ppb,
                er.pass_fail,
                er.source_url,
                er.source_type,
                l.name             AS lab_name
            FROM enforcement_records er
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            LEFT JOIN labs l ON l.id = er.lab_id
            WHERE
                er.brand_id = $1
                AND er.commodity_id = $2
                AND er.confidence_score >= 0.75
                AND er.is_duplicate = FALSE
            ORDER BY er.test_date DESC
            LIMIT 30
            """,
            brand_id, commodity_id,
        )

        provenance = await fetch_provenance(
            conn, "brand_id = $1 AND commodity_id = $2", brand_id, commodity_id,
        )

    events = [
        EnforcementEvent(
            test_date       = r["test_date"],
            contaminant     = r["contaminant"],
            value_ppb       = float(r["raw_value_ppb"]),
            legal_limit_ppb = float(r["legal_limit_ppb"]) if r["legal_limit_ppb"] else None,
            pass_fail       = r["pass_fail"],
            source_url      = r["source_url"],
            source_type     = r["source_type"],
            lab_name        = r["lab_name"],
        )
        for r in events_rows
    ]

    inference_type = agg["inference_type"] if agg else "insufficient_data"
    supply_chain: list[dict] = []

    # No direct test evidence — try the Bayesian supply-chain propagation
    # model (models/supply_chain.py) before falling back to "insufficient
    # data". We never fabricate a brand risk number without either a direct
    # test or an actual supply-chain graph edge backing it.
    if not agg or not agg["n_tests"]:
        propagated = await _try_supply_chain_propagation(brand["name_canonical"], commodity_id)
        if propagated is not None:
            supply_chain = propagated["subgraph"]
            if propagated["estimate"].get("inference_type") not in (None, "insufficient_data"):
                inference_type = propagated["estimate"]["inference_type"]

    inference_label = (
        "Tested: based on direct enforcement records"
        if inference_type == "direct_test"
        else "Inferred from supply chain data — no direct test on this product"
        if inference_type in ("propagated", "mixed")
        else "No supply chain mapping available for this brand. Search by commodity and district instead."
    )

    return BrandRiskResponse(
        brand_id          = brand_id,
        brand_name        = brand["name_canonical"],
        commodity_id      = commodity_id,
        commodity_name    = commodity["name_canonical"],
        district_id       = district_id,
        district_name     = district["name_canonical"],
        estimated_ppb     = float(agg["avg_ppb"]) if agg and agg["avg_ppb"] else None,
        risk_score        = float(agg["risk_score"]) if agg and agg["risk_score"] else None,
        ci_lower          = float(agg["ci_lower"]) if agg and agg["ci_lower"] else None,
        ci_upper          = float(agg["ci_upper"]) if agg and agg["ci_upper"] else None,
        n_tests           = agg["n_tests"] if agg else 0,
        inference_type    = inference_type,
        inference_label   = inference_label,
        supply_chain      = supply_chain,
        enforcement_events = events,
        provenance        = provenance,
        disclaimer        = build_disclaimer(commodity["name_canonical"], district["name_canonical"]),
    )


async def _try_supply_chain_propagation(brand_name: str, commodity_id: int) -> Optional[dict]:
    """
    Runs the sync psycopg2-based SupplyChainGraph (models/supply_chain.py) in
    a worker thread so it doesn't block the event loop. Returns None if there
    is no supply-chain node for this brand/commodity to propagate from —
    supply_chain_nodes/edges are frequently unseeded, and that's a legitimate
    "no data" case, not an error.
    """
    import asyncio

    def _run() -> Optional[dict]:
        from pipeline.config import pg_connect
        from models.supply_chain import SupplyChainGraph

        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM supply_chain_nodes WHERE node_type = 'brand' "
                    "AND commodity_id = %s AND name ILIKE %s LIMIT 1",
                    (commodity_id, brand_name),
                )
                row = cur.fetchone()
            if not row:
                return None
            brand_node_id = row[0]

            graph = SupplyChainGraph()
            graph.load_from_db(conn, commodity_id=commodity_id)
            graph.attach_measurements(conn, commodity_id=commodity_id)
            graph.propagate()
            return {
                "estimate": graph.get_brand_estimate(brand_node_id),
                "subgraph": graph.subgraph_for_display(brand_node_id),
            }
        finally:
            conn.close()

    return await asyncio.to_thread(_run)


# ============================================================
# MAP DATA (heatmap for frontend)
# ============================================================

@risk_router.get("/map/quarters", response_model=list[str])
async def map_quarters(commodity_id: int = 1, user: CurrentUser = Depends(get_current_user)):
    """Quarters with at least one real aggregation row for this commodity,
    oldest first — the range a time scrubber can honestly step through.
    Never fabricated: this is exactly what agg_district_commodity_risk has."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT quarter FROM agg_district_commodity_risk WHERE commodity_id = $1 ORDER BY quarter",
            commodity_id,
        )
    return [r["quarter"] for r in rows]


@risk_router.get("/map", response_model=list[MapDataPoint])
async def map_data(
    commodity_id: int = 1,
    quarter: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
):
    """Return risk scores for all districts for a given commodity, at the
    given quarter (e.g. '2025-Q3') or the latest available if omitted."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # LEFT JOIN so districts with no aggregation row for this commodity
        # still appear (risk_score/n_tests null) — the frontend renders
        # those as a distinct "no data" marker instead of silently omitting
        # them, which would otherwise look identical to "we checked and it's
        # fine" rather than "we have never tested this".
        rows = await conn.fetch(
            """
            SELECT
                d.id AS district_id,
                d.name_canonical AS district_name,
                d.state,
                d.latitude,
                d.longitude,
                latest.risk_score,
                latest.n_tests
            FROM districts d
            LEFT JOIN LATERAL (
                SELECT risk_score, n_tests
                FROM agg_district_commodity_risk agg
                WHERE agg.district_id = d.id AND agg.commodity_id = $1
                  AND ($2::text IS NULL OR agg.quarter = $2)
                ORDER BY agg.quarter DESC LIMIT 1
            ) latest ON TRUE
            """,
            commodity_id, quarter,
        )
        provenance_by_district = await fetch_provenance_by_district(conn, commodity_id)

    return [
        MapDataPoint(
            district_id   = r["district_id"],
            district_name = r["district_name"],
            state         = r["state"],
            latitude      = float(r["latitude"]) if r["latitude"] else None,
            longitude     = float(r["longitude"]) if r["longitude"] else None,
            risk_score    = float(r["risk_score"]) if r["risk_score"] else None,
            n_tests       = r["n_tests"] or 0,
            provenance    = provenance_by_district.get(r["district_id"], EMPTY_PROVENANCE),
        )
        for r in rows
    ]


# ============================================================
# RECENT ALERTS
# ============================================================

@risk_router.get("/alerts", response_model=list[AlertEvent])
async def recent_alerts(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
):
    """Recent enforcement failures — national ticker feed."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                er.id,
                er.test_date::text,
                c.name_canonical  AS commodity,
                cnt.name_canonical AS contaminant,
                er.raw_value_ppb,
                er.legal_limit_ppb,
                d.name_canonical  AS district,
                er.state,
                b.name_canonical  AS brand,
                er.source_type,
                er.source_url
            FROM enforcement_records er
            JOIN commodities c   ON c.id = er.commodity_id
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            LEFT JOIN districts d ON d.id = er.district_id
            LEFT JOIN brands b   ON b.id = er.brand_id
            WHERE
                er.pass_fail = FALSE
                AND er.confidence_score >= 0.75
                AND er.is_duplicate = FALSE
            ORDER BY er.test_date DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        AlertEvent(
            id              = r["id"],
            test_date       = r["test_date"],
            commodity       = r["commodity"],
            contaminant     = r["contaminant"],
            value_ppb       = float(r["raw_value_ppb"]),
            legal_limit_ppb = float(r["legal_limit_ppb"]) if r["legal_limit_ppb"] else None,
            district        = r["district"],
            state           = r["state"],
            brand           = r["brand"],
            source_type     = r["source_type"],
            source_url      = r["source_url"],
        )
        for r in rows
    ]
