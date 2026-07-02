"""
FoodSafe India — Codex/EU/WHO Benchmark Comparison

FoodSafe's most legally defensible finding: the gap between what FSSAI says
is safe and what international standards say is safe. A sample can pass
India's own limit while failing Codex Alimentarius / EU limits, or while
implying a dietary intake above the WHO/JECFA Tolerable Weekly Intake (TWI).

This module never names brands — it operates on (contaminant, commodity,
district) aggregates and individual enforcement_records rows, both of which
are geographic/product facts, not brand facts.

Run the batch aggregation:  python -m models.codex_benchmark
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from models.dietary_exposure import DietaryExposureEstimator, ExposureEstimate

logger = logging.getLogger("foodsafe.models.codex_benchmark")


@dataclass
class ContaminantLimits:
    contaminant_id: int
    name: str
    fssai_limit_ppb: Optional[float]
    codex_limit_ppb: Optional[float]
    eu_limit_ppb: Optional[float]
    who_jecfa_twi_ug_per_kg: Optional[float]


@dataclass
class CodexComparison:
    fssai_status: str          # "pass" | "fail" | "unknown"
    codex_status: str
    eu_status: str
    who_twi_fraction: Optional[float]
    fssai_compliant_codex_non_compliant: bool
    interpretation: str


class CodexBenchmarkComparator:
    """Compares a single measurement against FSSAI / Codex / EU / JECFA limits."""

    def __init__(self, exposure_estimator: Optional[DietaryExposureEstimator] = None):
        self.exposure_estimator = exposure_estimator or DietaryExposureEstimator()

    @staticmethod
    def _status(value_ppb: float, limit_ppb: Optional[float]) -> str:
        if limit_ppb is None or limit_ppb <= 0:
            return "unknown"
        return "pass" if value_ppb <= limit_ppb else "fail"

    def compare(
        self,
        value_ppb: float,
        limits: ContaminantLimits,
        commodity_name: str,
        district_name: Optional[str] = None,
        state: Optional[str] = None,
        commodity_id: Optional[int] = None,
        consumer_type: str = "mean",
    ) -> CodexComparison:
        fssai_status = self._status(value_ppb, limits.fssai_limit_ppb)
        codex_status = self._status(value_ppb, limits.codex_limit_ppb)
        eu_status = self._status(value_ppb, limits.eu_limit_ppb)

        who_twi_fraction = None
        if limits.who_jecfa_twi_ug_per_kg and commodity_id is not None:
            exposure: ExposureEstimate = self.exposure_estimator.estimate(
                contamination_ppb=value_ppb,
                commodity_id=commodity_id,
                state=state,
                consumer_type=consumer_type,
            )
            if exposure.weekly_intake_ug_per_kg_bw is not None:
                who_twi_fraction = round(
                    exposure.weekly_intake_ug_per_kg_bw / limits.who_jecfa_twi_ug_per_kg, 3
                )

        flag = fssai_status == "pass" and codex_status == "fail"

        interpretation = self._build_interpretation(
            value_ppb, limits, commodity_name, district_name, who_twi_fraction,
            fssai_status, codex_status,
        )

        return CodexComparison(
            fssai_status=fssai_status,
            codex_status=codex_status,
            eu_status=eu_status,
            who_twi_fraction=who_twi_fraction,
            fssai_compliant_codex_non_compliant=flag,
            interpretation=interpretation,
        )

    @staticmethod
    def _build_interpretation(
        value_ppb: float,
        limits: ContaminantLimits,
        commodity_name: str,
        district_name: Optional[str],
        who_twi_fraction: Optional[float],
        fssai_status: str,
        codex_status: str,
    ) -> str:
        loc = f" from {district_name}" if district_name else ""
        parts = []
        if limits.codex_limit_ppb and limits.fssai_limit_ppb:
            if fssai_status == "pass" and codex_status == "fail":
                parts.append(
                    f"This district's {commodity_name}{loc} {limits.name} level "
                    f"({value_ppb:.1f} PPB) is within FSSAI's limit "
                    f"({limits.fssai_limit_ppb:.1f} PPB) but exceeds the Codex "
                    f"Alimentarius international limit ({limits.codex_limit_ppb:.1f} PPB)."
                )
            elif fssai_status == "fail" and codex_status == "fail":
                parts.append(
                    f"{commodity_name.capitalize()}{loc} {limits.name} level "
                    f"({value_ppb:.1f} PPB) exceeds both FSSAI "
                    f"({limits.fssai_limit_ppb:.1f} PPB) and Codex "
                    f"({limits.codex_limit_ppb:.1f} PPB) limits."
                )
            elif fssai_status == "fail" and codex_status == "pass":
                parts.append(
                    f"{commodity_name.capitalize()}{loc} {limits.name} level "
                    f"({value_ppb:.1f} PPB) exceeds FSSAI's limit "
                    f"({limits.fssai_limit_ppb:.1f} PPB) but is within the Codex "
                    f"Alimentarius international limit ({limits.codex_limit_ppb:.1f} PPB)."
                )
            else:
                parts.append(
                    f"{commodity_name.capitalize()}{loc} {limits.name} level "
                    f"({value_ppb:.1f} PPB) is within both FSSAI "
                    f"({limits.fssai_limit_ppb:.1f} PPB) and Codex "
                    f"({limits.codex_limit_ppb:.1f} PPB) limits."
                )
        if who_twi_fraction is not None:
            parts.append(
                f"At typical consumption levels this equates to "
                f"{who_twi_fraction:.1f}x the JECFA Tolerable Weekly Intake."
            )
        return " ".join(parts) if parts else "Insufficient benchmark data for interpretation."


# ------------------------------------------------------------
# batch aggregation: feeds agg_district_commodity_risk columns
# ------------------------------------------------------------

def compute_district_commodity_codex_fractions(conn, records_by_group: dict) -> dict:
    """
    records_by_group: {(district_id, commodity_id, quarter): [rows]} where each
    row has raw_value_ppb, legal_limit_ppb, contaminant_id (as produced by
    models/aggregate.py's _load_records, grouped the same way as
    aggregate_districts() so results line up with each quarter's agg row).

    Returns {(district_id, commodity_id, quarter): {
        "codex_compliant_fraction": float,
        "eu_compliant_fraction": float,
        "twi_exceedance_fraction": float,
        "fssai_vs_codex_flag": bool,
    }}

    Only uses columns already present on `contaminants` — no extra query per
    group; the limits are loaded once and passed in via `limits_by_contaminant`
    from the caller (see models/aggregate.py).
    """
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name_canonical, legal_limit_ppb_fssai, legal_limit_ppb_codex,
                   eu_limit_ppb, who_jecfa_twi_ug_per_kg
            FROM contaminants
            """
        )
        limits_by_id = {
            r["id"]: ContaminantLimits(
                contaminant_id=r["id"],
                name=r["name_canonical"],
                fssai_limit_ppb=float(r["legal_limit_ppb_fssai"]) if r["legal_limit_ppb_fssai"] else None,
                codex_limit_ppb=float(r["legal_limit_ppb_codex"]) if r["legal_limit_ppb_codex"] else None,
                eu_limit_ppb=float(r["eu_limit_ppb"]) if r["eu_limit_ppb"] else None,
                who_jecfa_twi_ug_per_kg=float(r["who_jecfa_twi_ug_per_kg"]) if r["who_jecfa_twi_ug_per_kg"] else None,
            )
            for r in cur.fetchall()
        }

    comparator = CodexBenchmarkComparator()
    out = {}
    for (district_id, commodity_id, quarter), rows in records_by_group.items():
        n = len(rows)
        if n == 0:
            continue
        codex_pass = eu_pass = twi_exceed = 0
        codex_denom = eu_denom = twi_denom = 0
        any_flag = False
        for r in rows:
            limits = limits_by_id.get(r["contaminant_id"])
            if not limits or not r["raw_value_ppb"]:
                continue
            value = float(r["raw_value_ppb"])
            cmp = comparator.compare(
                value_ppb=value,
                limits=limits,
                commodity_name="",
                commodity_id=commodity_id,
            )
            if cmp.codex_status != "unknown":
                codex_denom += 1
                codex_pass += cmp.codex_status == "pass"
            if cmp.eu_status != "unknown":
                eu_denom += 1
                eu_pass += cmp.eu_status == "pass"
            if cmp.who_twi_fraction is not None:
                twi_denom += 1
                twi_exceed += cmp.who_twi_fraction > 1.0
            if cmp.fssai_compliant_codex_non_compliant:
                any_flag = True

        out[(district_id, commodity_id, quarter)] = {
            "codex_compliant_fraction": round(codex_pass / codex_denom, 4) if codex_denom else None,
            "eu_compliant_fraction": round(eu_pass / eu_denom, 4) if eu_denom else None,
            "twi_exceedance_fraction": round(twi_exceed / twi_denom, 4) if twi_denom else None,
            "fssai_vs_codex_flag": any_flag,
        }
    return out


def write_codex_gap_alerts(conn, records: list) -> int:
    """
    Surfaces the "Mother Dairy problem": districts x commodities x
    contaminants where samples pass FSSAI's own limit but would fail Codex.
    This is the discrepancy the brief calls out as scientifically and
    journalistically significant — India catching less than international
    benchmarks would.
    """
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name_canonical, legal_limit_ppb_fssai, legal_limit_ppb_codex FROM contaminants"
        )
        limits_by_id = {r["id"]: r for r in cur.fetchall()}

    groups = defaultdict(list)
    for r in records:
        if r["district_id"] is not None:
            groups[(r["district_id"], r["commodity_id"], r["contaminant_id"])].append(r)

    n_written = 0
    with conn.cursor() as cur:
        for (district_id, commodity_id, contaminant_id), rows in groups.items():
            limits = limits_by_id.get(contaminant_id)
            if not limits or not limits["legal_limit_ppb_codex"] or not limits["legal_limit_ppb_fssai"]:
                continue
            fssai_limit = float(limits["legal_limit_ppb_fssai"])
            codex_limit = float(limits["legal_limit_ppb_codex"])
            gap_rows = [
                r for r in rows
                if r["raw_value_ppb"] and float(r["raw_value_ppb"]) <= fssai_limit
                and float(r["raw_value_ppb"]) > codex_limit
            ]
            if not gap_rows:
                continue
            mean_ppb = sum(float(r["raw_value_ppb"]) for r in gap_rows) / len(gap_rows)
            severity = (
                "critical" if mean_ppb > codex_limit * 3 else
                "high" if mean_ppb > codex_limit * 1.5 else
                "moderate"
            )
            cur.execute(
                """
                INSERT INTO exposure_alerts
                    (district_id, contaminant_id, commodity_id, alert_type, severity,
                     mean_exposure_ppb, codex_limit_ppb, fssai_limit_ppb, n_samples,
                     first_seen, last_seen, active)
                VALUES (%s,%s,%s,'codex_exceedance_fssai_compliant',%s,%s,%s,%s,%s,
                        CURRENT_DATE,CURRENT_DATE,TRUE)
                ON CONFLICT (district_id, contaminant_id, commodity_id, alert_type)
                DO UPDATE SET
                    severity = EXCLUDED.severity,
                    mean_exposure_ppb = EXCLUDED.mean_exposure_ppb,
                    n_samples = EXCLUDED.n_samples,
                    last_seen = CURRENT_DATE,
                    active = TRUE
                """,
                (district_id, contaminant_id, commodity_id, severity,
                 round(mean_ppb, 4), codex_limit, fssai_limit, len(gap_rows)),
            )
            n_written += 1
    return n_written


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    from pipeline.config import pg_connect
    from models.aggregate import _load_records, _quarter

    conn = pg_connect()
    try:
        records = _load_records(conn)
        groups = defaultdict(list)
        for r in records:
            if r["district_id"] is not None:
                q = _quarter(r["test_date"])
                groups[(r["district_id"], r["commodity_id"], q)].append(r)
        fractions = compute_district_commodity_codex_fractions(conn, groups)

        with conn.cursor() as cur:
            for (district_id, commodity_id, quarter), vals in fractions.items():
                cur.execute(
                    """
                    UPDATE agg_district_commodity_risk
                    SET codex_compliant_fraction = %s,
                        eu_compliant_fraction = %s,
                        twi_exceedance_fraction = %s,
                        fssai_vs_codex_flag = %s
                    WHERE district_id = %s AND commodity_id = %s AND quarter = %s
                    """,
                    (
                        vals["codex_compliant_fraction"], vals["eu_compliant_fraction"],
                        vals["twi_exceedance_fraction"], vals["fssai_vs_codex_flag"],
                        district_id, commodity_id, quarter,
                    ),
                )
        n_alerts = write_codex_gap_alerts(conn, records)
        conn.commit()
        print(f"Updated Codex benchmark fractions for {len(fractions)} district x commodity x quarter groups")
        print(f"Wrote {n_alerts} codex_exceedance_fssai_compliant alerts")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
