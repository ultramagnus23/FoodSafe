"""
FoodSafe India — Comparative Analytics Routes
GET /v1/compare/districts?a={id}&b={id}&commodity_id=
GET /v1/compare/best?commodity_id=&limit=
GET /v1/compare/standards — FSSAI vs Codex vs EU benchmark table, all contaminants

No brand names anywhere — purely district/commodity/contaminant comparisons.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool
from api.routes.risk import build_disclaimer

logger = logging.getLogger("foodsafe.routes.compare")

compare_router = APIRouter()


class DistrictSummary(BaseModel):
    district_id: int
    district_name: str
    state: str
    risk_score: Optional[float]
    ci_lower: Optional[float]
    ci_upper: Optional[float]
    n_tests: int
    fail_rate: Optional[float]
    codex_compliant_fraction: Optional[float]
    top_contaminants: list[dict]
    inference_type: str


class CompareDelta(BaseModel):
    risk_score_delta: Optional[float]
    fail_rate_delta: Optional[float]
    codex_compliant_fraction_delta: Optional[float]


class CompareResponse(BaseModel):
    commodity_id: int
    commodity_name: str
    a: DistrictSummary
    b: DistrictSummary
    delta: CompareDelta
    disclaimer: str


async def _district_summary(conn, district_id: int, commodity_id: int) -> DistrictSummary:
    district = await conn.fetchrow("SELECT id, name_canonical, state FROM districts WHERE id = $1", district_id)
    if not district:
        raise HTTPException(404, f"District {district_id} not found")

    agg = await conn.fetchrow(
        """
        SELECT risk_score, ci_lower, ci_upper, n_tests, fail_rate,
               codex_compliant_fraction, top_contaminants
        FROM agg_district_commodity_risk
        WHERE district_id = $1 AND commodity_id = $2
        ORDER BY quarter DESC LIMIT 1
        """,
        district_id, commodity_id,
    )

    top_contaminants = []
    if agg and agg["top_contaminants"]:
        raw = agg["top_contaminants"]
        top_contaminants = json.loads(raw) if isinstance(raw, str) else list(raw)

    n_tests = agg["n_tests"] if agg else 0
    return DistrictSummary(
        district_id=district_id,
        district_name=district["name_canonical"],
        state=district["state"],
        risk_score=float(agg["risk_score"]) if agg and agg["risk_score"] is not None else None,
        ci_lower=float(agg["ci_lower"]) if agg and agg["ci_lower"] is not None else None,
        ci_upper=float(agg["ci_upper"]) if agg and agg["ci_upper"] is not None else None,
        n_tests=n_tests or 0,
        fail_rate=float(agg["fail_rate"]) if agg and agg["fail_rate"] is not None else None,
        codex_compliant_fraction=float(agg["codex_compliant_fraction"]) if agg and agg["codex_compliant_fraction"] is not None else None,
        top_contaminants=top_contaminants,
        inference_type="direct_test" if n_tests and n_tests >= 3 else "insufficient_data",
    )


@compare_router.get("/districts", response_model=CompareResponse)
async def compare_districts(a: int, b: int, commodity_id: int, user: CurrentUser = Depends(get_current_user)):
    if a == b:
        raise HTTPException(400, "Choose two different districts to compare")
    pool = get_pool()
    async with pool.acquire() as conn:
        commodity = await conn.fetchrow("SELECT id, name_canonical FROM commodities WHERE id = $1", commodity_id)
        if not commodity:
            raise HTTPException(404, "Commodity not found")
        summary_a = await _district_summary(conn, a, commodity_id)
        summary_b = await _district_summary(conn, b, commodity_id)

    delta = CompareDelta(
        risk_score_delta=(
            round(summary_a.risk_score - summary_b.risk_score, 2)
            if summary_a.risk_score is not None and summary_b.risk_score is not None else None
        ),
        fail_rate_delta=(
            round(summary_a.fail_rate - summary_b.fail_rate, 4)
            if summary_a.fail_rate is not None and summary_b.fail_rate is not None else None
        ),
        codex_compliant_fraction_delta=(
            round(summary_a.codex_compliant_fraction - summary_b.codex_compliant_fraction, 4)
            if summary_a.codex_compliant_fraction is not None and summary_b.codex_compliant_fraction is not None else None
        ),
    )

    return CompareResponse(
        commodity_id=commodity_id,
        commodity_name=commodity["name_canonical"],
        a=summary_a,
        b=summary_b,
        delta=delta,
        disclaimer=build_disclaimer(commodity["name_canonical"]),
    )


class BestDistrict(BaseModel):
    district_id: int
    district_name: str
    state: str
    risk_score: float
    n_tests: int
    codex_compliant_fraction: Optional[float]


@compare_router.get("/best", response_model=list[BestDistrict])
async def best_districts(commodity_id: int, limit: int = 10, user: CurrentUser = Depends(get_current_user)):
    """Lowest-risk districts for a commodity — the mirror image of the FMCG
    market-gaps endpoint, framed for consumers instead of procurement."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (agg.district_id)
                d.id AS district_id, d.name_canonical AS district_name, d.state,
                agg.risk_score, agg.n_tests, agg.codex_compliant_fraction
            FROM agg_district_commodity_risk agg
            JOIN districts d ON d.id = agg.district_id
            WHERE agg.commodity_id = $1 AND agg.risk_score IS NOT NULL AND agg.n_tests >= 3
            ORDER BY agg.district_id, agg.quarter DESC
            """,
            commodity_id,
        )
    ranked = sorted(rows, key=lambda r: r["risk_score"])[:limit]
    return [
        BestDistrict(
            district_id=r["district_id"], district_name=r["district_name"], state=r["state"],
            risk_score=float(r["risk_score"]), n_tests=r["n_tests"],
            codex_compliant_fraction=float(r["codex_compliant_fraction"]) if r["codex_compliant_fraction"] is not None else None,
        )
        for r in ranked
    ]


class StandardsRow(BaseModel):
    contaminant_id: int
    contaminant_name: str
    fssai_limit_ppb: Optional[float]
    codex_limit_ppb: Optional[float]
    eu_limit_ppb: Optional[float]
    fssai_vs_codex_ratio: Optional[float]
    codex_doc_reference: Optional[str]


@compare_router.get("/standards", response_model=list[StandardsRow])
async def standards_table(user: CurrentUser = Depends(get_current_user)):
    """The India-vs-world benchmark table — sorted biggest gap first. This
    is the platform's centrepiece finding: where FSSAI's own limit is more
    permissive than the international standard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name_canonical, legal_limit_ppb_fssai, legal_limit_ppb_codex,
                   eu_limit_ppb, codex_doc_reference
            FROM contaminants
            WHERE legal_limit_ppb_fssai IS NOT NULL AND legal_limit_ppb_codex IS NOT NULL
            """
        )
    out = []
    for r in rows:
        fssai = float(r["legal_limit_ppb_fssai"])
        codex = float(r["legal_limit_ppb_codex"])
        ratio = round(fssai / codex, 3) if codex > 0 else None
        out.append(StandardsRow(
            contaminant_id=r["id"], contaminant_name=r["name_canonical"],
            fssai_limit_ppb=fssai, codex_limit_ppb=codex,
            eu_limit_ppb=float(r["eu_limit_ppb"]) if r["eu_limit_ppb"] is not None else None,
            fssai_vs_codex_ratio=ratio, codex_doc_reference=r["codex_doc_reference"],
        ))
    out.sort(key=lambda x: (x.fssai_vs_codex_ratio or 0), reverse=True)
    return out
