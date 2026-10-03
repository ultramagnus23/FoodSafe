"""
Tests for pipeline/sources/country_indicators.py (World Bank + WHO GHO). The
payloads are trimmed real API shapes. No network, no database.
"""
from __future__ import annotations

from decimal import Decimal

from pipeline.sources import country_indicators as C


def test_world_bank_countries_flag_aggregates():
    payload = [{"page": 1}, [
        {"id": "IND", "iso2Code": "IN", "name": "India", "region": {"value": "South Asia"},
         "incomeLevel": {"value": "Lower middle income"}},
        {"id": "AFE", "iso2Code": "ZH", "name": "Africa Eastern and Southern", "region": {"value": "Aggregates"},
         "incomeLevel": {"value": "Aggregates"}}]]
    got = C.parse_wb_countries(payload)
    assert got[0] == {"iso3": "IND", "iso2": "IN", "name": "India", "region": "South Asia",
                      "income_level": "Lower middle income", "is_aggregate": False}
    assert got[1]["is_aggregate"] is True


def test_world_bank_series_skips_missing_values():
    payload = [{"page": 1}, [
        {"countryiso3code": "IND", "date": "2024", "value": 32.9},
        {"countryiso3code": "IND", "date": "2025", "value": None},
        {"countryiso3code": "", "date": "2024", "value": 5}]]
    got = C.parse_wb_series(payload, "SH.STA.STNT.ME.ZS")
    assert [(r["iso3"], r["year"], r["value"]) for r in got] == [("IND", 2024, Decimal("32.9"))]
    assert got[0]["source"] == "World Bank" and got[0]["source_url"].endswith("SH.STA.STNT.ME.ZS")
    assert C.parse_wb_series([{"page": 1}, None], "SH.STA.STNT.ME.ZS") == []


def test_gho_country_rows_only():
    values = [{"SpatialDimType": "COUNTRY", "SpatialDim": "IND", "TimeDim": 2023, "NumericValue": 60.0},
              {"SpatialDimType": "REGION", "SpatialDim": "SEAR", "TimeDim": 2023, "NumericValue": 70.0},
              {"SpatialDimType": "COUNTRY", "SpatialDim": "FIN", "TimeDim": 2023, "NumericValue": None}]
    got = C.parse_gho_country(values, "IHRSPAR2_C13")
    assert [(r["iso3"], r["value"]) for r in got] == [("IND", Decimal("60.0"))]


def test_gho_burden_labels_hazards_and_ages():
    labels = {"FOODBORNE_HAZARD1_FOODBORNE_HAZARD1_TOX": "Chemical hazards",
              "FOODBORNE_HAZARD2_FOODBORNE_HAZARD2_LEA": "Lead"}
    values = [{"SpatialDim": "GLOBAL", "TimeDim": 2021, "Dim1": "AGEGROUP_YEARSALL",
               "Dim2": "FOODBORNE_HAZARD1_FOODBORNE_HAZARD1_TOX", "Dim3": "FOODBORNE_HAZARD2_FOODBORNE_HAZARD2_LEA",
               "NumericValue": 466010.9, "Low": 1.0, "High": 2.0},
              {"SpatialDim": "GLOBAL", "TimeDim": 2021, "Dim1": "AGEGROUP_YEARSUNDER5",
               "Dim2": "X", "Dim3": "FOODBORNE_HAZARD2_FOODBORNE_HAZARD2_ZZZ", "NumericValue": 3}]
    got = C.parse_gho_burden(values, "FOODBORNE_DTH", labels)
    assert (got[0]["hazard_group"], got[0]["hazard"], got[0]["age_group"], got[0]["measure"]) == \
        ("Chemical hazards", "Lead", "all ages", "deaths")
    assert got[1]["hazard"] == "ZZZ" and got[1]["age_group"] == "under 5"     # unknown label: code kept, not invented
