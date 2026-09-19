"""
Route-level tests for api/routes/research.py, against a fake asyncpg pool.

What is pinned here is what the code review found reachable from the public
internet: out-of-range ids/offsets and NUL bytes in `q` used to reach asyncpg
and surface as HTTP 500, and the detail route returned an arbitrary
(paper, contaminant) pair for a paper linked to several contaminants.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import research as R


class _Conn:
    def __init__(self, log, rows=None):
        self.log = log
        self.rows = rows or []

    async def fetchval(self, sql, *args):
        self.log.append(("fetchval", sql, args))
        return len(self.rows)

    async def fetch(self, sql, *args):
        self.log.append(("fetch", sql, args))
        return self.rows

    async def fetchrow(self, sql, *args):
        self.log.append(("fetchrow", sql, args))
        return self.rows[0] if self.rows else None


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def _detail_row(**over):
    row = {
        "id": 7, "contaminant_id": 3, "contaminant_name": "lead", "title": "T",
        "authors": ["A"], "journal": None, "publication_year": 2020, "doi": None,
        "landing_page_url": "https://x", "evidence_level": "C",
        "matched_health_terms": [], "is_oa": None, "study_design": None,
        "source_apis": ["openalex"], "abstract": "abs", "pmid": None,
        "pmcid": None, "oa_status": None, "work_type": None,
    }
    row.update(over)
    return row


@pytest.fixture
def client_and_log(monkeypatch):
    log: list = []
    conn = _Conn(log, rows=[_detail_row()])
    monkeypatch.setattr(R, "get_pool", lambda: _Pool(conn))
    app = FastAPI()
    app.include_router(R.research_router, prefix="/v1/research")
    return TestClient(app), log


@pytest.mark.parametrize("qs", [
    "contaminant_id=0",
    "contaminant_id=-1",
    "contaminant_id=2147483648",
    "contaminant_id=99999999999999999999",
    "offset=1000001",
    "offset=9223372036854775808",
])
def test_list_rejects_out_of_range_numbers_with_422_not_500(client_and_log, qs):
    client, log = client_and_log
    r = client.get(f"/v1/research?{qs}")
    assert r.status_code == 422
    assert log == []  # never reached the database


@pytest.mark.parametrize("path", ["/v1/research/0", "/v1/research/-3", "/v1/research/2147483648"])
def test_detail_rejects_out_of_range_id(client_and_log, path):
    client, log = client_and_log
    assert client.get(path).status_code == 422
    assert log == []


def test_detail_rejects_out_of_range_contaminant(client_and_log):
    client, log = client_and_log
    assert client.get("/v1/research/7?contaminant_id=2147483648").status_code == 422
    assert log == []


def test_nul_in_search_is_stripped_not_a_500(client_and_log):
    client, log = client_and_log
    r = client.get("/v1/research", params={"q": "lea\x00d"})
    assert r.status_code == 200
    pattern = log[0][2][1]
    assert "\x00" not in pattern
    assert pattern == "%lead%"


def test_search_of_only_nul_and_spaces_means_no_filter(client_and_log):
    client, log = client_and_log
    client.get("/v1/research", params={"q": " \x00 "})
    assert log[0][2][1] is None


def test_like_wildcards_are_escaped(client_and_log):
    client, log = client_and_log
    client.get("/v1/research", params={"q": "50%_off\\"})
    assert log[0][2][1] == "%50\\%\\_off\\\\%"


def test_detail_is_deterministic_and_can_target_a_contaminant(client_and_log):
    client, log = client_and_log
    r = client.get("/v1/research/7")
    assert r.status_code == 200 and r.json()["contaminant_id"] == 3
    kind, sql, args = log[-1]
    assert "ORDER BY crl.contaminant_id" in sql       # deterministic without a filter
    assert args == (7, None)

    client.get("/v1/research/7?contaminant_id=5")
    assert log[-1][2] == (7, 5)


def test_detail_404_when_no_such_pair(monkeypatch):
    log: list = []
    monkeypatch.setattr(R, "get_pool", lambda: _Pool(_Conn(log, rows=[])))
    app = FastAPI()
    app.include_router(R.research_router, prefix="/v1/research")
    assert TestClient(app).get("/v1/research/7?contaminant_id=5").status_code == 404
