"""
FoodSafe India — Disease Burden Routes
GET /v1/disease/district/{district_id}
GET /v1/disease/contaminant/{contaminant_id}/map
GET /v1/disease/alerts
GET /v1/disease/benchmark/{contaminant_id}/{commodity_id}

Every response includes disclaimer, evidence_grade, and inference_type per
the platform's legal/scientific constraints. No brand names anywhere —
these endpoints operate purely on district x commodity x contaminant data.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool
from api.routes.risk import build_disclaimer
from models.codex_benchmark import CodexBenchmarkComparator, ContaminantLimits
from models.dietary_exposure import DietaryExposureEstimator

logger = logging.getLogger("foodsafe.routes.disease")

disease_router = APIRouter()


# ============================================================
# RESPONSE MODELS
# ============================================================

class DistrictBurdenRow(BaseModel):
    commodity_id:      int
    commodity_name:    str
    contaminant_id:     int
    contaminant_name:   str
    mean_exposure_ppb:  Optional[float]
    dietary_intake_ug_per_kg_day: Optional[float]
    fssai_compliant:    Optional[bool]
    codex_compliant:    Optional[bool]
    fssai_vs_codex_gap: Optional[float]   # ratio of FSSAI limit to Codex limit, >1 = FSSAI more permissive
    paf_estimate:        Optional[float]
    paf_ci:               Optional[list[float]]
    hazard_quotient:      Optional[float]
    attributable_cases_per_100k: Optional[float]
    disease_name:          str
    disease_icd10:          str
    evidence_grade:          str
    latency_years:            Optional[str]
    n_records:                 int
    inference_type:             str
    disclaimer:                  str


class DistrictBurdenResponse(BaseModel):
    district_id:   int
    district_name: str
    state:         str
    rows:          list[DistrictBurdenRow]
    disclaimer:    str


class ContaminantMapPoint(BaseModel):
    district_id:    int
    district_name:  str
    state:          str
    latitude:       Optional[float]
    longitude:      Optional[float]
    paf_estimate:   Optional[float]
    fssai_compliant: Optional[bool]
    codex_compliant: Optional[bool]
    n_records:      int
    inference_type: str


class ExposureAlertOut(BaseModel):
    id:               int
    district_id:       int
    district_name:      str
    state:               str
    commodity:            str
    contaminant:           str
    alert_type:             str
    severity:                str
    mean_exposure_ppb:        Optional[float]
    codex_limit_ppb:            Optional[float]
    fssai_limit_ppb:              Optional[float]
    n_samples:                     Optional[int]
    first_seen:                     Optional[str]
    last_seen:                       Optional[str]
    disclaimer:                       str


class BenchmarkResponse(BaseModel):
    contaminant_id:     int
    contaminant_name:   str
    commodity_id:       int
    commodity_name:      str
    fssai_limit_ppb:      Optional[float]
    codex_limit_ppb:        Optional[float]
    eu_limit_ppb:             Optional[float]
    who_jecfa_twi_ug_per_kg:   Optional[float]
    codex_doc_reference:         Optional[str]
    fssai_vs_codex_ratio:          Optional[float]
    interpretation:                  str
    evidence_grade:                    Optional[str]
    disclaimer:                          str


# ============================================================
# DISTRICT DISEASE BURDEN
# ============================================================

@disease_router.get("/district/{district_id}", response_model=DistrictBurdenResponse)
async def district_burden(district_id: int, user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        district = await conn.fetchrow(
            "SELECT id, name_canonical, state FROM districts WHERE id = $1", district_id
        )
        if not district:
            raise HTTPException(404, "District not found")

        rows = await conn.fetch(
            """
            SELECT dbe.*, c.name_canonical AS commodity_name,
                   cnt.name_canonical AS contaminant_name,
                   cnt.legal_limit_ppb_fssai, cnt.legal_limit_ppb_codex,
                   drp.evidence_grade, drp.latency_years_min, drp.latency_years_max,
                   drp.disease_name AS drp_disease_name
            FROM disease_burden_estimates dbe
            JOIN commodities c ON c.id = dbe.commodity_id
            JOIN contaminants cnt ON cnt.id = dbe.contaminant_id
            LEFT JOIN dose_response_params drp
                ON drp.contaminant_id = dbe.contaminant_id AND drp.disease_icd10 = dbe.disease_icd10
            WHERE dbe.district_id = $1
            ORDER BY dbe.population_attributable_fraction DESC NULLS LAST
            """,
            district_id,
        )

    out_rows = []
    for r in rows:
        fssai_limit = float(r["legal_limit_ppb_fssai"]) if r["legal_limit_ppb_fssai"] else None
        codex_limit = float(r["legal_limit_ppb_codex"]) if r["legal_limit_ppb_codex"] else None
        mean_ppb = float(r["mean_exposure_ppb"]) if r["mean_exposure_ppb"] is not None else None

        fssai_compliant = (mean_ppb is not None and fssai_limit is not None and mean_ppb <= fssai_limit)
        codex_compliant = (mean_ppb is not None and codex_limit is not None and mean_ppb <= codex_limit)
        gap = round(fssai_limit / codex_limit, 3) if fssai_limit and codex_limit else None

        latency = None
        if r["latency_years_min"] is not None and r["latency_years_max"] is not None:
            latency = f"{r['latency_years_min']}–{r['latency_years_max']} years"

        out_rows.append(DistrictBurdenRow(
            commodity_id=r["commodity_id"],
            commodity_name=r["commodity_name"],
            contaminant_id=r["contaminant_id"],
            contaminant_name=r["contaminant_name"],
            mean_exposure_ppb=mean_ppb,
            dietary_intake_ug_per_kg_day=float(r["mean_dietary_intake_ug_per_kg_per_day"]) if r["mean_dietary_intake_ug_per_kg_per_day"] is not None else None,
            fssai_compliant=fssai_compliant,
            codex_compliant=codex_compliant,
            fssai_vs_codex_gap=gap,
            paf_estimate=float(r["population_attributable_fraction"]) if r["population_attributable_fraction"] is not None else None,
            paf_ci=(
                [float(r["paf_lower_ci"]), float(r["paf_upper_ci"])]
                if r["paf_lower_ci"] is not None and r["paf_upper_ci"] is not None else None
            ),
            hazard_quotient=None,
            attributable_cases_per_100k=float(r["estimated_attributable_cases_per_100k"]) if r["estimated_attributable_cases_per_100k"] is not None else None,
            disease_name=r["drp_disease_name"] or r["disease_icd10"],
            disease_icd10=r["disease_icd10"],
            evidence_grade=r["evidence_grade"] or "jecfa_established",
            latency_years=latency,
            n_records=r["n_enforcement_records"] or 0,
            inference_type=r["inference_type"],
            disclaimer=build_disclaimer(r["commodity_name"], district["name_canonical"]),
        ))

    return DistrictBurdenResponse(
        district_id=district_id,
        district_name=district["name_canonical"],
        state=district["state"],
        rows=out_rows,
        disclaimer=build_disclaimer(district=district["name_canonical"]),
    )


# ============================================================
# CONTAMINANT MAP (choropleth)
# ============================================================

@disease_router.get("/contaminant/{contaminant_id}/map", response_model=list[ContaminantMapPoint])
async def contaminant_map(contaminant_id: int, user: CurrentUser = Depends(get_current_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        contaminant = await conn.fetchrow(
            "SELECT id, legal_limit_ppb_fssai, legal_limit_ppb_codex FROM contaminants WHERE id = $1",
            contaminant_id,
        )
        if not contaminant:
            raise HTTPException(404, "Contaminant not found")

        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (dbe.district_id)
                d.id AS district_id, d.name_canonical AS district_name, d.state,
                d.latitude, d.longitude,
                dbe.mean_exposure_ppb, dbe.population_attributable_fraction,
                dbe.n_enforcement_records, dbe.inference_type
            FROM disease_burden_estimates dbe
            JOIN districts d ON d.id = dbe.district_id
            WHERE dbe.contaminant_id = $1
            ORDER BY dbe.district_id, dbe.population_attributable_fraction DESC NULLS LAST
            """,
            contaminant_id,
        )

    fssai_limit = float(contaminant["legal_limit_ppb_fssai"]) if contaminant["legal_limit_ppb_fssai"] else None
    codex_limit = float(contaminant["legal_limit_ppb_codex"]) if contaminant["legal_limit_ppb_codex"] else None

    out = []
    for r in rows:
        mean_ppb = float(r["mean_exposure_ppb"]) if r["mean_exposure_ppb"] is not None else None
        out.append(ContaminantMapPoint(
            district_id=r["district_id"],
            district_name=r["district_name"],
            state=r["state"],
            latitude=float(r["latitude"]) if r["latitude"] else None,
            longitude=float(r["longitude"]) if r["longitude"] else None,
            paf_estimate=float(r["population_attributable_fraction"]) if r["population_attributable_fraction"] is not None else None,
            fssai_compliant=(mean_ppb is not None and fssai_limit is not None and mean_ppb <= fssai_limit),
            codex_compliant=(mean_ppb is not None and codex_limit is not None and mean_ppb <= codex_limit),
            n_records=r["n_enforcement_records"] or 0,
            inference_type=r["inference_type"],
        ))
    return out


# ============================================================
# EXPOSURE ALERTS
# ============================================================

@disease_router.get("/alerts", response_model=list[ExposureAlertOut])
async def exposure_alerts(
    state: Optional[str] = None,
    commodity_id: Optional[int] = None,
    contaminant_id: Optional[int] = None,
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ea.*, d.name_canonical AS district_name, d.state AS district_state,
                   c.name_canonical AS commodity_name, cnt.name_canonical AS contaminant_name
            FROM exposure_alerts ea
            JOIN districts d ON d.id = ea.district_id
            JOIN commodities c ON c.id = ea.commodity_id
            JOIN contaminants cnt ON cnt.id = ea.contaminant_id
            WHERE ea.active = TRUE
              AND ($1::text IS NULL OR d.state = $1)
              AND ($2::int IS NULL OR ea.commodity_id = $2)
              AND ($3::int IS NULL OR ea.contaminant_id = $3)
              AND ($4::text IS NULL OR ea.severity = $4)
              AND ($5::text IS NULL OR ea.alert_type = $5)
            ORDER BY
                CASE ea.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                ea.last_seen DESC
            LIMIT $6 OFFSET $7
            """,
            state, commodity_id, contaminant_id, severity, alert_type, limit, offset,
        )

    return [
        ExposureAlertOut(
            id=r["id"],
            district_id=r["district_id"],
            district_name=r["district_name"],
            state=r["district_state"],
            commodity=r["commodity_name"],
            contaminant=r["contaminant_name"],
            alert_type=r["alert_type"],
            severity=r["severity"],
            mean_exposure_ppb=float(r["mean_exposure_ppb"]) if r["mean_exposure_ppb"] is not None else None,
            codex_limit_ppb=float(r["codex_limit_ppb"]) if r["codex_limit_ppb"] is not None else None,
            fssai_limit_ppb=float(r["fssai_limit_ppb"]) if r["fssai_limit_ppb"] is not None else None,
            n_samples=r["n_samples"],
            first_seen=str(r["first_seen"]) if r["first_seen"] else None,
            last_seen=str(r["last_seen"]) if r["last_seen"] else None,
            disclaimer=build_disclaimer(r["commodity_name"], r["district_name"]),
        )
        for r in rows
    ]


# ============================================================
# BENCHMARK COMPARISON
# ============================================================

@disease_router.get("/benchmark/{contaminant_id}/{commodity_id}", response_model=BenchmarkResponse)
async def benchmark(
    contaminant_id: int, commodity_id: int,
    district_id: Optional[int] = None,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        contaminant = await conn.fetchrow(
            """
            SELECT id, name_canonical, legal_limit_ppb_fssai, legal_limit_ppb_codex,
                   eu_limit_ppb, who_jecfa_twi_ug_per_kg, codex_doc_reference, iarc_class
            FROM contaminants WHERE id = $1
            """,
            contaminant_id,
        )
        if not contaminant:
            raise HTTPException(404, "Contaminant not found")
        commodity = await conn.fetchrow("SELECT id, name_canonical FROM commodities WHERE id = $1", commodity_id)
        if not commodity:
            raise HTTPException(404, "Commodity not found")

        district_name = None
        mean_ppb = None
        if district_id:
            district = await conn.fetchrow("SELECT name_canonical FROM districts WHERE id = $1", district_id)
            district_name = district["name_canonical"] if district else None
            agg_row = await conn.fetchrow(
                """
                SELECT AVG(raw_value_ppb) AS mean_ppb
                FROM enforcement_records
                WHERE district_id = $1 AND commodity_id = $2 AND contaminant_id = $3
                  AND confidence_score >= 0.75 AND is_duplicate = FALSE
                """,
                district_id, commodity_id, contaminant_id,
            )
            mean_ppb = float(agg_row["mean_ppb"]) if agg_row and agg_row["mean_ppb"] is not None else None

    fssai_limit = float(contaminant["legal_limit_ppb_fssai"]) if contaminant["legal_limit_ppb_fssai"] else None
    codex_limit = float(contaminant["legal_limit_ppb_codex"]) if contaminant["legal_limit_ppb_codex"] else None
    eu_limit = float(contaminant["eu_limit_ppb"]) if contaminant["eu_limit_ppb"] else None
    twi = float(contaminant["who_jecfa_twi_ug_per_kg"]) if contaminant["who_jecfa_twi_ug_per_kg"] else None
    ratio = round(fssai_limit / codex_limit, 3) if fssai_limit and codex_limit else None

    interpretation = "Insufficient benchmark data for interpretation."
    if mean_ppb is not None:
        limits = ContaminantLimits(
            contaminant_id=contaminant_id, name=contaminant["name_canonical"],
            fssai_limit_ppb=fssai_limit, codex_limit_ppb=codex_limit,
            eu_limit_ppb=eu_limit, who_jecfa_twi_ug_per_kg=twi,
        )
        comparator = CodexBenchmarkComparator(DietaryExposureEstimator())
        cmp = comparator.compare(
            value_ppb=mean_ppb, limits=limits, commodity_name=commodity["name_canonical"],
            district_name=district_name, commodity_id=commodity_id,
        )
        interpretation = cmp.interpretation
    elif fssai_limit and codex_limit:
        interpretation = (
            f"FSSAI's limit for {contaminant['name_canonical']} in {commodity['name_canonical']} "
            f"is {fssai_limit:.1f} PPB versus Codex Alimentarius's {codex_limit:.1f} PPB"
            + (f" ({ratio}x more permissive)." if ratio and ratio > 1 else ".")
        )

    evidence_grade = {
        "1": "iarc_group_1", "2A": "iarc_group_2a", "2B": "iarc_group_2b",
    }.get(contaminant["iarc_class"], "jecfa_established")

    return BenchmarkResponse(
        contaminant_id=contaminant_id,
        contaminant_name=contaminant["name_canonical"],
        commodity_id=commodity_id,
        commodity_name=commodity["name_canonical"],
        fssai_limit_ppb=fssai_limit,
        codex_limit_ppb=codex_limit,
        eu_limit_ppb=eu_limit,
        who_jecfa_twi_ug_per_kg=twi,
        codex_doc_reference=contaminant["codex_doc_reference"],
        fssai_vs_codex_ratio=ratio,
        interpretation=interpretation,
        evidence_grade=evidence_grade,
        disclaimer=build_disclaimer(commodity["name_canonical"], district_name),
    )
