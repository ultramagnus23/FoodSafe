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

class LocalityOut(BaseModel):
    id: int
    name: str
    district_id: int
    district_name: str
    state: str
    pincodes: list[str]
    latitude: Optional[float]
    longitude: Optional[float]

class CommissionerOut(BaseModel):
    state: str
    commissioner_name: Optional[str]
    address: Optional[str]
    contact: Optional[str]
    email: Optional[str]
    nodal_officer: Optional[str]
    source_url: str

class LabOut(BaseModel):
    id: int
    name: str
    tier: int
    state: Optional[str]
    accreditation: Optional[str]
    accreditation_ref: Optional[str]
    source_url: Optional[str]

class NationalEnforcementOut(BaseModel):
    fiscal_year: str
    samples_analyzed: Optional[int]
    samples_non_conforming: Optional[int]
    non_conforming_unsafe: Optional[int]
    non_conforming_substandard: Optional[int]
    non_conforming_labelling: Optional[int]
    civil_cases_launched: Optional[int]
    civil_cases_decided: Optional[int]
    civil_cases_convictions: Optional[int]
    civil_penalty_amount: Optional[int]
    criminal_cases_launched: Optional[int]
    criminal_cases_decided: Optional[int]
    criminal_cases_convictions: Optional[int]
    criminal_penalty_amount: Optional[int]
    criminal_acquittals: Optional[int]
    total_penalty_amount: Optional[int]
    source_url: str

class StateEnforcementOut(BaseModel):
    state: str
    fiscal_year: str
    samples_analyzed: Optional[int]
    civil_cases_decided_penalty: Optional[int]
    criminal_cases_convictions: Optional[int]
    licenses_cancelled: Optional[int]
    source_question_no: int
    source_question_subject: Optional[str]
    answered_date: Optional[str]
    source_url: str

@meta_router.get("/districts", response_model=list[DistrictOut])
async def list_districts():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name_canonical, state FROM districts ORDER BY state, name_canonical"
        )
    return [DistrictOut(id=r["id"], name=r["name_canonical"], state=r["state"]) for r in rows]

@meta_router.get("/localities", response_model=list[LocalityOut])
async def list_localities(district_id: Optional[int] = None, pincode: Optional[str] = None):
    """Sub-district localities (e.g. Juhu, Vile Parle, Churchgate within
    Mumbai) — see schema_migration_009.sql. Optionally filter by parent
    district or resolve a single pincode to its locality (used by the
    report form to turn a pincode into a locality_id client-side)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT l.id, l.name_canonical, l.parent_district_id, d.name_canonical AS district_name,
                   d.state, l.pincodes, l.latitude, l.longitude
            FROM localities l
            JOIN districts d ON d.id = l.parent_district_id
            WHERE ($1::int IS NULL OR l.parent_district_id = $1)
              AND ($2::text IS NULL OR $2 = ANY(l.pincodes))
            ORDER BY d.state, d.name_canonical, l.name_canonical
            """,
            district_id, pincode,
        )
    return [
        LocalityOut(
            id=r["id"], name=r["name_canonical"], district_id=r["parent_district_id"],
            district_name=r["district_name"], state=r["state"], pincodes=list(r["pincodes"]),
            latitude=float(r["latitude"]) if r["latitude"] is not None else None,
            longitude=float(r["longitude"]) if r["longitude"] is not None else None,
        )
        for r in rows
    ]

@meta_router.get("/commissioners", response_model=list[CommissionerOut])
async def list_commissioners(state: Optional[str] = None):
    """Real State/UT Commissioner of Food Safety contact directory, scraped
    from fssai.gov.in — see schema_migration_011.sql and
    pipeline/sources/fssai_commissioners.py. Escalation/contact metadata,
    not enforcement data — who to reach in a given state, not what was found
    there."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT state, commissioner_name, address, contact, email, nodal_officer, source_url
               FROM state_commissioners
               WHERE ($1::text IS NULL OR state ILIKE $1)
               ORDER BY state""",
            state,
        )
    return [CommissionerOut(**dict(r)) for r in rows]

@meta_router.get("/labs", response_model=list[LabOut])
async def list_labs(state: Optional[str] = None, tier: Optional[int] = None):
    """FSSAI-notified food testing laboratories — NABL-accredited Primary
    labs (tier 1), statutory Referral labs (tier 2), and National Reference
    Labs (tier 1) — plus a handful of pre-existing synthetic demo rows.
    source_url IS NULL is the discriminator for those synthetic rows; see
    schema_migration_012.sql and pipeline/sources/fssai_labs.py."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, tier, state, accreditation, accreditation_ref, source_url
               FROM labs
               WHERE ($1::text IS NULL OR state ILIKE $1)
                 AND ($2::int IS NULL OR tier = $2)
               ORDER BY state NULLS LAST, name""",
            state, tier,
        )
    return [LabOut(**dict(r)) for r in rows]

@meta_router.get("/state-enforcement", response_model=list[StateEnforcementOut])
async def list_state_enforcement(state: Optional[str] = None, fiscal_year: Optional[str] = None):
    """Real State/UT x fiscal-year FSSAI enforcement counts (samples
    analysed, civil/criminal cases, license cancellations), sourced from
    Lok Sabha written answers — not FSSAI's own portal, which publishes no
    structured state-level data. See schema_migration_013.sql and
    pipeline/sources/loksabha_qa.py. Two different Parliamentary questions
    can each independently report a given (state, year) — both are kept,
    distinguished by source_question_no, rather than merged."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT state, fiscal_year, samples_analyzed, civil_cases_decided_penalty,
                      criminal_cases_convictions, licenses_cancelled, source_question_no,
                      source_question_subject, answered_date::text, source_url
               FROM state_enforcement_annual
               WHERE ($1::text IS NULL OR state ILIKE $1)
                 AND ($2::text IS NULL OR fiscal_year = $2)
               ORDER BY state, fiscal_year DESC""",
            state, fiscal_year,
        )
    return [StateEnforcementOut(**dict(r)) for r in rows]

@meta_router.get("/national-enforcement", response_model=list[NationalEnforcementOut])
async def list_national_enforcement():
    """Real, national-level FSSAI enforcement metrics, one row per fiscal
    year, sourced directly from each year's FSSAI Annual Report PDF's own
    "Progress on enforcement metrics" table (not a third party, not
    Parliament — FSSAI's own annual publication). See
    schema_migration_014.sql and pipeline/sources/fssai_annual_report.py.
    Some columns are null for years where that report didn't break out
    that particular figure (report format changed over the years)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT fiscal_year, samples_analyzed, samples_non_conforming, non_conforming_unsafe,
                      non_conforming_substandard, non_conforming_labelling, civil_cases_launched,
                      civil_cases_decided, civil_cases_convictions, civil_penalty_amount,
                      criminal_cases_launched, criminal_cases_decided, criminal_cases_convictions,
                      criminal_penalty_amount, criminal_acquittals, total_penalty_amount, source_url
               FROM national_enforcement_annual
               ORDER BY fiscal_year"""
        )
    return [NationalEnforcementOut(**dict(r)) for r in rows]

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
