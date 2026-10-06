"""
Rate limiting in api/main.py: which bucket a request lands in, and the visitor address
behind Render's proxy.

Pinned: visitors are told apart by CF-Connecting-IP (request.client is Render's proxy,
shared by everyone), anonymous reads of the open data routes get the browsing cap while
writes and sign-in routes keep the 20/day anonymous cap, and signing in never lowers the
browsing cap.
"""

from __future__ import annotations

import time

import jwt
from starlette.requests import Request

import api.main as M
from api.auth_utils import ALGORITHM, SECRET_KEY
from api.public_rate_limit import client_ip


def _req(path: str, method: str = "GET", headers: dict[str, str] | None = None, client=("10.0.0.7", 443)) -> Request:
    return Request({
        "type": "http", "method": method, "path": path, "root_path": "", "scheme": "https",
        "query_string": b"", "server": ("api.test", 443), "client": client,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    })


def _token(tier: str) -> str:
    return jwt.encode({"sub": "u1", "type": "access", "tier": tier, "exp": int(time.time()) + 600}, SECRET_KEY, algorithm=ALGORITHM)


def test_client_ip_prefers_cloudflare_header():
    r = _req("/v1/hazards", headers={"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.1, 10.0.0.2"})
    assert client_ip(r) == "203.0.113.9"


def test_client_ip_falls_back_to_first_forwarded_hop_then_socket():
    assert client_ip(_req("/v1/hazards", headers={"X-Forwarded-For": "198.51.100.1, 10.0.0.2"})) == "198.51.100.1"
    assert client_ip(_req("/v1/hazards")) == "10.0.0.7"


def test_two_visitors_behind_the_same_proxy_get_separate_buckets():
    a = M._rate_limit_key_and_cap(_req("/v1/standards/summary", headers={"CF-Connecting-IP": "203.0.113.9"}))
    b = M._rate_limit_key_and_cap(_req("/v1/standards/summary", headers={"CF-Connecting-IP": "203.0.113.10"}))
    assert a[0] != b[0]


def test_anonymous_public_read_gets_the_browsing_cap():
    for path in ("/v1/standards/summary", "/v1/meta/sources", "/v1/research", "/v1/rasff/summary", "/v1/places/states"):
        key, cap = M._rate_limit_key_and_cap(_req(path, headers={"CF-Connecting-IP": "203.0.113.9"}))
        assert key == "ip-read:203.0.113.9" and cap == M.PUBLIC_READ_LIMIT_PER_DAY, path


def test_classify_post_counts_as_a_public_read():
    _, cap = M._rate_limit_key_and_cap(_req("/v1/classify", method="POST"))
    assert cap == M.PUBLIC_READ_LIMIT_PER_DAY


def test_writes_and_signed_in_routes_keep_the_anonymous_cap():
    for path, method in (("/v1/reports", "POST"), ("/v1/risk/map", "GET"), ("/v1/meta/sources", "POST"), ("/v1/auth/login", "POST")):
        key, cap = M._rate_limit_key_and_cap(_req(path, method=method))
        assert key.startswith("ip:") and cap == M.UNAUTH_LIMIT_PER_DAY, (path, method)


def test_signing_in_never_lowers_the_browsing_cap():
    auth = {"Authorization": f"Bearer {_token('consumer_free')}"}
    _, read_cap = M._rate_limit_key_and_cap(_req("/v1/standards/summary", headers=auth))
    _, risk_cap = M._rate_limit_key_and_cap(_req("/v1/risk/map", headers=auth))
    assert read_cap == M.PUBLIC_READ_LIMIT_PER_DAY
    assert risk_cap == M.TIER_LIMITS["consumer_free"]
