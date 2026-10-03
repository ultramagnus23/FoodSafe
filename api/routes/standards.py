"""
FoodSafe India — food standards (India vs EU / Codex / US) and the hazard ->
health knowledge base.

  GET /v1/standards/summary              what is loaded, from which document versions, headline gaps
  GET /v1/standards/compare              India vs others, one row per (hazard, food); filterable
  GET /v1/standards/foods                the foods that can be compared, with counts
  GET /v1/standards/food/{food_key}      every regulated hazard for one food, all four rule-books
  GET /v1/standards/hazard/{hazard_key}  one hazard: every limit, safety thresholds, health effects
  GET /v1/hazards                        the knowledge base (hazard, class, IARC group, outcomes)
  GET /v1/hazards/{hazard_key}           one hazard's health effects with sources

Public reference data (no auth). Built by pipeline/sources/standards_*.py,
pipeline/sources/hazard_kb.py and models/standards_compare.py (see their
docstrings for how each value is read and when it is left empty).

Reading a comparison: ratio_in_* = India's limit / the other rule-book's.
> 1 means India allows MORE residue. *_basis says where a value came from:
'specific' (a row naming the food), 'group' (a food-group row covering it),
'eu_default' (no EU residue definition, so the EU's general 0.01 mg/kg
applies), 'none' (Codex: no standard; US: no tolerance, so no residue is
legal), 'not_loaded'. A legal limit is a regulatory line, not a safety
verdict; the health-based guidance values (ADI/ARfD) are served next to it.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool

standards_router = APIRouter()
hazards_router = APIRouter()

_KEY = r"^[a-z0-9_]{1,80}$"
JURISDICTION_NAMES = {"IN": "India (FSSAI)", "EU": "European Union", "CODEX": "Codex Alimentarius",
                      "US": "United States (EPA)"}
CAVEATS = [
    "A maximum residue limit is set from good agricultural practice and checked against safety thresholds; "
    "a higher limit is not proof that food is unsafe, and a lower one is not proof that it is safe.",
    "EU limits are loaded for ~50 India-relevant foods only; foods outside that set show 'not_loaded'.",
    "US crop-group tolerances are mapped for the main groups only; 'none' for the US means no tolerance was "
    "found for the commodity or its mapped groups.",
    "Residue definitions differ between rule-books for some substances (e.g. dithiocarbamates); those pairs "
    "are flagged 'basis_mismatch' and get no ratio.",
]


def _f(v):
    return None if v is None else float(v)


class Snapshot(BaseModel):
    jurisdiction: str
    document_title: str
    document_url: str
    document_version: Optional[str]
    document_sha256: Optional[str]
    rows_loaded: int
    loaded_at: str


class SummaryOut(BaseModel):
    jurisdictions: dict[str, str]
    rows_by_jurisdiction: dict[str, dict[str, int]]
    snapshots: list[Snapshot]
    comparisons: int
    india_higher_than_eu: int
    india_higher_than_codex: int
    india_higher_than_us: int
    no_us_tolerance: int
    no_codex_standard: int
    eu_default_applies: int
    india_internal_conflict: int
    # Why India's limit is above the EU's, per pair (models/standards_compare.eu_gap_reason):
    # eu_gap_not_approved / _no_use_on_food / _never_assessed / _at_loq / _both_permit,
    # plus 'contaminant' for contaminant maximum levels.
    india_higher_than_eu_why: dict[str, int] = {}
    india_pesticides: int
    india_pesticides_not_approved_in_eu: int
    hazards_in_kb: int
    health_effect_rows: int
    caveats: list[str]


@standards_router.get("/summary", response_model=SummaryOut)
async def standards_summary():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT jurisdiction, standard_type, COUNT(*) AS n FROM food_standards GROUP BY 1, 2")
        snaps = await conn.fetch(
            """SELECT DISTINCT ON (jurisdiction, standard_types) jurisdiction, document_title, document_url,
                      document_version, document_sha256, rows_loaded, loaded_at::text AS loaded_at
               FROM standards_snapshots ORDER BY jurisdiction, standard_types, loaded_at DESC""")
        c = await conn.fetchrow(
            """SELECT COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE 'india_higher_than_eu' = ANY(flags)) AS hi_eu,
                      COUNT(*) FILTER (WHERE 'india_higher_than_codex' = ANY(flags)) AS hi_cx,
                      COUNT(*) FILTER (WHERE 'india_higher_than_us' = ANY(flags)) AS hi_us,
                      COUNT(*) FILTER (WHERE 'no_us_tolerance' = ANY(flags)) AS no_us,
                      COUNT(*) FILTER (WHERE 'no_codex_standard' = ANY(flags)) AS no_cx,
                      COUNT(*) FILTER (WHERE eu_basis = 'eu_default') AS eu_def,
                      COUNT(*) FILTER (WHERE 'india_internal_conflict' = ANY(flags)) AS conflict
               FROM standards_comparison""")
        why = await conn.fetch(
            """SELECT CASE WHEN standard_type = 'contaminant_ml' THEN 'contaminant'
                           ELSE (SELECT f FROM unnest(flags) f WHERE starts_with(f, 'eu_gap_') LIMIT 1) END AS reason,
                      COUNT(*) AS n
               FROM standards_comparison WHERE 'india_higher_than_eu' = ANY(flags) GROUP BY 1""")
        in_pest = await conn.fetchval(
            """SELECT COUNT(DISTINCT hazard_key) FROM food_standards
               WHERE jurisdiction='IN' AND standard_type='pesticide_mrl'""")
        not_eu = await conn.fetchval(
            """SELECT COUNT(DISTINCT in_substance_key) FROM standards_comparison
               WHERE standard_type='pesticide_mrl' AND eu_status = 'Not approved'""")
        kb = await conn.fetchval("SELECT COUNT(*) FROM hazards WHERE summary IS NOT NULL")
        eff = await conn.fetchval("SELECT COUNT(*) FROM hazard_health_effects")
    by: dict[str, dict[str, int]] = {}
    for r in rows:
        by.setdefault(r["jurisdiction"], {})[r["standard_type"]] = r["n"]
    return SummaryOut(
        jurisdictions=JURISDICTION_NAMES, rows_by_jurisdiction=by,
        snapshots=[Snapshot(**dict(s)) for s in snaps],
        comparisons=c["n"] or 0, india_higher_than_eu=c["hi_eu"] or 0, india_higher_than_codex=c["hi_cx"] or 0,
        india_higher_than_us=c["hi_us"] or 0, no_us_tolerance=c["no_us"] or 0, no_codex_standard=c["no_cx"] or 0,
        eu_default_applies=c["eu_def"] or 0, india_internal_conflict=c["conflict"] or 0,
        india_higher_than_eu_why={(r["reason"] or "unclassified"): r["n"] for r in why},
        india_pesticides=in_pest or 0, india_pesticides_not_approved_in_eu=not_eu or 0,
        hazards_in_kb=kb or 0, health_effect_rows=eff or 0, caveats=CAVEATS,
    )


class LimitCell(BaseModel):
    value_mg_per_kg: Optional[float]
    basis: str
    ratio_india_over: Optional[float] = None
    rows: list[dict[str, Any]] = []


class ComparisonOut(BaseModel):
    standard_type: str
    hazard_key: str
    hazard_name: str
    food_key: str
    food_name: Optional[str]
    india: LimitCell
    eu: LimitCell
    codex: LimitCell
    us: LimitCell
    flags: list[str]
    eu_status: Optional[str]
    iarc_group: Optional[str]


class CompareResponse(BaseModel):
    results: list[ComparisonOut]
    total: int
    caveats: list[str]


def _food_names() -> dict[str, str]:
    from pipeline.sources.standards_foods import FOODS
    return {k: v[0] for k, v in FOODS.items()}


def _cmp_out(r, names: dict[str, str], with_rows: bool) -> ComparisonOut:
    d = r["detail"] if isinstance(r["detail"], dict) else json.loads(r["detail"])

    def cell(j, value, basis, ratio=None):
        return LimitCell(value_mg_per_kg=_f(value), basis=basis, ratio_india_over=_f(ratio),
                         rows=(d.get(j) or {}).get("rows", []) if with_rows else [])

    return ComparisonOut(
        standard_type=r["standard_type"], hazard_key=r["hazard_key"], hazard_name=r["hazard_name"],
        food_key=r["food_key"], food_name=names.get(r["food_key"]),
        india=cell("IN", r["in_value"], (d.get("IN") or {}).get("basis", "none")),
        eu=cell("EU", r["eu_value"], r["eu_basis"], r["ratio_in_eu"]),
        codex=cell("CODEX", r["codex_value"], r["codex_basis"], r["ratio_in_codex"]),
        us=cell("US", r["us_value"], r["us_basis"], r["ratio_in_us"]),
        flags=list(r["flags"]), eu_status=r["eu_status"], iarc_group=r["iarc_group"],
    )


_CMP_SELECT = "SELECT c.* FROM standards_comparison c"


@standards_router.get("/compare", response_model=CompareResponse)
async def compare(
    food: Optional[str] = Query(None, pattern=_KEY),
    hazard: Optional[str] = Query(None, pattern=_KEY),
    flag: Optional[str] = Query(None, pattern=r"^[a-z_]{1,40}$"),
    standard_type: Optional[str] = Query(None, pattern=r"^(pesticide_mrl|contaminant_ml)$"),
    sort: str = Query("ratio_eu", pattern=r"^(ratio_eu|ratio_codex|ratio_us|hazard|food)$"),
    with_rows: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
):
    order = {"ratio_eu": "c.ratio_in_eu DESC NULLS LAST, c.hazard_key, c.food_key",
             "ratio_codex": "c.ratio_in_codex DESC NULLS LAST, c.hazard_key, c.food_key",
             "ratio_us": "c.ratio_in_us DESC NULLS LAST, c.hazard_key, c.food_key",
             "hazard": "c.hazard_key, c.food_key", "food": "c.food_key, c.hazard_key"}[sort]
    where = """WHERE ($1::text IS NULL OR c.food_key = $1) AND ($2::text IS NULL OR c.hazard_key = $2)
                 AND ($3::text IS NULL OR $3 = ANY(c.flags)) AND ($4::text IS NULL OR c.standard_type = $4)"""
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM standards_comparison c {where}", food, hazard, flag,
                                    standard_type)
        rows = await conn.fetch(f"{_CMP_SELECT} {where} ORDER BY {order} LIMIT $5 OFFSET $6",
                                food, hazard, flag, standard_type, limit, offset)
    names = _food_names()
    return CompareResponse(results=[_cmp_out(r, names, with_rows) for r in rows], total=total or 0, caveats=CAVEATS)


class FoodOut(BaseModel):
    food_key: str
    name: str
    food_group: str
    hazards_compared: int
    india_higher_than_eu: int


@standards_router.get("/foods", response_model=list[FoodOut])
async def foods():
    from pipeline.sources.standards_foods import foods_table
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT food_key, COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE 'india_higher_than_eu' = ANY(flags)) AS hi
               FROM standards_comparison GROUP BY food_key""")
    counts = {r["food_key"]: (r["n"], r["hi"]) for r in rows}
    return [FoodOut(**f, hazards_compared=counts.get(f["food_key"], (0, 0))[0],
                    india_higher_than_eu=counts.get(f["food_key"], (0, 0))[1]) for f in foods_table()]


@standards_router.get("/food/{food_key}", response_model=CompareResponse)
async def food_detail(food_key: str):
    if not __import__("re").fullmatch(_KEY, food_key):
        raise HTTPException(422, "bad food key")
    names = _food_names()
    if food_key not in names:
        raise HTTPException(404, "unknown food")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"{_CMP_SELECT} WHERE c.food_key = $1 ORDER BY c.standard_type DESC, "
                                "c.ratio_in_eu DESC NULLS LAST, c.hazard_key", food_key)
    return CompareResponse(results=[_cmp_out(r, names, True) for r in rows], total=len(rows), caveats=CAVEATS)


class RefValue(BaseModel):
    body: str
    value_type: str
    value: Optional[float]
    unit: Optional[str]
    raw_text: str
    year: Optional[int]
    source_ref: Optional[str]
    source_url: str


class HealthEffect(BaseModel):
    outcome_key: str
    outcome: str
    icd10: Optional[str]
    organ_system: str
    exposure: str
    onset: Optional[str]
    vulnerable_groups: list[str]
    evidence: str
    source_title: str
    source_url: str


class HazardOut(BaseModel):
    hazard_key: str
    name: str
    hazard_class: str
    cas_number: Optional[str]
    iarc_group: Optional[str]
    iarc_agent: Optional[str]
    eu_status: Optional[str]
    eu_category: Optional[str]
    summary: Optional[str]
    aliases: list[str]
    reference_values: list[RefValue]
    health_effects: list[HealthEffect]


class HazardStandardsOut(BaseModel):
    hazard: Optional[HazardOut]
    limits: list[dict[str, Any]]
    comparisons: list[ComparisonOut]


async def _hazard(conn, key: str) -> Optional[HazardOut]:
    h = await conn.fetchrow("SELECT * FROM hazards WHERE hazard_key = $1", key)
    refs = await conn.fetch("SELECT * FROM hazard_reference_values WHERE hazard_key = $1 ORDER BY body, value_type", key)
    eff = await conn.fetch("SELECT * FROM hazard_health_effects WHERE hazard_key = $1 ORDER BY exposure, outcome", key)
    if not h and not refs and not eff:
        return None
    return HazardOut(
        hazard_key=key, name=(h["name"] if h else key), hazard_class=(h["hazard_class"] if h else "pesticide"),
        cas_number=h["cas_number"] if h else None, iarc_group=h["iarc_group"] if h else None,
        iarc_agent=h["iarc_agent"] if h else None, eu_status=h["eu_status"] if h else None,
        eu_category=h["eu_category"] if h else None, summary=h["summary"] if h else None,
        aliases=list(h["aliases"]) if h else [],
        reference_values=[RefValue(**{k: (_f(v) if k == "value" else v) for k, v in dict(r).items()
                                      if k in RefValue.model_fields}) for r in refs],
        health_effects=[HealthEffect(**{k: v for k, v in dict(e).items() if k in HealthEffect.model_fields})
                        for e in eff],
    )


@standards_router.get("/hazard/{hazard_key}", response_model=HazardStandardsOut)
async def hazard_standards(hazard_key: str):
    if not __import__("re").fullmatch(_KEY, hazard_key):
        raise HTTPException(422, "bad hazard key")
    pool = get_pool()
    async with pool.acquire() as conn:
        hz = await _hazard(conn, hazard_key)
        limits = await conn.fetch(
            """SELECT jurisdiction, standard_type, hazard_raw, food_raw, food_code, food_keys, food_match, limit_raw,
                      limit_mg_per_kg::float AS limit_mg_per_kg, limit_unit, at_loq, limit_basis, legal_reference,
                      source_url, source_page, applicability
               FROM food_standards WHERE hazard_key = $1
               ORDER BY jurisdiction, food_raw LIMIT 3000""", hazard_key)
        cmp = await conn.fetch(f"{_CMP_SELECT} WHERE c.hazard_key = $1 ORDER BY c.ratio_in_eu DESC NULLS LAST", hazard_key)
    if not hz and not limits:
        raise HTTPException(404, "unknown hazard")
    names = _food_names()
    return HazardStandardsOut(hazard=hz, limits=[dict(r) for r in limits],
                              comparisons=[_cmp_out(r, names, False) for r in cmp])


class HazardListItem(BaseModel):
    hazard_key: str
    name: str
    hazard_class: str
    iarc_group: Optional[str]
    outcomes: list[str]


@hazards_router.get("", response_model=list[HazardListItem])
async def list_hazards(hazard_class: Optional[str] = Query(None, pattern=r"^[a-z_]{1,40}$"),
                       curated_only: bool = True):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT h.hazard_key, h.name, h.hazard_class, h.iarc_group,
                      COALESCE(array_agg(DISTINCT e.outcome) FILTER (WHERE e.outcome IS NOT NULL), '{}') AS outcomes
               FROM hazards h LEFT JOIN hazard_health_effects e USING (hazard_key)
               WHERE ($1::text IS NULL OR h.hazard_class = $1) AND (NOT $2 OR h.summary IS NOT NULL)
               GROUP BY 1, 2, 3, 4 ORDER BY h.hazard_class, h.name""", hazard_class, curated_only)
    return [HazardListItem(**dict(r)) for r in rows]


@hazards_router.get("/{hazard_key}", response_model=HazardOut)
async def get_hazard(hazard_key: str):
    if not __import__("re").fullmatch(_KEY, hazard_key):
        raise HTTPException(422, "bad hazard key")
    pool = get_pool()
    async with pool.acquire() as conn:
        hz = await _hazard(conn, hazard_key)
    if not hz:
        raise HTTPException(404, "unknown hazard")
    return hz
