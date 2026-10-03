"""
FoodSafe India — what recorded contamination means for health.

  GET /v1/health/profile                 outcomes implied by the hazards found in food from one origin (default IN)
  GET /v1/health/profile/compare         the same outcomes side by side for several origins
  GET /v1/health/safe-intake             grams of a food that reach a health-based guidance value
  GET /v1/health/safe-intake/rasff       that calculation for real measured findings (EU RASFF)

Profiles come from models/health_profile.py (RASFF findings x the cited
hazard -> health knowledge base); the calculator from models/safe_intake.py.
Counts are contamination FINDINGS whose hazard can cause an outcome — never
counts of illness. The safe-intake figures use one sample's measured value and
are an illustration of what a finding means, not anyone's dietary exposure.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool

health_router = APIRouter()

_ORIGIN = r"^([A-Z]{2}|ALL)$"
_KEY = r"^[a-z0-9_]{1,80}$"
PROFILE_CAVEAT = ("Counts EU border/market contamination findings whose hazard can cause each outcome, with the "
                  "evidence for each link. It is not a count of illness and not a prevalence: findings are "
                  "risk-targeted checks of exported food.")


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


class ProfileRow(BaseModel):
    outcome_key: str
    outcome: str
    organ_system: str
    exposure: str
    notifications: int
    share_of_classified: Optional[float]
    serious_notifications: int
    level_counts: dict[str, int]
    top_hazards: list[Any]
    top_products: list[Any]
    by_year: dict[str, int]
    sources: list[dict[str, str]]
    vulnerable_groups: list[str]


class ProfileOut(BaseModel):
    origin: str
    outcomes: list[ProfileRow]
    caveat: str


@health_router.get("/profile", response_model=ProfileOut)
async def profile(origin: str = Query("IN", pattern=_ORIGIN), exposure: Optional[str] = Query(
        None, pattern=r"^(acute|chronic|both)$")):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM health_outcome_profile WHERE scope_type='rasff_origin' AND scope_key=$1
                 AND ($2::text IS NULL OR exposure=$2) ORDER BY notifications DESC, outcome_key""", origin, exposure)
    return ProfileOut(origin=origin, caveat=PROFILE_CAVEAT, outcomes=[ProfileRow(
        outcome_key=r["outcome_key"], outcome=r["outcome"], organ_system=r["organ_system"], exposure=r["exposure"],
        notifications=r["notifications"], share_of_classified=float(r["share_of_classified"])
        if r["share_of_classified"] is not None else None, serious_notifications=r["serious_notifications"],
        level_counts=_j(r["level_counts"]), top_hazards=_j(r["top_hazards"]), top_products=_j(r["top_products"]),
        by_year=_j(r["by_year"]), sources=_j(r["sources"]), vulnerable_groups=list(r["vulnerable_groups"]))
        for r in rows])


class CompareOut(BaseModel):
    origins: list[str]
    outcomes: list[dict[str, Any]]      # {outcome_key, outcome, <origin>: share, ...}
    caveat: str


@health_router.get("/profile/compare", response_model=CompareOut)
async def profile_compare(origins: str = Query("IN,CN,TR,TH,VN,US", max_length=60)):
    codes = [o.strip().upper() for o in origins.split(",") if o.strip()]
    if not codes or len(codes) > 10 or not all(len(c) == 2 and c.isalpha() for c in codes):
        raise HTTPException(422, "origins: 1-10 ISO-2 codes, comma-separated")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT scope_key, outcome_key, outcome, share_of_classified, notifications
               FROM health_outcome_profile WHERE scope_type='rasff_origin' AND scope_key = ANY($1::text[])""", codes)
    table: dict[str, dict] = {}
    for r in rows:
        t = table.setdefault(r["outcome_key"], {"outcome_key": r["outcome_key"], "outcome": r["outcome"]})
        t[r["scope_key"]] = {"share": float(r["share_of_classified"]) if r["share_of_classified"] is not None else None,
                             "notifications": r["notifications"]}
    ordered = sorted(table.values(), key=lambda t: -max((t.get(c) or {}).get("notifications", 0) for c in codes))
    return CompareOut(origins=codes, outcomes=ordered, caveat=PROFILE_CAVEAT)


class IntakeOut(BaseModel):
    hazard_key: str
    concentration_mg_per_kg: Optional[float]
    body_weight_kg: float
    computable: bool
    reason: Optional[str]
    chronic: Optional[dict[str, Any]]
    acute: Optional[dict[str, Any]]
    caveat: str


INTAKE_CAVEAT = ("Uses one measured value and a health-based guidance value; an illustration of what a finding means, "
                 "not an assessment of anyone's diet.")


async def _refs(conn, keys: list[str]) -> list[dict]:
    rows = await conn.fetch(
        """SELECT body, value_type, value::float AS value, unit, raw_text, source_ref, source_url
           FROM hazard_reference_values WHERE hazard_key = ANY($1::text[])""", [k for k in keys if k])
    return [dict(r) for r in rows]


@health_router.get("/safe-intake", response_model=IntakeOut)
async def safe_intake(hazard: str = Query(..., pattern=_KEY), concentration_mg_kg: float = Query(..., gt=0, le=1e6),
                      body_weight_kg: float = Query(60, ge=5, le=200)):
    from models.safe_intake import assess
    pool = get_pool()
    async with pool.acquire() as conn:
        refs = await _refs(conn, [hazard])
    a = assess(hazard, Decimal(str(concentration_mg_kg)), Decimal(str(body_weight_kg)), refs)
    return IntakeOut(hazard_key=hazard, concentration_mg_per_kg=concentration_mg_kg, body_weight_kg=body_weight_kg,
                     caveat=INTAKE_CAVEAT, **a)


class MeasuredFinding(BaseModel):
    notif_id: int
    validation_date: str
    subject: Optional[str]
    product_category: Optional[str]
    hazard: str
    hazard_key: Optional[str]
    result_raw: Optional[str]
    concentration_mg_per_kg: Optional[float]
    limit_mg_per_kg: Optional[float]
    computable: bool
    reason: Optional[str]
    chronic: Optional[dict[str, Any]]
    acute: Optional[dict[str, Any]]
    source_url: str


class MeasuredOut(BaseModel):
    origin: str
    body_weight_kg: float
    results: list[MeasuredFinding]
    caveat: str


def _mg_per_kg(value, unit) -> Optional[Decimal]:
    if value is None or unit not in ("mg/kg", "ug/kg"):
        return None
    v = Decimal(str(value))
    return v if unit == "mg/kg" else v / 1000


@health_router.get("/safe-intake/rasff", response_model=MeasuredOut)
async def safe_intake_rasff(origin: str = Query("IN", pattern=_ORIGIN), hazard: Optional[str] = Query(None, pattern=_KEY),
                            body_weight_kg: float = Query(60, ge=5, le=200), limit: int = Query(50, ge=1, le=200)):
    """Recent EU findings with a measured concentration, and how much of that food
    would reach the hazard's acceptable daily intake / acute reference dose."""
    from models.safe_intake import assess
    from pipeline.sources.standards_common import hazard_key as fam_key, substance_key
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT n.notif_id, n.validation_date::text AS validation_date, n.subject, n.product_category, n.source_url,
                      h.hazard, h.hazard_key, h.result_raw, h.result_value::float AS rv, h.result_unit,
                      h.result_qualifier, h.limit_value::float AS lv, h.limit_unit
               FROM rasff_hazards h JOIN rasff_notifications n USING (notif_id)
               WHERE ($1 = 'ALL' OR $1 = ANY(n.origin_countries)) AND h.result_value IS NOT NULL
                 AND h.result_qualifier IN ('=', '>') AND h.result_unit IN ('mg/kg', 'ug/kg')
                 AND ($2::text IS NULL OR h.hazard_key = $2)
               ORDER BY n.validation_date DESC, n.notif_id DESC LIMIT $3""", origin, hazard, limit)
        out = []
        for r in rows:
            keys = [r["hazard_key"], substance_key(r["hazard"]), fam_key(r["hazard"])]
            conc = _mg_per_kg(r["rv"], r["result_unit"])
            a = assess(r["hazard_key"], conc, Decimal(str(body_weight_kg)), await _refs(conn, keys))
            lim = _mg_per_kg(r["lv"], r["limit_unit"])
            out.append(MeasuredFinding(
                notif_id=r["notif_id"], validation_date=r["validation_date"], subject=r["subject"],
                product_category=r["product_category"], hazard=r["hazard"], hazard_key=r["hazard_key"],
                result_raw=r["result_raw"], concentration_mg_per_kg=float(conc) if conc is not None else None,
                limit_mg_per_kg=float(lim) if lim is not None else None, source_url=r["source_url"], **a))
    return MeasuredOut(origin=origin, body_weight_kg=body_weight_kg, results=out, caveat=INTAKE_CAVEAT)
