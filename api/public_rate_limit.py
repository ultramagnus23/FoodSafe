"""
FoodSafe India — Persisted rate limiting for unauthenticated public POSTs.

POST /v1/reports and POST /v1/disputes/submit take no auth (by design —
"make it easy to report a problem"), so they're the two endpoints spam/
abuse would hit first. The global in-memory limiter in api/main.py covers
them today, but it resets on every deploy and doesn't share state across
multiple Render instances. This gives them a durable, DB-backed limit,
mirroring the pattern api/auth_utils.py already uses for API-key clients
(api_key_usage) — see schema_migration_008.sql for public_submission_log.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import HTTPException, Request, status

from api.db import get_pool

logger = logging.getLogger("foodsafe.public_rate_limit")

# Generous but real ceilings — these endpoints feed an admin review queue,
# not the public directly, so the cost of a false positive (a genuine
# reporter blocked) is worse than letting a modest amount of spam through
# to be rejected by a human reviewer.
DAILY_LIMITS = {
    "reports": 10,
    "disputes": 10,
}


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()


async def enforce_public_rate_limit(request: Request, endpoint: str) -> None:
    """Raise 429 if this client IP has exceeded the daily cap for `endpoint`.
    Call before writing the submission; on pass, also logs the attempt."""
    limit = DAILY_LIMITS.get(endpoint, 10)
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(client_ip)

    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM public_submission_log
            WHERE ip_hash = $1 AND endpoint = $2 AND created_at >= NOW() - INTERVAL '24 hours'
            """,
            ip_hash, endpoint,
        )
        if count >= limit:
            logger.warning("Public submission rate limit hit for endpoint=%s", endpoint)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many submissions from this network today (limit {limit}/day). Try again tomorrow.",
            )
        await conn.execute(
            "INSERT INTO public_submission_log (ip_hash, endpoint) VALUES ($1, $2)",
            ip_hash, endpoint,
        )
