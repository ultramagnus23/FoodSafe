"""
Route-level tests for the public country, nutrition and places routes
(api/routes/countries.py, nutrition.py, places.py) against a fake asyncpg pool.

Pinned: bad input is rejected before it reaches the database (a NUL byte or an
out-of-pattern code used to surface as HTTP 500 on other routes), unknown keys are
404s, and the app registers every prefix.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import countries as C
from api.routes import nutrition as N
from api.routes import places as P


class _Conn:
    def __init__(self, log):
        self.log = log

    async def fetchval(self, sql, *args):
        self.log.append(("fetchval", sql, args))
        return None

    async def fetch(self, sql, *args):
        self.log.append(("fetch", sql, args))
        return []

    async def fetchrow(self, sql, *args):
        self.log.append(("fetchrow", sql, args))
        return None


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


@pytest.fixture
def client(monkeypatch):
    log: list = []
    pool = _Pool(_Conn(log))
    for mod in (C, N, P):
        monkeypatch.setattr(mod, "get_pool", lambda: pool)
    app = FastAPI()
    app.include_router(C.countries_router, prefix="/v1/countries")
    app.include_router(C.global_router, prefix="/v1/global")
    app.include_router(N.nutrition_router, prefix="/v1/nutrition")
    app.include_router(P.places_router, prefix="/v1/places")
    c = TestClient(app)
    c.db_log = log
    return c


@pytest.mark.parametrize("code", ["I", "INDI", "I1", "1N"])
def test_country_code_must_be_iso(client, code):
    assert client.get(f"/v1/countries/{code}").status_code == 422
    assert client.db_log == []


def test_unknown_country_is_404(client):
    r = client.get("/v1/countries/zz")
    assert r.status_code == 404
    assert client.db_log[0][2] == ("ZZ",)            # normalised before the query


@pytest.mark.parametrize("path", ["/v1/global/foodborne-burden?measure=cases",
                                  "/v1/global/foodborne-burden?age_group=adults",
                                  "/v1/global/foodborne-burden?year=1800"])
def test_burden_rejects_out_of_pattern_params(client, path):
    assert client.get(path).status_code == 422


def test_burden_with_nothing_loaded_is_404(client):
    assert client.get("/v1/global/foodborne-burden").status_code == 404


@pytest.mark.parametrize("code", ["abc", "1" * 21, "12-34"])
def test_barcode_must_be_digits(client, code):
    assert client.get(f"/v1/nutrition/products/{code}").status_code == 422


def test_unknown_barcode_is_404(client):
    assert client.get("/v1/nutrition/products/8901719134845").status_code == 404


@pytest.mark.parametrize("qs", ["q=a%00b", "brand=x%00", "grade=f", "high_in=sodium", "category=snacks",
                                "limit=0", "limit=201", "offset=-1"])
def test_product_search_rejects_bad_params(client, qs):
    assert client.get(f"/v1/nutrition/products?{qs}").status_code == 422
    assert client.db_log == []


def test_product_search_passes_params_positionally(client):
    r = client.get("/v1/nutrition/products?q=Biscuit&brand=Parle&grade=e&limit=5")
    assert r.status_code == 200 and r.json()["results"] == []
    _, _, args = client.db_log[-1]
    assert args == ("%biscuit%", "parle", None, "e", None, 5, 0)


def test_state_name_rejects_nul(client):
    assert client.get("/v1/places/states/Ker%00ala").status_code == 422
    assert client.db_log == []


def test_unknown_state_is_404(client):
    assert client.get("/v1/places/states/Atlantis").status_code == 404


def test_app_registers_public_prefixes():
    from api.main import app
    paths = set(app.openapi()["paths"])
    for p in ("/v1/countries", "/v1/countries/{code}", "/v1/global/foodborne-burden", "/v1/nutrition/summary",
              "/v1/nutrition/products", "/v1/nutrition/products/{code}", "/v1/places/states",
              "/v1/places/states/{state}"):
        assert p in paths, p
