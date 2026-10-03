"""
FoodSafe India — places in India: what can be known about food safety in each
State / UT, from the records the project holds.

  GET /v1/places/states           every State/UT: latest sampling outcome, enforcement, labs
  GET /v1/places/states/{state}   one State/UT in full, with national context

Per state (Lok Sabha disclosures, FSSAI directories):
  * samples analysed vs found non-conforming, by fiscal year (state_sampling_annual)
    — the two definitions ('non_conforming' and the older 'adulterated_misbranded')
    are never pooled;
  * enforcement: civil cases with penalty, criminal convictions, licences
    cancelled (state_enforcement_annual);
  * FSSAI-notified food testing labs; the State Commissioner of Food Safety.
National context (no state split exists): pesticide-residue monitoring (MPRNL),
EU findings on Indian exports, WHO/World Bank indicators for India.

Inspector-targeted samples are not a prevalence estimate: a high non-conforming
rate can mean better targeting as much as worse food. Every row carries its
confidence from api/source_registry.py.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_pool
from api.source_registry import SOURCES, row_confidence

places_router = APIRouter()

CAVEAT = ("Samples are chosen by inspectors (targeted), so a non-conforming rate is not the share of unsafe food in "
          "the state; 'non-conforming' includes labelling and quality failures, not only unsafe food. Figures are "
          "as disclosed by the Ministry of Health to Parliament.")


def _pct(nc, n):
    return round(100.0 * nc / n, 2) if n else None


class StateRow(BaseModel):
    state: str
    latest_fiscal_year: Optional[str]
    samples_analyzed: Optional[int]
    samples_non_conforming: Optional[int]
    non_conforming_pct: Optional[float]
    years_with_sampling: int
    latest_enforcement_year: Optional[str]
    criminal_convictions: Optional[int]
    civil_penalty_cases: Optional[int]
    labs: int
    has_commissioner: bool
    confidence_level: str


class StatesOut(BaseModel):
    states: list[StateRow]
    caveat: str
    scope: list[str]


_LATEST_SAMPLING = """
    SELECT DISTINCT ON (state, fiscal_year) state, fiscal_year, samples_analyzed, samples_non_conforming, verification
    FROM state_sampling_annual WHERE non_conforming_basis = 'non_conforming'
    ORDER BY state, fiscal_year, lok_sabha_no DESC, answered_date DESC NULLS LAST, source_question_no DESC"""


@places_router.get("/states", response_model=StatesOut)
async def states():
    pool = get_pool()
    async with pool.acquire() as conn:
        samp = await conn.fetch(_LATEST_SAMPLING)
        enf = await conn.fetch(
            """SELECT DISTINCT ON (state) state, fiscal_year, criminal_cases_convictions, civil_cases_decided_penalty
               FROM state_enforcement_annual ORDER BY state, fiscal_year DESC, answered_date DESC NULLS LAST""")
        labs = await conn.fetch("SELECT state, COUNT(*) AS n FROM labs WHERE state IS NOT NULL GROUP BY state")
        comm = await conn.fetch("SELECT state FROM state_commissioners")
    by_state: dict[str, list] = {}
    for r in samp:
        by_state.setdefault(r["state"], []).append(r)
    enf_by = {r["state"]: r for r in enf}
    labs_by = {r["state"]: r["n"] for r in labs}
    comm_set = {r["state"] for r in comm}
    names = sorted(set(by_state) | set(enf_by) | set(labs_by) | comm_set)
    out = []
    for s in names:
        rows = sorted(by_state.get(s, []), key=lambda r: r["fiscal_year"])
        last = rows[-1] if rows else None
        e = enf_by.get(s)
        conf = row_confidence("loksabha_sampling", verification=last["verification"]) if last else None
        out.append(StateRow(
            state=s, latest_fiscal_year=last["fiscal_year"] if last else None,
            samples_analyzed=last["samples_analyzed"] if last else None,
            samples_non_conforming=last["samples_non_conforming"] if last else None,
            non_conforming_pct=_pct(last["samples_non_conforming"], last["samples_analyzed"]) if last else None,
            years_with_sampling=len(rows), latest_enforcement_year=e["fiscal_year"] if e else None,
            criminal_convictions=e["criminal_cases_convictions"] if e else None,
            civil_penalty_cases=e["civil_cases_decided_penalty"] if e else None,
            labs=labs_by.get(s, 0), has_commissioner=s in comm_set,
            confidence_level=conf.level if conf else "n/a"))
    return StatesOut(states=out, caveat=CAVEAT, scope=list(SOURCES["loksabha_sampling"].scope))


class StateProfile(BaseModel):
    state: str
    sampling: list[dict[str, Any]]
    sampling_older_definition: list[dict[str, Any]]
    enforcement: list[dict[str, Any]]
    labs: list[dict[str, Any]]
    commissioner: Optional[dict[str, Any]]
    national_context: dict[str, Any]
    caveat: str


@places_router.get("/states/{state}", response_model=StateProfile)
async def state(state: str):
    s = state.strip()
    if not s or len(s) > 80 or "\x00" in s:      # a NUL would reach asyncpg and surface as a 500
        raise HTTPException(422, "bad state name")
    pool = get_pool()
    async with pool.acquire() as conn:
        canon = await conn.fetchval(
            """SELECT state FROM (SELECT state FROM state_sampling_annual UNION SELECT state FROM state_enforcement_annual
                                  UNION SELECT state FROM labs WHERE state IS NOT NULL
                                  UNION SELECT state FROM state_commissioners) x
               WHERE lower(state) = lower($1) LIMIT 1""", s)
        if not canon:
            raise HTTPException(404, "unknown State/UT")
        samp = await conn.fetch(
            """SELECT fiscal_year, samples_analyzed, samples_non_conforming, non_conforming_basis, verification,
                      lok_sabha_no, source_question_no, answered_date::text AS answered_date, source_url
               FROM state_sampling_annual WHERE state = $1 ORDER BY fiscal_year, lok_sabha_no""", canon)
        enf = await conn.fetch(
            """SELECT fiscal_year, samples_analyzed, civil_cases_decided_penalty, criminal_cases_convictions,
                      licenses_cancelled, answered_date::text AS answered_date, source_url
               FROM state_enforcement_annual WHERE state = $1 ORDER BY fiscal_year""", canon)
        labs = await conn.fetch("SELECT name, tier, accreditation, source_url FROM labs WHERE state = $1 ORDER BY tier, name",
                                canon)
        comm = await conn.fetchrow("SELECT commissioner_name, address, contact, email, source_url FROM state_commissioners "
                                   "WHERE state = $1", canon)
        pest = await conn.fetch(
            """SELECT commodity_label, period_label, samples_analyzed, samples_above_mrl FROM pesticide_residue_annual
               WHERE period_kind = 'fiscal_year' ORDER BY period_label DESC, commodity LIMIT 12""")
        eu = await conn.fetchrow(
            """SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE risk_decision='serious') AS s FROM rasff_notifications
               WHERE 'IN' = ANY(origin_countries)""")
    def rows(rs, basis):
        out = []
        for r in rs:
            if r["non_conforming_basis"] != basis:
                continue
            d = dict(r)
            d["non_conforming_pct"] = _pct(r["samples_non_conforming"], r["samples_analyzed"])
            d["confidence_level"] = row_confidence("loksabha_sampling", verification=r["verification"]).level
            out.append(d)
        return out
    return StateProfile(
        state=canon, sampling=rows(samp, "non_conforming"), sampling_older_definition=rows(samp, "adulterated_misbranded"),
        enforcement=[dict(r) for r in enf], labs=[dict(r) for r in labs], commissioner=dict(comm) if comm else None,
        national_context={
            "pesticide_residues_recent": [dict(r) for r in pest],
            "eu_findings_on_indian_exports": {"notifications": eu["n"], "serious": eu["s"]} if eu else None,
            "see_also": ["/v1/health/profile?origin=IN", "/v1/countries/IN", "/v1/standards/summary"]},
        caveat=CAVEAT)
