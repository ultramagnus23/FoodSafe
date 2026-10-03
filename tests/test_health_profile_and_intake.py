"""
Tests for models/health_profile.py (contamination findings -> health-outcome
profiles per origin) and models/safe_intake.py (how much food reaches a
health-based guidance value). Pure functions; no database.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from models import health_profile as HP
from models import safe_intake as SI


def _row(nid, origins, hazard, cat, risk="serious", product="nuts", year=2025, hid=None):
    return (nid, origins, risk, product, year, hid or nid * 10, hazard, cat, None, None, None)


def test_profile_counts_notifications_not_hazard_rows():
    rows = [
        _row(1, ["IN"], "Aflatoxin B1", "mycotoxins"),
        _row(1, ["IN"], "Aflatoxins total", "mycotoxins", hid=11),     # same notification, same outcomes
        _row(2, ["IN"], "Salmonella Infantis", "pathogenic micro-organisms", risk="not serious"),
        _row(3, ["TR"], "Aflatoxin B1", "mycotoxins"),
    ]
    profile, updates = HP.build(rows, min_notifications=1)
    by = {(p["scope_key"], p["outcome_key"]): p for p in profile}
    liver = by[("IN", "liver_cancer")]
    assert liver["notifications"] == 1 and liver["serious_notifications"] == 1
    assert liver["share_of_classified"] == 0.5                      # 1 of 2 classified IN notifications
    assert liver["level_counts"] == {"hazard": 1}
    assert by[("IN", "acute_gastroenteritis")]["serious_notifications"] == 0
    assert by[("ALL", "liver_cancer")]["notifications"] == 2
    assert liver["outcome"] == "Liver cancer"                       # shared outcomes get a neutral label
    assert all(s["url"].startswith("https://") for s in liver["sources"])
    assert len(updates) == 4                                         # stored classification was empty


def test_profile_respects_minimum_scope_size():
    rows = [_row(1, ["IN"], "Aflatoxin B1", "mycotoxins")]
    profile, _ = HP.build(rows, min_notifications=2)
    assert profile == []


def test_parse_jecfa_text_converts_weekly_to_daily():
    got = SI.parse_jecfa_text("PTWI 0.0007 mg/kg bw (2001); ARfD 0.09 mg/kg bw as cyanide; TDI 200 µg/kg bw")
    assert [(k, round(float(v), 6)) for k, v, _ in got] == [("chronic", 0.0001), ("acute", 0.09), ("chronic", 0.2)]


def test_guidance_preference_eu_over_jmpr_over_jecfa():
    rows = [{"body": "JECFA", "value_type": "guidance", "value": None, "unit": None, "raw_text": "PMTDI 0.5 mg/kg bw"},
            {"body": "JMPR", "value_type": "ADI", "value": 0.02, "unit": "mg/kg bw", "raw_text": "0-0.02"},
            {"body": "EU", "value_type": "ADI", "value": 0.01, "unit": "mg/kg bw/day", "raw_text": "0.01"}]
    g = SI.pick_guidance(rows)
    assert g["chronic"].value_mg_per_kg_bw_day == Decimal("0.01") and "(EU)" in g["chronic"].label


def test_assess_amounts_and_no_threshold_hazards():
    refs = [{"body": "EU", "value_type": "ADI", "value": 0.01, "unit": "mg/kg bw/day", "raw_text": "",
             "source_ref": None, "source_url": "u"},
            {"body": "EU", "value_type": "ARfD", "value": 0.05, "unit": "mg/kg bw", "raw_text": "",
             "source_ref": None, "source_url": "u"}]
    a = SI.assess("x", Decimal("0.5"), Decimal("60"), refs)
    assert a["chronic"]["grams"] == 1200.0 and a["acute"]["grams"] == 6000.0     # 0.01*60/0.5*1000, 0.05*60/0.5*1000
    assert a["chronic"]["reachable_by_eating"] is True
    tiny = SI.assess("x", Decimal("0.0001"), Decimal("60"), refs)
    assert tiny["chronic"]["reachable_by_eating"] is False
    for k in ("aflatoxins_total", "ethylene_oxide", "lead", "chlorpyrifos"):
        r = SI.assess(k, Decimal("1"), Decimal("60"), refs)
        assert r["computable"] is False and r["chronic"] is None and r["reason"]
    assert SI.assess("x", None, Decimal("60"), refs)["reason"] == "no measured concentration"
    assert SI.assess("x", Decimal("1"), Decimal("60"), [])["computable"] is False
