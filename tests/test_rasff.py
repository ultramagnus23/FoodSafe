"""
Tests for pipeline/sources/rasff.py (EU RASFF notifications about Indian-origin
food). The fixtures are real API responses (list entry + detail), trimmed; the
detail's named contact person is deliberately absent — the parser must never
read it. No network, no database.
"""
from __future__ import annotations

import urllib.error
from datetime import date
from decimal import Decimal

import pytest

from pipeline.sources import rasff as R

# ---- real records ---------------------------------------------------------

LISTED = {
    "notifId": 873205, "ecValidationDate": "16-09-2026 15:36:22", "reference": "2026.8210",
    "notifyingCountry": {"organizationName": "Spain", "isoCode": "ES"},
    "subject": "Ethylene oxide in cumin seeds from India",
    "productCategory": {"id": 18427, "description": "herbs and spices"},
    "productType": {"id": 283, "description": "food"},
    "notificationClassification": {"id": 305, "description": "border rejection notification"},
    "riskDecision": {"id": 1, "description": "potentially serious"},
    "originCountries": [{"organizationName": "India", "isoCode": "IN"}],
}
DETAIL = {
    "id": 873205, "reference": "2026.8210",
    "notificationBasis": {"description": "border control - consignment detained"},
    "product": {
        "description": "Cumin seeds",
        "hazards": [{
            "name": "ethylene oxide  - pesticide residues", "analyticalResult": "0.26 ", "unit": "mg/kg - ppm",
            "samplingDate": "03-09-2026 00:00:00", "maxPermittedLvlQuantities": "0.1",
            "maxPermittedLvlUnit": "mg/kg - ppm", "hazardCategory": {"description": "pesticide residues"},
        }],
        "measures": [{"takenBy": {"isoCode": "ES"}, "actionTaken": {"description": "official detention"}}],
        "distributionStatus": {"description": "no distribution from notifying country"},
    },
    "risk": {"riskDecision": "potentially serious"},
    "additionalInformations": [{"organization": "MAPA", "contactPerson": "A NAMED OFFICIAL"}],
}


# ---- numbers and units ------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0.26 ", (Decimal("0.26"), "=")),
    ("5,0", (Decimal("5.0"), "=")),                 # decimal comma
    ("0,125", (Decimal("0.125"), "=")),             # leading 0: unambiguous decimal
    ("42�13", (Decimal("42"), "=")),           # the API's mangled '±'
    ("42±13", (Decimal("42"), "=")),
    ("81.1 ± 40.6", (Decimal("81.1"), "=")),
    (">150000", (Decimal("150000"), ">")),
    ("<0.01", (Decimal("0.01"), "<")),
    ("1,000", (None, "")),                           # thousand or 1.000? refused, not guessed
    ("1.5-2.3", (None, "")),                         # a range
    ("nd", (None, "")), ("", (None, "")), (None, (None, "")), ("positive", (None, "")),
    ("-3", (None, "")),
])
def test_parse_result(raw, expected):
    assert R.parse_result(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("mg/kg - ppm", "mg/kg"), ("�g/kg - ppb", "ug/kg"), ("µg/kg - ppb", "ug/kg"),
    ("mg/l", "mg/l"), ("%", "%"), ("CFU/g", "CFU/g"), ("/25g", "/25g"),
    ("mg/kg dry matter", "mg/kg dry matter"),       # not silently treated as wet weight
    (None, None), ("", None),
])
def test_normalise_unit(raw, expected):
    assert R.normalise_unit(raw) == expected


D = Decimal


@pytest.mark.parametrize("value,q,unit,limit,lunit,expected", [
    (D("0.26"), "=", "mg/kg", D("0.1"), "mg/kg", (D("2.6000"), True)),
    (D("0.05"), "=", "mg/kg", D("0.1"), "mg/kg", (D("0.5000"), False)),
    (D("150000"), ">", "mg/kg", D("100000"), "mg/kg", (None, True)),      # censored but certainly over
    (D("0.01"), "<", "mg/kg", D("0.05"), "mg/kg", (None, False)),         # censored and certainly under
    (D("0.5"), "<", "mg/kg", D("0.05"), "mg/kg", (None, None)),           # '<0.5' vs 0.05: unknowable
    (D("4.2"), "=", "mg/kg", D("0"), "mg/kg", (None, True)),              # zero tolerance
    (D("0"), "=", "mg/kg", D("0"), "mg/kg", (None, False)),
    (D("1"), "=", "mg/kg", D("1"), "ug/kg", (None, None)),                # units differ: never compared
    (D("150000"), "=", "CFU/g", D("100000"), "CFU/g", (None, None)),      # not a comparable unit
    (None, "", "mg/kg", D("1"), "mg/kg", (None, None)),
    (D("1"), "=", "mg/kg", None, "mg/kg", (None, None)),
])
def test_compare_to_limit(value, q, unit, limit, lunit, expected):
    assert R.compare_to_limit(value, q, unit, limit, lunit) == expected


# ---- notification parsing ------------------------------------------------------

def test_a_real_notification_parses_with_its_hazard_and_limit():
    row = R.parse_notification(LISTED, DETAIL)
    assert row["notif_id"] == 873205 and row["validation_date"] == date(2026, 9, 16)
    assert row["origin_countries"] == ["IN"] and row["notifying_country"] == "ES" and row["has_detail"]
    assert row["product_name"] == "Cumin seeds" and row["actions_taken"] == ["official detention"]
    assert row["basis"] == "border control - consignment detained"
    (h,) = row["hazards"]
    assert h["hazard"] == "ethylene oxide" and h["hazard_category"] == "pesticide residues"
    assert (h["result_value"], h["result_unit"], h["limit_value"], h["limit_unit"]) == (D("0.26"), "mg/kg", D("0.1"), "mg/kg")
    assert h["exceedance_ratio"] == D("2.6000") and h["exceeds_limit"] is True and h["sampling_date"] == date(2026, 9, 3)


def test_the_named_contact_person_is_never_carried_into_the_row():
    row = R.parse_notification(LISTED, DETAIL)
    assert "A NAMED OFFICIAL" not in repr(row) and "MAPA" not in repr(row)


def test_a_notification_without_detail_keeps_its_list_level_fields():
    row = R.parse_notification(LISTED, None)
    assert row["has_detail"] is False and row["hazards"] == []
    assert row["risk_decision"] == "potentially serious" and row["product_category"] == "herbs and spices"


def test_a_detail_for_a_different_notification_is_not_attached():
    other = dict(DETAIL, id=1)
    row = R.parse_notification(LISTED, other)
    assert row["has_detail"] is False and row["hazards"] == []


def test_a_notification_not_of_indian_origin_is_refused():
    listed = dict(LISTED, originCountries=[{"isoCode": "PK"}])
    assert R.parse_notification(listed, DETAIL) is None
    assert R.parse_notification(dict(LISTED, originCountries=[]), None) is None


def test_multi_origin_notification_that_includes_india_is_kept():
    listed = dict(LISTED, originCountries=[{"isoCode": "TR"}, {"isoCode": "IN"}])
    assert R.parse_notification(listed, None)["origin_countries"] == ["IN", "TR"]


@pytest.mark.parametrize("bad", [dict(LISTED, ecValidationDate="not a date"), dict(LISTED, notifId="x"), {}])
def test_malformed_records_are_refused_not_guessed(bad):
    assert R.parse_notification(bad, None) is None


def test_a_hazard_with_an_unreadable_value_keeps_the_text_but_no_number():
    detail = dict(DETAIL, product=dict(DETAIL["product"], hazards=[{
        "name": "Salmonella spp.  - pathogenic micro-organisms", "analyticalResult": "positive in 25 g",
        "unit": "/25g", "hazardCategory": {"description": "pathogenic micro-organisms"}}]))
    (h,) = R.parse_notification(LISTED, detail)["hazards"]
    assert h["hazard"] == "Salmonella spp." and h["result_raw"] == "positive in 25 g"
    assert h["result_value"] is None and h["exceedance_ratio"] is None and h["exceeds_limit"] is None


# ---- which details to fetch ------------------------------------------------------

def _l(nid, day):
    return {"notifId": nid, "ecValidationDate": f"{day} 10:00:00"}


def test_plan_prioritises_new_then_backlog_then_recent_unavailable_newest_first():
    today = date(2026, 9, 19)
    listed = [_l(1, "01-01-2021"), _l(2, "10-09-2026"), _l(3, "01-06-2026"), _l(4, "12-09-2026"), _l(5, "05-05-2024"), _l(6, "01-02-2022")]
    known = {
        2: (False, True),     # attempted, no detail, recent (9 days)  -> retry
        3: (False, True),     # attempted, no detail, 110 days old      -> leave
        4: (True, True),      # has detail                              -> leave
        5: (False, False),    # stored, never attempted (backfill)      -> fetch
    }                         # 1 and 6 are new                          -> fetch
    assert R.plan_detail_fetches(listed, known, today) == [2, 5, 6, 1]


# ---- the run ----------------------------------------------------------------------

class _Cur:
    def __init__(self, log, fetch=()):
        self.log, self._fetch = log, fetch

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split())[:50], params))

    def fetchall(self):
        return list(self._fetch)


class _Conn:
    def __init__(self, known=()):
        self.log, self.commits, self._known = [], 0, known

    def cursor(self):
        return _Cur(self.log, self._known)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _run(monkeypatch, listed, detail, known=(), limit=100):
    conn = _Conn(known)
    monkeypatch.setattr(R, "pg_connect", lambda: conn)
    monkeypatch.setattr(R, "fetch_all_listed", lambda: listed)
    monkeypatch.setattr(R, "fetch_detail", detail)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    return R.run(limit), conn


def test_first_run_stores_every_notification_and_fetches_details_up_to_the_cap(monkeypatch):
    listed = [dict(LISTED, notifId=100 + i, ecValidationDate=f"{10 + i:02d}-09-2026 10:00:00") for i in range(5)]
    fetched = []

    def detail(nid):
        fetched.append(nid)
        return dict(DETAIL, id=nid)
    summary, conn = _run(monkeypatch, listed, detail, limit=2)
    assert summary["new_notifications"] == 5 and summary["inserted"] == 5
    assert summary["detail_fetched"] == 2 and summary["backlog_remaining"] == 3
    assert sorted(fetched) == [103, 104]                     # the newest two
    assert sum(1 for e in conn.log if e[0].startswith("INSERT INTO rasff_hazards")) == 2


def test_a_notification_with_no_public_detail_is_marked_attempted_and_not_retried(monkeypatch):
    summary, conn = _run(monkeypatch, [LISTED], lambda nid: None)
    assert summary["detail_unavailable"] == 1 and summary["detail_fetched"] == 0
    assert any(e[0].startswith("UPDATE rasff_notifications SET detail_checked_at") for e in conn.log)
    assert not any(e[0].startswith("DELETE FROM rasff_hazards") for e in conn.log)   # nothing stored to wipe


def test_hazards_are_replaced_only_when_detail_was_obtained(monkeypatch):
    summary, conn = _run(monkeypatch, [LISTED], lambda nid: dict(DETAIL))
    verbs = [e[0].split()[0] for e in conn.log]
    assert "DELETE" in verbs and verbs.count("INSERT") == 3      # notification (list level), notification (with detail), 1 hazard


def test_an_unreachable_api_raises_instead_of_reporting_nothing_new(monkeypatch):
    def down():
        raise R.RasffUnavailable("RASFF list page 1 failed")
    monkeypatch.setattr(R, "fetch_all_listed", down)
    monkeypatch.setattr(R, "pg_connect", lambda: _Conn())
    with pytest.raises(R.RasffUnavailable):
        R.run()


def test_fetch_all_listed_turns_an_http_error_into_rasff_unavailable(monkeypatch):
    def boom(page):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(R, "fetch_list_page", boom)
    with pytest.raises(R.RasffUnavailable):
        R.fetch_all_listed()


def test_fetch_all_listed_reads_every_page(monkeypatch):
    pages = {1: {"notifications": [1, 2], "totalPages": 3}, 2: {"notifications": [3], "totalPages": 3},
             3: {"notifications": [4], "totalPages": 3}}
    monkeypatch.setattr(R, "fetch_list_page", lambda p: pages[p])
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    assert R.fetch_all_listed() == [1, 2, 3, 4]


def test_a_detail_error_is_counted_not_fatal(monkeypatch):
    def flaky(nid):
        raise RuntimeError("boom")
    summary, _ = _run(monkeypatch, [LISTED], flaky)
    assert summary["detail_errors"] == 1 and summary["new_notifications"] == 1


def test_a_run_with_nothing_new_says_so(monkeypatch):
    known = [(873205, True, True)]
    summary, _ = _run(monkeypatch, [LISTED], lambda nid: None, known=known)
    assert summary["inserted"] == 0 and "nothing new" in summary["note"]
