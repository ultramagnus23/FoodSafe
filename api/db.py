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
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        kwargs["ssl"] = ctx
    return kwargs


async def init_pool(min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
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
