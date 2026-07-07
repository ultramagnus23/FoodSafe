"""
FoodSafe India — Search, FMCG, Insurance Routes
Adapted from other_routes.py to use asyncpg pool.
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth_utils import get_current_user, require_tier, CurrentUser
from api.db import get_pool
from api.provenance import (
    ProvenanceSummary,
    EMPTY_PROVENANCE,
    fetch_provenance_by_commodity,
    fetch_provenance_by_brand,
)

search_router = APIRouter()
fmcg_router = APIRouter()
insurance_router = APIRouter()
meta_router = APIRouter()

# ---- Reference lists (public — no auth; used to populate UI selectors) ----

class DistrictOut(BaseModel):
    id: int
    name: str
    state: str

class CommodityOut(BaseModel):
    id: int
    name: str
    category: str

class BrandOut(BaseModel):
    id: int
    name: str

@meta_router.get("/districts", response_model=list[DistrictOut])
async def list_districts():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name_canonical, state FROM districts ORDER BY state, name_canonical"
        )
    return [DistrictOut(id=r["id"], name=r["name_canonical"], state=r["state"]) for r in rows]

@meta_router.get("/commodities", response_model=list[CommodityOut])
async def list_commodities():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name_canonical, category FROM commodities ORDER BY id"
        )
    return [CommodityOut(id=r["id"], name=r["name_canonical"], category=r["category"]) for r in rows]

@meta_router.get("/brands", response_model=list[BrandOut])
async def list_brands(limit: int = 200):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name_canonical FROM brands ORDER BY name_canonical LIMIT $1", limit
        )
    return [BrandOut(id=r["id"], name=r["name_canonical"]) for r in rows]

# ---- Search ----
class SearchResult(BaseModel):
    type: str
    id: int
    name: str
    risk_score: Optional[float]
    n_tests: Optional[int]
    provenance: ProvenanceSummary

@search_router.get("", response_model=list[SearchResult])
async def search(q: str, district_id: Optional[int] = None, user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    results = []
    async with pool.acquire() as conn:
        comm_rows = await conn.fetch("""
            SELECT c.id, c.name_canonical, agg.risk_score, agg.n_tests
            FROM commodities c
            LEFT JOIN agg_district_commodity_risk agg ON agg.commodity_id = c.id
              AND ($2::int IS NULL OR agg.district_id = $2)
            WHERE c.name_canonical ILIKE $1 OR $1 ILIKE ANY(c.aliases::text[])
            LIMIT 10
        """, f"%{q}%", district_id)
        commodity_provenance = await fetch_provenance_by_commodity(conn, [r["id"] for r in comm_rows])
        for r in comm_rows:
            results.append(SearchResult(type="commodity", id=r["id"], name=r["name_canonical"],
                risk_score=float(r["risk_score"]) if r["risk_score"] else None, n_tests=r["n_tests"],
                provenance=commodity_provenance.get(r["id"], EMPTY_PROVENANCE)))

        brand_rows = await conn.fetch("""
            SELECT b.id, b.name_canonical, agg.risk_score, agg.n_tests
            FROM brands b
            LEFT JOIN agg_brand_safety_profile agg ON agg.brand_id = b.id
            WHERE b.name_canonical ILIKE $1
            LIMIT 10
        """, f"%{q}%")
        brand_provenance = await fetch_provenance_by_brand(conn, [r["id"] for r in brand_rows])
        for r in brand_rows:
            results.append(SearchResult(type="brand", id=r["id"], name=r["name_canonical"],
                risk_score=float(r["risk_score"]) if r["risk_score"] else None, n_tests=r["n_tests"],
                provenance=brand_provenance.get(r["id"], EMPTY_PROVENANCE)))
    return results

class AutocompleteResult(BaseModel):
    id: int
    name: str
    type: str

@search_router.get("/autocomplete", response_model=list[AutocompleteResult])
async def autocomplete(q: str):
    """Lightweight, unauthenticated typeahead — pg_trgm similarity across
    commodities, districts, and contaminants. Capped at 5 results total."""
    if not q or len(q) < 2:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            (SELECT id, name_canonical AS name, 'commodity' AS type,
                    similarity(name_canonical, $1) AS score
             FROM commodities WHERE name_canonical % $1)
            UNION ALL
            (SELECT id, name_canonical AS name, 'district' AS type,
                    similarity(name_canonical, $1) AS score
             FROM districts WHERE name_canonical % $1)
            UNION ALL
            (SELECT id, name_canonical AS name, 'contaminant' AS type,
                    similarity(name_canonical, $1) AS score
             FROM contaminants WHERE name_canonical % $1)
            ORDER BY score DESC
            LIMIT 5
            """,
            q,
        )
    return [AutocompleteResult(id=r["id"], name=r["name"], type=r["type"]) for r in rows]

# ---- FMCG ----
class MarketGap(BaseModel):
    district_id: int
    district_name: str
    state: str
    commodity: str
    risk_score: float
    n_tests: int
    brand_count: int

@fmcg_router.get("/market-gaps", response_model=list[MarketGap])
async def market_gaps(state: Optional[str]=None, category: Optional[str]=None, limit: int=20,
                      user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT d.id AS district_id, d.name_canonical AS district_name, d.state,
                   c.name_canonical AS commodity, agg.risk_score, agg.n_tests,
                   COUNT(DISTINCT er.brand_id) AS brand_count
            FROM agg_district_commodity_risk agg
            JOIN districts d ON d.id = agg.district_id
            JOIN commodities c ON c.id = agg.commodity_id
            LEFT JOIN enforcement_records er ON er.district_id = agg.district_id
              AND er.commodity_id = agg.commodity_id AND er.brand_id IS NOT NULL
            WHERE agg.risk_score < 30 AND agg.n_tests >= 5
              AND ($1::text IS NULL OR d.state = $1)
              AND ($2::text IS NULL OR c.category = $2)
            GROUP BY d.id, d.name_canonical, d.state, c.name_canonical, agg.risk_score, agg.n_tests
            ORDER BY brand_count ASC, agg.risk_score ASC LIMIT $3
        """, state, category, limit)
    return [MarketGap(district_id=r["district_id"], district_name=r["district_name"], state=r["state"],
                      commodity=r["commodity"], risk_score=float(r["risk_score"]),
                      n_tests=r["n_tests"], brand_count=r["brand_count"]) for r in rows]

class ProcurementRiskRequest(BaseModel):
    commodity_id: int
    district_ids: list[int]
    volume_weights: Optional[list[float]] = None  # same length as district_ids; defaults to equal weight

class DistrictContribution(BaseModel):
    district_id: int
    district_name: str
    weight: float
    risk_score: Optional[float]
    n_tests: int
    codex_compliant_fraction: Optional[float]
    top_contaminant: Optional[str]

class ProcurementRiskResponse(BaseModel):
    commodity_id: int
    commodity_name: str
    blended_risk_score: Optional[float]
    blended_ci: Optional[list[float]]
    by_district: list[DistrictContribution]
    inference_type: str
    disclaimer: str

@fmcg_router.post("/procurement-risk", response_model=ProcurementRiskResponse)
async def procurement_risk(req: ProcurementRiskRequest, user: CurrentUser = Depends(require_tier("fmcg", "insurance"))):
    """Blended sourcing risk for procuring a commodity across multiple
    districts, weighted by volume share — e.g. "60% of our groundnut comes
    from Bikaner, 40% from Hardoi"."""
    if not req.district_ids:
        raise HTTPException(400, "district_ids must not be empty")
    weights = req.volume_weights or [1.0 / len(req.district_ids)] * len(req.district_ids)
    if len(weights) != len(req.district_ids):
        raise HTTPException(400, "volume_weights must be the same length as district_ids")

    pool = get_pool()
    async with pool.acquire() as conn:
        commodity = await conn.fetchrow("SELECT id, name_canonical FROM commodities WHERE id = $1", req.commodity_id)
        if not commodity:
            raise HTTPException(404, "Commodity not found")

        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (agg.district_id)
                d.id AS district_id, d.name_canonical AS district_name,
                agg.risk_score, agg.ci_lower, agg.ci_upper, agg.n_tests,
                agg.codex_compliant_fraction, agg.top_contaminants
            FROM agg_district_commodity_risk agg
            JOIN districts d ON d.id = agg.district_id
            WHERE agg.commodity_id = $1 AND agg.district_id = ANY($2::int[])
            ORDER BY agg.district_id, agg.quarter DESC
            """,
            req.commodity_id, req.district_ids,
        )
    by_district_id = {r["district_id"]: r for r in rows}

    import json
    contributions = []
    weighted_risk_sum = 0.0
    weighted_ci_lo_sum = 0.0
    weighted_ci_hi_sum = 0.0
    total_weight_with_data = 0.0
    any_data = False

    for district_id, weight in zip(req.district_ids, weights):
        r = by_district_id.get(district_id)
        if r is None or r["risk_score"] is None:
            contributions.append(DistrictContribution(
                district_id=district_id, district_name=(r["district_name"] if r else "Unknown"),
                weight=weight, risk_score=None, n_tests=(r["n_tests"] if r else 0),
                codex_compliant_fraction=None, top_contaminant=None,
            ))
            continue
        any_data = True
        top_contaminants = json.loads(r["top_contaminants"]) if isinstance(r["top_contaminants"], str) else (r["top_contaminants"] or [])
        top_contaminant = top_contaminants[0]["name"] if top_contaminants else None
        risk = float(r["risk_score"])
        weighted_risk_sum += risk * weight
        weighted_ci_lo_sum += float(r["ci_lower"] or risk) * weight
        weighted_ci_hi_sum += float(r["ci_upper"] or risk) * weight
        total_weight_with_data += weight
        contributions.append(DistrictContribution(
            district_id=district_id, district_name=r["district_name"], weight=weight,
            risk_score=risk, n_tests=r["n_tests"],
            codex_compliant_fraction=float(r["codex_compliant_fraction"]) if r["codex_compliant_fraction"] is not None else None,
            top_contaminant=top_contaminant,
        ))

    blended = None
    blended_ci = None
    if any_data and total_weight_with_data > 0:
        blended = round(weighted_risk_sum / total_weight_with_data, 2)
        blended_ci = [round(weighted_ci_lo_sum / total_weight_with_data, 2),
                       round(weighted_ci_hi_sum / total_weight_with_data, 2)]

    return ProcurementRiskResponse(
        commodity_id=req.commodity_id,
        commodity_name=commodity["name_canonical"],
        blended_risk_score=blended,
        blended_ci=blended_ci,
        by_district=contributions,
        inference_type="direct_test" if any_data else "insufficient_data",
        disclaimer=(
            f"Statistical estimate based on public enforcement records for "
            f"{commodity['name_canonical']} sourced from the specified districts. "
            "Not a product test result. Not a verdict on any specific brand, "
            "manufacturer, or batch. Not medical or legal advice."
        ),
    )

# ---- Insurance ----
class DistrictRiskProfile(BaseModel):
    district_id: int
    district_name: str
    state: str
    contaminant: str
    risk_score: float
    ci_lower: float
    ci_upper: float
    n_tests: int
    fail_rate: float
    water_quality_index: Optional[float]
    industrial_proximity_score: Optional[float]

@insurance_router.get("/district-risk-profile", response_model=list[DistrictRiskProfile])
async def district_risk_profile(districts: str, contaminants: Optional[str]=None,
                                 user: CurrentUser = Depends(get_current_user)):
    district_ids = [int(x) for x in districts.split(",") if x.strip().isdigit()]
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT d.id AS district_id, d.name_canonical AS district_name, d.state,
                   cnt.name_canonical AS contaminant,
                   agg.risk_score, agg.ci_lower, agg.ci_upper, agg.n_tests, agg.fail_rate,
                   d.water_quality_index, d.industrial_proximity_score
            FROM agg_district_commodity_risk agg
            JOIN districts d ON d.id = agg.district_id
            JOIN enforcement_records er ON er.district_id = agg.district_id AND er.commodity_id = agg.commodity_id
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            WHERE d.id = ANY($1) AND agg.risk_score IS NOT NULL
            GROUP BY d.id, d.name_canonical, d.state, cnt.name_canonical,
                     agg.risk_score, agg.ci_lower, agg.ci_upper, agg.n_tests, agg.fail_rate,
                     d.water_quality_index, d.industrial_proximity_score
            ORDER BY agg.risk_score DESC LIMIT 100
        """, district_ids)
    return [DistrictRiskProfile(district_id=r["district_id"], district_name=r["district_name"],
                                 state=r["state"], contaminant=r["contaminant"],
                                 risk_score=float(r["risk_score"]), ci_lower=float(r["ci_lower"] or 0),
                                 ci_upper=float(r["ci_upper"] or 0), n_tests=r["n_tests"],
                                 fail_rate=float(r["fail_rate"] or 0),
                                 water_quality_index=float(r["water_quality_index"]) if r["water_quality_index"] else None,
                                 industrial_proximity_score=float(r["industrial_proximity_score"]) if r["industrial_proximity_score"] else None)
            for r in rows]
