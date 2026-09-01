"""
FoodSafe India — Async Database Pool
Uses asyncpg for high-performance async PostgreSQL.
"""

from __future__ import annotations

import asyncpg
import os
import logging

# Load a local .env (if present) so DATABASE_URL etc. are available without
# having to export them. Optional dependency — if python-dotenv isn't
# installed we just fall back to the real process environment.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("foodsafe.db")

_pool: asyncpg.Pool | None = None

# Supabase's connection pooler (Supavisor) serves a cert chain rooted in
# Supabase's own private CA ("Supabase Root 2021 CA") — confirmed via
# `openssl s_client -connect <pooler host>:5432 -starttls postgres
# -showcerts`, which shows the chain terminating in a self-signed cert
# issued by/to "Supabase Inc". This root is NOT in certifi, the OS trust
# store, or any public CA bundle — no amount of "use a better/更complete CA
# bundle" fixes it, because the issuer was never publicly cross-signed. We
# pin it explicitly so the connection still gets real certificate
# verification (protection against a network-level MITM) rather than
# disabling verification outright.
_SUPABASE_ROOT_CA = """-----BEGIN CERTIFICATE-----
MIIDxDCCAqygAwIBAgIUbLxMod62P2ktCiAkxnKJwtE9VPYwDQYJKoZIhvcNAQEL
BQAwazELMAkGA1UEBhMCVVMxEDAOBgNVBAgMB0RlbHdhcmUxEzARBgNVBAcMCk5l
dyBDYXN0bGUxFTATBgNVBAoMDFN1cGFiYXNlIEluYzEeMBwGA1UEAwwVU3VwYWJh
c2UgUm9vdCAyMDIxIENBMB4XDTIxMDQyODEwNTY1M1oXDTMxMDQyNjEwNTY1M1ow
azELMAkGA1UEBhMCVVMxEDAOBgNVBAgMB0RlbHdhcmUxEzARBgNVBAcMCk5ldyBD
YXN0bGUxFTATBgNVBAoMDFN1cGFiYXNlIEluYzEeMBwGA1UEAwwVU3VwYWJhc2Ug
Um9vdCAyMDIxIENBMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqQXW
QyHOB+qR2GJobCq/CBmQ40G0oDmCC3mzVnn8sv4XNeWtE5XcEL0uVih7Jo4Dkx1Q
DmGHBH1zDfgs2qXiLb6xpw/CKQPypZW1JssOTMIfQppNQ87K75Ya0p25Y3ePS2t2
GtvHxNjUV6kjOZjEn2yWEcBdpOVCUYBVFBNMB4YBHkNRDa/+S4uywAoaTWnCJLUi
cvTlHmMw6xSQQn1UfRQHk50DMCEJ7Cy1RxrZJrkXXRP3LqQL2ijJ6F4yMfh+Gyb4
O4XajoVj/+R4GwywKYrrS8PrSNtwxr5StlQO8zIQUSMiq26wM8mgELFlS/32Uclt
NaQ1xBRizkzpZct9DwIDAQABo2AwXjALBgNVHQ8EBAMCAQYwHQYDVR0OBBYEFKjX
uXY32CztkhImng4yJNUtaUYsMB8GA1UdIwQYMBaAFKjXuXY32CztkhImng4yJNUt
aUYsMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAB8spzNn+4VU
tVxbdMaX+39Z50sc7uATmus16jmmHjhIHz+l/9GlJ5KqAMOx26mPZgfzG7oneL2b
VW+WgYUkTT3XEPFWnTp2RJwQao8/tYPXWEJDc0WVQHrpmnWOFKU/d3MqBgBm5y+6
jB81TU/RG2rVerPDWP+1MMcNNy0491CTL5XQZ7JfDJJ9CCmXSdtTl4uUQnSuv/Qx
Cea13BX2ZgJc7Au30vihLhub52De4P/4gonKsNHYdbWjg7OWKwNv/zitGDVDB9Y2
CMTyZKG3XEu5Ghl1LEnI3QmEKsqaCLv12BnVjbkSeZsMnevJPs1Ye6TjjJwdik5P
o/bKiIz+Fq8=
-----END CERTIFICATE-----
"""

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://foodsafe_app:password@localhost:5432/foodsafe",
)

# asyncpg uses postgresql:// not postgresql+asyncpg://
_ASYNCPG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _connect_kwargs() -> dict:
    """Build explicit asyncpg connect kwargs from DATABASE_URL.

    We pass parsed components (not the raw DSN) because libpq/asyncpg can
    misparse the dotted Supabase pooler username (postgres.<ref>) from a URI,
    causing intermittent 'password authentication failed'. We also attach an
    SSL context (sslmode=require semantics) for Supabase/any remote host.
    """
    from urllib.parse import urlparse

    u = urlparse(_ASYNCPG_URL)
    kwargs: dict = dict(
        host=u.hostname,
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        database=(u.path.lstrip("/") or "postgres"),
    )
    host = u.hostname or ""
    if "supabase.com" in host or "sslmode=require" in _ASYNCPG_URL:
        import ssl as _ssl
        # Verify against certifi's public bundle *plus* Supabase's own root
        # CA (see _SUPABASE_ROOT_CA above) — do NOT disable verification
        # here. An unverified TLS context lets any network-level attacker
        # between this process and Supabase silently MITM every query,
        # including login credentials and JWTs.
        import certifi
        ctx = _ssl.create_default_context(cafile=certifi.where())
        ctx.load_verify_locations(cadata=_SUPABASE_ROOT_CA)
        # Supabase's intermediate cert ("Supabase Intermediate 2021 CA") was
        # issued without a Key Usage extension — a defect in Supabase's own
        # CA, confirmed via `openssl x509 -text` on the chain. OpenSSL 3.x's
        # strict RFC 5280 chain-building rejects CA certs missing that
        # extension outright ("CA cert does not include key usage
        # extension"), which nothing on our end can fix by supplying a
        # better/more-complete CA bundle. We relax only this one flag; full
        # chain-of-trust verification against Supabase's actual root (above)
        # still applies, so this is not equivalent to disabling verification.
        if hasattr(_ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~_ssl.VERIFY_X509_STRICT
        kwargs["ssl"] = ctx
    return kwargs


async def init_pool(min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    # statement_cache_size=0: Supabase's pooler on port 6543 is PgBouncer/
    # Supavisor in *transaction* mode, which hands out a different backend
    # connection per transaction. asyncpg's default server-side prepared
    # statement cache assumes a stable backend connection, so under
    # transaction pooling it causes "prepared statement already exists" /
    # "does not exist" errors intermittently. Disabling it falls back to
    # asyncpg re-preparing per-call, which is the documented pgbouncer/
    # Supavisor-transaction-mode workaround. If DATABASE_URL points at the
    # *session* pooler (port 5432) instead, this is unnecessary but harmless.
    _pool = await asyncpg.create_pool(
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
        statement_cache_size=0,
        **_connect_kwargs(),
    )
    logger.info("DB pool initialised (min=%d max=%d)", min_size, max_size)


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
    logger.info("DB pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call init_pool() first.")
    return _pool


class _UserScopedConnection:
    """Acquires a pool connection, opens a transaction, and sets
    app.user_id for its duration via set_config(..., is_local=true).

    This makes the RLS policies in schema.sql (users_self, api_keys_own)
    real for any route that uses this instead of pool.acquire() directly —
    today those policies are inert because nothing ever sets app.user_id
    and the app connects as the DB owner (which bypasses RLS entirely).
    set_config's third arg (is_local) mirrors SET LOCAL: the setting is
    scoped to the current transaction and vanishes on commit/rollback, so
    it can never leak onto a pooled connection reused by a different user.

    Note this only takes effect once DATABASE_URL points at a non-owner
    role (e.g. foodsafe_app) that RLS actually applies to — connecting as
    the table owner bypasses RLS regardless of app.user_id. See
    docs/RLS_ACTIVATION.md for the activation steps and why login/register
    can't be scoped this way (the user_id isn't known until credentials
    are checked).
    """

    def __init__(self, pool: asyncpg.Pool, user_id: str):
        self._pool = pool
        self._user_id = user_id
        self._conn: asyncpg.Connection | None = None
        self._tx = None

    async def __aenter__(self) -> asyncpg.Connection:
        self._conn = await self._pool.acquire()
        self._tx = self._conn.transaction()
        await self._tx.start()
        await self._conn.execute("SELECT set_config('app.user_id', $1, true)", self._user_id)
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                await self._tx.commit()
            else:
                await self._tx.rollback()
        finally:
            await self._pool.release(self._conn)


def user_scoped(user_id: str) -> _UserScopedConnection:
    """Use in place of `pool.acquire()` for DB work scoped to one
    already-authenticated user (profile, API keys, refresh tokens) so RLS
    policies keyed on app.user_id apply. See _UserScopedConnection."""
    return _UserScopedConnection(get_pool(), user_id)
