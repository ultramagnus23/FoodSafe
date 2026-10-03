"""
Country context from WHO and the World Bank, for comparing places.

  WHO Global Health Observatory (OData API, no key)
    IHRSPAR2_C13          IHR State Party self-assessment: food-safety capacity (%), 2021-
    IHRSPAR_CAPACITY04    the same capacity under the first SPAR edition, 2018-2020
    FOODSAFETY_JEE_SCORE  Joint External Evaluation food-safety score
    FOODBORNE_ILL / _DTH / _DALY
                          WHO foodborne disease burden by hazard and age group,
                          2000-2021. GLOBAL estimates only -> foodborne_burden_global.
  World Bank API (no key)
    nutrition and food-security indicators listed in WB_INDICATORS.

Every value is stored as published (one row per country x indicator x year);
nothing is imputed. A country-capacity score is a self-assessment reported to
WHO, which the API says next to it.

-> countries, country_indicators, foodborne_burden_global (migration 025)

Run: python -m pipeline.sources.country_indicators [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger("foodsafe.country_indicators")

USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
GHO = "https://ghoapi.azureedge.net/api/"
WB = "https://api.worldbank.org/v2/"

GHO_COUNTRY_INDICATORS = {
    "IHRSPAR2_C13": ("IHR self-assessment: food-safety capacity", "%"),
    "IHRSPAR_CAPACITY04": ("IHR self-assessment (1st edition): food-safety capacity", "%"),
    "FOODSAFETY_JEE_SCORE": ("Joint External Evaluation: food-safety score", "score 1-5"),
}
GHO_BURDEN = {"FOODBORNE_ILL": "illnesses", "FOODBORNE_DTH": "deaths", "FOODBORNE_DALY": "DALYs"}
AGE = {"AGEGROUP_YEARSALL": "all ages", "AGEGROUP_YEARSUNDER5": "under 5", "AGEGROUP_YEARS05PLUS": "5 and over"}

WB_INDICATORS = {
    "SN.ITK.DEFC.ZS": ("Prevalence of undernourishment", "% of population"),
    "SN.ITK.MSFI.ZS": ("Moderate or severe food insecurity", "% of population"),
    "SN.ITK.SVFI.ZS": ("Severe food insecurity", "% of population"),
    "SH.STA.STNT.ME.ZS": ("Stunting, children under 5", "% of children under 5"),
    "SH.STA.WAST.ZS": ("Wasting, children under 5", "% of children under 5"),
    "SH.ANM.ALLW.ZS": ("Anaemia, women of reproductive age", "% of women 15-49"),
    "SH.ANM.CHLD.ZS": ("Anaemia, children under 5", "% of children 6-59 months"),
    "SH.STA.OWAD.ZS": ("Overweight, adults", "% of adults"),
    "SH.STA.DIAB.ZS": ("Diabetes prevalence", "% of population 20-79"),
    "SH.H2O.SMDW.ZS": ("Safely managed drinking water", "% of population"),
    "SH.STA.SMSS.ZS": ("Safely managed sanitation", "% of population"),
}


def _get(url: str, attempts: int = 4):
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def _dec(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def strip_code(code: Optional[str], prefix: str) -> Optional[str]:
    """'FOODBORNE_HAZARD2_FOODBORNE_HAZARD2_AFB' -> 'AFB'."""
    if not code:
        return None
    return code.split(prefix + "_")[-1] if prefix in code else code


# ---------------------------------------------------------------- parsing (pure)

def parse_wb_countries(payload: list) -> list[dict]:
    out = []
    for c in payload[1] if len(payload) > 1 else []:
        region = (c.get("region") or {}).get("value", "").strip()
        out.append({"iso3": c["id"], "iso2": c.get("iso2Code") or None, "name": c["name"].strip(),
                    "region": region or None, "income_level": ((c.get("incomeLevel") or {}).get("value") or "").strip()
                    or None, "is_aggregate": region == "Aggregates"})
    return out


def parse_wb_series(payload: list, code: str) -> list[dict]:
    name, unit = WB_INDICATORS[code]
    out = []
    for r in payload[1] if len(payload) > 1 and payload[1] else []:
        v = _dec(r.get("value"))
        iso3 = r.get("countryiso3code")
        if v is None or not iso3:
            continue
        out.append({"iso3": iso3, "indicator_code": code, "indicator_name": name, "source": "World Bank",
                    "year": int(r["date"]), "value": v, "unit": unit,
                    "source_url": f"https://data.worldbank.org/indicator/{code}"})
    return out


def parse_gho_country(values: list, code: str) -> list[dict]:
    name, unit = GHO_COUNTRY_INDICATORS[code]
    out = []
    for r in values:
        if r.get("SpatialDimType") != "COUNTRY" or r.get("NumericValue") is None:
            continue
        out.append({"iso3": r["SpatialDim"], "indicator_code": code, "indicator_name": name, "source": "WHO GHO",
                    "year": int(r["TimeDim"]), "value": _dec(r["NumericValue"]), "unit": unit,
                    "source_url": f"https://www.who.int/data/gho/data/indicators/indicator-details/GHO/{code}"})
    return out


def parse_gho_burden(values: list, code: str, labels: dict[str, str]) -> list[dict]:
    out = []
    for r in values:
        if r.get("NumericValue") is None or r.get("SpatialDim") != "GLOBAL":
            continue
        out.append({"indicator_code": code, "measure": GHO_BURDEN[code], "year": int(r["TimeDim"]),
                    "age_group": AGE.get(r.get("Dim1"), r.get("Dim1") or "all ages"),
                    "hazard_group": labels.get(r.get("Dim2"), strip_code(r.get("Dim2"), "FOODBORNE_HAZARD1") or ""),
                    "hazard": labels.get(r.get("Dim3"), strip_code(r.get("Dim3"), "FOODBORNE_HAZARD2") or ""),
                    "value": _dec(r["NumericValue"]), "low": _dec(r.get("Low")), "high": _dec(r.get("High")),
                    "source_url": f"https://www.who.int/data/gho/data/indicators/indicator-details/GHO/{code}"})
    return out


# ---------------------------------------------------------------- fetching

def fetch_all() -> dict:
    countries = parse_wb_countries(_get(WB + "country?format=json&per_page=400"))
    if len(countries) < 200:
        raise RuntimeError(f"World Bank country list has only {len(countries)} entries")
    indicators: list[dict] = []
    for code in WB_INDICATORS:
        try:
            indicators += parse_wb_series(_get(f"{WB}country/all/indicator/{code}?format=json&per_page=20000"
                                               f"&date=2000:2026"), code)
        except urllib.error.HTTPError as e:
            logger.warning("World Bank %s unavailable (%s) — skipped", code, e)
    for code in GHO_COUNTRY_INDICATORS:
        indicators += parse_gho_country(_get(GHO + code)["value"], code)
    labels = {}
    for dim in ("FOODBORNE_HAZARD1", "FOODBORNE_HAZARD2"):
        for v in _get(f"{GHO}DIMENSION/{dim}/DimensionValues")["value"]:
            labels[v["Code"]] = v["Title"].replace("\xa0", " ").strip()
    burden: list[dict] = []
    for code in GHO_BURDEN:
        burden += parse_gho_burden(_get(GHO + code)["value"], code, labels)
    return {"countries": countries, "indicators": indicators, "burden": burden}


def load(conn, data: dict) -> dict:
    from psycopg2.extras import execute_batch
    with conn.cursor() as cur:
        execute_batch(cur,
            """INSERT INTO countries (iso3, iso2, name, region, income_level, is_aggregate, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,NOW())
               ON CONFLICT (iso3) DO UPDATE SET iso2=EXCLUDED.iso2, name=EXCLUDED.name, region=EXCLUDED.region,
                 income_level=EXCLUDED.income_level, is_aggregate=EXCLUDED.is_aggregate, updated_at=NOW()""",
            [(c["iso3"], c["iso2"], c["name"], c["region"], c["income_level"], c["is_aggregate"])
             for c in data["countries"]], page_size=500)
        execute_batch(cur,
            """INSERT INTO country_indicators (iso3, indicator_code, indicator_name, source, year, value, unit, source_url)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (iso3, indicator_code, year) DO UPDATE SET value=EXCLUDED.value,
                 indicator_name=EXCLUDED.indicator_name, unit=EXCLUDED.unit, loaded_at=NOW()""",
            [(r["iso3"], r["indicator_code"], r["indicator_name"], r["source"], r["year"], r["value"], r["unit"],
              r["source_url"]) for r in data["indicators"]], page_size=500)
        execute_batch(cur,
            """INSERT INTO foodborne_burden_global (indicator_code, measure, year, age_group, hazard_group, hazard,
                 value, low, high, source_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (indicator_code, year, age_group, hazard_group, hazard) DO UPDATE SET
                 value=EXCLUDED.value, low=EXCLUDED.low, high=EXCLUDED.high""",
            [(b["indicator_code"], b["measure"], b["year"], b["age_group"], b["hazard_group"], b["hazard"],
              b["value"], b["low"], b["high"], b["source_url"]) for b in data["burden"]], page_size=500)
    conn.commit()
    return {"countries": len(data["countries"]), "indicator_values": len(data["indicators"]),
            "burden_rows": len(data["burden"])}


def run(dry_run: bool = False) -> dict:
    data = fetch_all()
    info = {"countries": len(data["countries"]), "indicator_values": len(data["indicators"]),
            "burden_rows": len(data["burden"])}
    if dry_run:
        return {**info, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = load(conn, data)
    finally:
        conn.close()
    return {**res, "inserted": res["indicator_values"]}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    print(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
