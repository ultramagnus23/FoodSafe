"""
FoodSafe India — Provenance helpers (H1.1)

Every risk/search/comparison surface must disclose whether the enforcement
records backing a number are real or the seed-demo synthetic fill
(pipeline/seed_enforcement.py, etl_version='seed-demo'). This module is the
single place that computes that split so the frontend, API, and any future
endpoint all agree on the same definition.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ProvenanceSummary(BaseModel):
    real_count: int
    synthetic_count: int
    synthetic_fraction: Optional[float]
    # True if any underlying record is synthetic. Deliberately conservative —
    # a mixed real+synthetic result is still flagged, since a user has no way
    # to tell which specific number came from which record.
    is_synthetic: bool


def compute_synthetic_fraction(real_count: int, synthetic_count: int) -> Optional[float]:
    total = real_count + synthetic_count
    if total == 0:
        return None
    return round(synthetic_count / total, 4)


def summarize(real_count: int, synthetic_count: int) -> ProvenanceSummary:
    return ProvenanceSummary(
        real_count=real_count,
        synthetic_count=synthetic_count,
        synthetic_fraction=compute_synthetic_fraction(real_count, synthetic_count),
        is_synthetic=synthetic_count > 0,
    )


EMPTY_PROVENANCE = ProvenanceSummary(
    real_count=0, synthetic_count=0, synthetic_fraction=None, is_synthetic=False,
)


async def fetch_provenance(conn, where_clause: str, *args) -> ProvenanceSummary:
    """Single-target provenance lookup, e.g. one district+commodity or one brand+commodity."""
    row = await conn.fetchrow(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE etl_version IS DISTINCT FROM 'seed-demo') AS real_count,
            COUNT(*) FILTER (WHERE etl_version = 'seed-demo') AS synthetic_count
        FROM enforcement_records
        WHERE {where_clause}
        """,
        *args,
    )
    return summarize(row["real_count"] or 0, row["synthetic_count"] or 0)


async def fetch_provenance_by_district(conn, commodity_id: int) -> dict[int, ProvenanceSummary]:
    """Bulk provenance grouped by district_id, for map/best-districts endpoints."""
    rows = await conn.fetch(
        """
        SELECT district_id,
               COUNT(*) FILTER (WHERE etl_version IS DISTINCT FROM 'seed-demo') AS real_count,
               COUNT(*) FILTER (WHERE etl_version = 'seed-demo') AS synthetic_count
        FROM enforcement_records
        WHERE commodity_id = $1 AND district_id IS NOT NULL
        GROUP BY district_id
        """,
        commodity_id,
    )
    return {
        r["district_id"]: summarize(r["real_count"] or 0, r["synthetic_count"] or 0)
        for r in rows
    }


async def fetch_provenance_by_commodity(conn, commodity_ids: list[int]) -> dict[int, ProvenanceSummary]:
    if not commodity_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT commodity_id,
               COUNT(*) FILTER (WHERE etl_version IS DISTINCT FROM 'seed-demo') AS real_count,
               COUNT(*) FILTER (WHERE etl_version = 'seed-demo') AS synthetic_count
        FROM enforcement_records
        WHERE commodity_id = ANY($1::int[])
        GROUP BY commodity_id
        """,
        commodity_ids,
    )
    return {
        r["commodity_id"]: summarize(r["real_count"] or 0, r["synthetic_count"] or 0)
        for r in rows
    }


async def fetch_provenance_by_brand(conn, brand_ids: list[int]) -> dict[int, ProvenanceSummary]:
    if not brand_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT brand_id,
               COUNT(*) FILTER (WHERE etl_version IS DISTINCT FROM 'seed-demo') AS real_count,
               COUNT(*) FILTER (WHERE etl_version = 'seed-demo') AS synthetic_count
        FROM enforcement_records
        WHERE brand_id = ANY($1::int[])
        GROUP BY brand_id
        """,
        brand_ids,
    )
    return {
        r["brand_id"]: summarize(r["real_count"] or 0, r["synthetic_count"] or 0)
        for r in rows
    }
