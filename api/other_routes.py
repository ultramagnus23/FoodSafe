"""
FoodSafe India — Search, FMCG, Insurance Routes
Adapted from other_routes.py to use asyncpg pool.
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool

search_router = APIRouter()
fmcg_router = APIRouter()
insurance_router = APIRouter()

# ---- Search ----
class SearchResult(BaseModel):
    type: str
    id: int
    name: str
    risk_score: Optional[float]
    n_tests: Optional[int]

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
        for r in comm_rows:
            results.append(SearchResult(type="commodity", id=r["id"], name=r["name_canonical"],
                risk_score=float(r["risk_score"]) if r["risk_score"] else None, n_tests=r["n_tests"]))

        brand_rows = await conn.fetch("""
            SELECT b.id, b.name_canonical, agg.risk_score, agg.n_tests
            FROM brands b
            LEFT JOIN agg_brand_safety_profile agg ON agg.brand_id = b.id
            WHERE b.name_canonical ILIKE $1
            LIMIT 10
        """, f"%{q}%")
        for r in brand_rows:
            results.append(SearchResult(type="brand", id=r["id"], name=r["name_canonical"],
                risk_score=float(r["risk_score"]) if r["risk_score"] else None, n_tests=r["n_tests"]))
    return results

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
