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

logger = logging.getLogger("foodsafe.routes.risk")

risk_router = APIRouter()

DISCLAIMER = (
    "Statistical model estimate based on public enforcement data. "
    "Not a laboratory test result. Not medical or legal advice."
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
    disclaimer:        str


class MapDataPoint(BaseModel):
    district_id:    int
    district_name:  str
    state:          str
    latitude:       Optional[float]
    longitude:      Optional[float]
    risk_score:     Optional[float]
    n_tests:        int


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
                   top_contaminants, last_updated
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
        disclaimer        = DISCLAIMER,
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
    inference_label = (
        "Tested: based on direct enforcement records"
        if inference_type == "direct_test"
        else "Inferred from supply chain data — no direct test on this product"
        if inference_type == "propagated"
        else "Insufficient data for this brand/commodity combination"
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
        supply_chain      = [],   # populated by supply_chain.py in production
        enforcement_events = events,
        disclaimer        = DISCLAIMER,
    )


# ============================================================
# MAP DATA (heatmap for frontend)
# ============================================================

@risk_router.get("/map", response_model=list[MapDataPoint])
async def map_data(
    commodity_id: int = 1,
    user: CurrentUser = Depends(get_current_user),
):
    """Return latest risk scores for all districts for a given commodity."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (agg.district_id)
                d.id AS district_id,
                d.name_canonical AS district_name,
                d.state,
                d.latitude,
                d.longitude,
                agg.risk_score,
                agg.n_tests
            FROM agg_district_commodity_risk agg
            JOIN districts d ON d.id = agg.district_id
            WHERE agg.commodity_id = $1
              AND agg.risk_score IS NOT NULL
            ORDER BY agg.district_id, agg.quarter DESC
            """,
            commodity_id,
        )

    return [
        MapDataPoint(
            district_id   = r["district_id"],
            district_name = r["district_name"],
            state         = r["state"],
            latitude      = float(r["latitude"]) if r["latitude"] else None,
            longitude     = float(r["longitude"]) if r["longitude"] else None,
            risk_score    = float(r["risk_score"]) if r["risk_score"] else None,
            n_tests       = r["n_tests"] or 0,
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
