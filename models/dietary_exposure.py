"""
FoodSafe India — Dietary Exposure Estimation

Converts a district-level contamination measurement (PPB in food) into a
human dietary intake estimate (µg contaminant per kg bodyweight per day),
using the EFSA dietary exposure assessment methodology:

    daily_intake_ug   = contamination_ppb * consumption_g_per_day * 1e-6
    intake_per_kg_bw  = daily_intake_ug / bodyweight_kg

Consumption data comes from `icmr_consumption` (state -> national fallback,
same table `schema_migration_002.sql` already seeds). JECFA bodyweights are
used because JECFA's India-specific values differ from WHO's global default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("foodsafe.models.dietary_exposure")

# JECFA bodyweights (kg) — India-specific, not WHO's 70kg adult default.
BODYWEIGHT_KG = {
    "adult": 60.0,
    "child_0_5": 15.0,
    "pregnant": 62.0,
}

# icmr_consumption.age_group doesn't have a single "child_0_5" bucket; map
# our exposure "population" scenarios onto the closest seeded age_group.
POPULATION_TO_AGE_GROUP = {
    "adult": "adult",
    "child_0_5": "child_1_3",
    "pregnant": "pregnant",
}


@dataclass
class ExposureEstimate:
    daily_intake_ug_per_kg_bw: Optional[float]
    weekly_intake_ug_per_kg_bw: Optional[float]
    twi_fraction: Optional[float]  # intake / TWI, only set by caller with a TWI
    consumption_g_day: Optional[float]
    contamination_ppb: float
    consumer_scenario: str
    data_source: str


class DietaryExposureEstimator:
    """
    Looks up consumption (g/day) from icmr_consumption and converts a
    contamination measurement into per-kg-bodyweight intake.

    Falls back state -> national when no state-specific consumption row
    exists, matching the pattern already used elsewhere in the pipeline.
    """

    def __init__(self, conn=None):
        # Lazily connect only if the caller didn't hand one in (keeps this
        # usable both from batch jobs with an open connection and from
        # standalone unit-style calls).
        self._conn = conn
        self._owns_conn = conn is None
        self._consumption_cache: dict[tuple, Optional[dict]] = {}

    def _get_conn(self):
        if self._conn is None:
            from pipeline.config import pg_connect
            self._conn = pg_connect()
        return self._conn

    def _lookup_consumption(
        self, commodity_id: int, state: Optional[str], age_group: str
    ) -> Optional[dict]:
        key = (commodity_id, state, age_group)
        if key in self._consumption_cache:
            return self._consumption_cache[key]

        import psycopg2.extras
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = None
            if state:
                cur.execute(
                    """
                    SELECT grams_per_day, p95_consumption_g_per_day, p99_consumption_g_per_day,
                           source_doc AS data_source, 'state' AS granularity
                    FROM icmr_consumption
                    WHERE commodity_id = %s AND state = %s AND age_group = %s AND sex = 'all'
                    LIMIT 1
                    """,
                    (commodity_id, state, age_group),
                )
                row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT grams_per_day, p95_consumption_g_per_day, p99_consumption_g_per_day,
                           source_doc AS data_source, 'national' AS granularity
                    FROM icmr_consumption
                    WHERE commodity_id = %s AND state IS NULL AND age_group = %s AND sex = 'all'
                    LIMIT 1
                    """,
                    (commodity_id, age_group),
                )
                row = cur.fetchone()
        self._consumption_cache[key] = dict(row) if row else None
        return self._consumption_cache[key]

    def estimate(
        self,
        contamination_ppb: float,
        commodity_id: int,
        state: Optional[str] = None,
        consumer_type: str = "mean",   # "mean" | "p95" | "p99"
        population: str = "adult",     # "adult" | "child_0_5" | "pregnant"
    ) -> ExposureEstimate:
        if contamination_ppb is None:
            return ExposureEstimate(None, None, None, None, contamination_ppb, consumer_type, "no_measurement")

        age_group = POPULATION_TO_AGE_GROUP.get(population, "adult")
        bodyweight_kg = BODYWEIGHT_KG.get(population, BODYWEIGHT_KG["adult"])

        consumption_row = self._lookup_consumption(commodity_id, state, age_group)
        if not consumption_row:
            return ExposureEstimate(None, None, None, None, contamination_ppb, consumer_type, "no_consumption_data")

        if consumer_type == "p95" and consumption_row.get("p95_consumption_g_per_day"):
            grams_per_day = float(consumption_row["p95_consumption_g_per_day"])
        elif consumer_type == "p99" and consumption_row.get("p99_consumption_g_per_day"):
            grams_per_day = float(consumption_row["p99_consumption_g_per_day"])
        else:
            grams_per_day = float(consumption_row["grams_per_day"])

        # contamination_ppb == µg contaminant per kg food; grams_per_day/1000 = kg food/day.
        daily_intake_ug = contamination_ppb * (grams_per_day / 1000.0)
        intake_per_kg_bw = daily_intake_ug / bodyweight_kg

        data_source = (
            consumption_row.get("data_source") or "icmr_consumption"
        )
        if consumption_row.get("granularity") == "national" and state:
            data_source = f"{data_source} (national_proxy, no {state} data)"

        return ExposureEstimate(
            daily_intake_ug_per_kg_bw=round(intake_per_kg_bw, 6),
            weekly_intake_ug_per_kg_bw=round(intake_per_kg_bw * 7, 6),
            twi_fraction=None,
            consumption_g_day=grams_per_day,
            contamination_ppb=contamination_ppb,
            consumer_scenario=consumer_type,
            data_source=data_source,
        )

    def close(self):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None
