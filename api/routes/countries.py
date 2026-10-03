"""
FoodSafe India — places compared: countries and the global foodborne burden.

  GET /v1/countries                     every country: food-safety capacity, nutrition, EU findings on its food
  GET /v1/countries/{code}              one country (ISO-2 or ISO-3): indicator series, EU findings, health profile
  GET /v1/global/foodborne-burden       WHO's global foodborne disease burden by hazard

Sources: World Bank and WHO GHO (pipeline/sources/country_indicators.py), EU
RASFF (rasff_*), health profiles (models/health_profile.py). Values are as
published; a country's food-safety capacity is its own IHR self-assessment to
WHO. EU findings reflect what the EU imports and how it targets checks, not the
safety of food eaten in the origin country.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool

countries_router = APIRouter()
global_router = APIRouter()

KEY_INDICATORS = ["IHRSPAR2_C13", "SH.STA.STNT.ME.ZS", "SH.ANM.ALLW.ZS", "SN.ITK.DEFC.ZS", "SN.ITK.MSFI.ZS",
                  "SH.H2O.SMDW.ZS"]
CAVEAT = ("Indicators are as published by the World Bank and WHO (food-safety capacity is a self-assessment). "
          "EU findings count checks on exported food, driven by trade volume and targeting; they do not rank whose "
          "food is safer.")


class Latest(BaseModel):
    indicator_code: str
    indicator_name: str
    year: int
    value: float
    unit: Optional[str]
    source: str


class CountryRow(BaseModel):
    iso3: str
    iso2: Optional[str]
    name: str
    region: Optional[str]
    income_level: Optional[str]
    indicators: dict[str, Latest]
    eu_findings: int
    eu_findings_serious_share: Optional[float]


class CountriesOut(BaseModel):
    countries: list[CountryRow]
    key_indicators: list[str]
    caveat: str


async def _latest(conn, iso3s: Optional[list[str]] = None, codes: Optional[list[str]] = None) -> dict:
    rows = await conn.fetch(
        """SELECT DISTINCT ON (iso3, indicator_code) iso3, indicator_code, indicator_name, year, value::float AS value,
                  unit, source
           FROM country_indicators
           WHERE ($1::text[] IS NULL OR iso3 = ANY($1)) AND ($2::text[] IS NULL OR indicator_code = ANY($2))
           ORDER BY iso3, indicator_code, year DESC""", iso3s, codes)
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["iso3"], {})[r["indicator_code"]] = Latest(**{k: r[k] for k in Latest.model_fields})
    return out


@countries_router.get("", response_model=CountriesOut)
async def list_countries(region: Optional[str] = Query(None, max_length=80), include_aggregates: bool = False):
    pool = get_pool()
    async with pool.acquire() as conn:
        cs = await conn.fetch(
            """SELECT * FROM countries WHERE ($1::text IS NULL OR region = $1) AND ($2 OR NOT is_aggregate)
               ORDER BY name""", region, include_aggregates)
        latest = await _latest(conn, None, KEY_INDICATORS)
        eu = await conn.fetch(
            """SELECT o AS iso2, COUNT(*) AS n,
                      COUNT(*) FILTER (WHERE risk_decision = 'serious') AS s,
                      COUNT(*) FILTER (WHERE risk_decision IS NOT NULL) AS d
               FROM rasff_notifications, unnest(origin_countries) AS o GROUP BY o""")
    eu_by = {r["iso2"]: r for r in eu}
    out = []
    for c in cs:
        e = eu_by.get(c["iso2"])
        out.append(CountryRow(iso3=c["iso3"], iso2=c["iso2"], name=c["name"], region=c["region"],
                              income_level=c["income_level"], indicators=latest.get(c["iso3"], {}),
                              eu_findings=e["n"] if e else 0,
                              eu_findings_serious_share=round(e["s"] / e["d"], 4) if e and e["d"] else None))
    return CountriesOut(countries=out, key_indicators=KEY_INDICATORS, caveat=CAVEAT)


class Series(BaseModel):
    indicator_code: str
    indicator_name: str
    unit: Optional[str]
    source: str
    source_url: str
    points: list[tuple[int, float]]


class CountryProfile(BaseModel):
    iso3: str
    iso2: Optional[str]
    name: str
    region: Optional[str]
    income_level: Optional[str]
    series: list[Series]
    eu_findings_by_year: dict[str, int]
    eu_findings_by_category: list[tuple[str, int]]
    health_outcomes: list[dict[str, Any]]
    caveat: str


@countries_router.get("/{code}", response_model=CountryProfile)
async def country(code: str):
    c = code.strip().upper()
    if not (2 <= len(c) <= 3 and c.isalpha()):
        raise HTTPException(422, "use an ISO-2 or ISO-3 country code")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM countries WHERE iso3 = $1 OR iso2 = $1", c)
        if not row:
            raise HTTPException(404, "unknown country")
        ser = await conn.fetch(
            """SELECT indicator_code, indicator_name, unit, source, source_url, year, value::float AS value
               FROM country_indicators WHERE iso3 = $1 ORDER BY indicator_code, year""", row["iso3"])
        by_year = await conn.fetch(
            """SELECT EXTRACT(YEAR FROM validation_date)::int::text AS y, COUNT(*) AS n FROM rasff_notifications
               WHERE $1 = ANY(origin_countries) GROUP BY 1 ORDER BY 1""", row["iso2"])
        by_cat = await conn.fetch(
            """SELECT COALESCE(h.hazard_category, 'unclassified') AS k, COUNT(DISTINCT n.notif_id) AS c
               FROM rasff_notifications n JOIN rasff_hazards h USING (notif_id)
               WHERE $1 = ANY(n.origin_countries) GROUP BY 1 ORDER BY c DESC LIMIT 10""", row["iso2"])
        prof = await conn.fetch(
            """SELECT outcome_key, outcome, organ_system, exposure, notifications, share_of_classified::float AS share
               FROM health_outcome_profile WHERE scope_type='rasff_origin' AND scope_key=$1
               ORDER BY notifications DESC LIMIT 12""", row["iso2"])
    series: dict[str, Series] = {}
    for r in ser:
        s = series.setdefault(r["indicator_code"], Series(indicator_code=r["indicator_code"],
                                                          indicator_name=r["indicator_name"], unit=r["unit"],
                                                          source=r["source"], source_url=r["source_url"], points=[]))
        s.points.append((r["year"], r["value"]))
    return CountryProfile(iso3=row["iso3"], iso2=row["iso2"], name=row["name"], region=row["region"],
                          income_level=row["income_level"], series=list(series.values()),
                          eu_findings_by_year={r["y"]: r["n"] for r in by_year},
                          eu_findings_by_category=[(r["k"], r["c"]) for r in by_cat],
                          health_outcomes=[dict(r) for r in prof], caveat=CAVEAT)


class BurdenRow(BaseModel):
    hazard_group: str
    hazard: str
    value: float
    low: Optional[float]
    high: Optional[float]


class BurdenOut(BaseModel):
    measure: str
    year: int
    age_group: str
    rows: list[BurdenRow]
    source: str
    note: str


@global_router.get("/foodborne-burden", response_model=BurdenOut)
async def foodborne_burden(measure: str = Query("deaths", pattern=r"^(illnesses|deaths|DALYs)$"),
                           year: Optional[int] = Query(None, ge=2000, le=2100),
                           age_group: str = Query("all ages", pattern=r"^(all ages|under 5|5 and over)$")):
    pool = get_pool()
    async with pool.acquire() as conn:
        y = year or await conn.fetchval("SELECT MAX(year) FROM foodborne_burden_global WHERE measure=$1", measure)
        rows = await conn.fetch(
            """SELECT hazard_group, hazard, value::float AS value, low::float AS low, high::float AS high
               FROM foodborne_burden_global WHERE measure=$1 AND year=$2 AND age_group=$3
               ORDER BY value DESC""", measure, y, age_group)
    if y is None:
        raise HTTPException(404, "no burden data loaded")
    return BurdenOut(measure=measure, year=y, age_group=age_group, rows=[BurdenRow(**dict(r)) for r in rows],
                     source="WHO Global Health Observatory — foodborne disease burden estimates (FERG)",
                     note="WHO publishes these estimates at global level only. Rows include group totals "
                          "('All hazards', 'Chemical hazards' ...) alongside individual hazards.")
