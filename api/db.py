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
        # Verify the server cert against certifi's bundled root CAs, not the
        # OS trust store — do NOT disable verification here. An unverified
        # TLS context lets any network-level attacker between this process
        # and Supabase silently MITM every query, including login
        # credentials and JWTs. We use certifi explicitly (rather than
        # ssl.create_default_context()'s OS-default paths) because minimal
        # container images (e.g. Render's Python runtime) often ship without
        # a populated system CA bundle, which surfaces as a misleading
        # "self-signed certificate in certificate chain" error even though
        # Supabase's pooler cert is publicly trusted.
        import certifi
        ctx = _ssl.create_default_context(cafile=certifi.where())
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
