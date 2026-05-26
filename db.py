"""
FoodSafe India — Async Database Pool
Uses asyncpg for high-performance async PostgreSQL.
"""

from __future__ import annotations

import asyncpg
import os
import logging

logger = logging.getLogger("foodsafe.db")

_pool: asyncpg.Pool | None = None

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://foodsafe_app:password@localhost:5432/foodsafe",
)

# asyncpg uses postgresql:// not postgresql+asyncpg://
_ASYNCPG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


async def init_pool(min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        _ASYNCPG_URL,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
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
