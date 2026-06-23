"""
FoodSafe India — Aggregation Job (the "nightly Airflow aggregation")

Computes the two aggregation tables that the API serves, directly from
enforcement_records:
  - agg_district_commodity_risk  (district × commodity × quarter)
  - agg_brand_safety_profile     (brand × commodity)

This is what turns raw enforcement records into the risk scores shown on the
map / risk report / brand pages. Before this existed the agg tables were
hand-seeded; now they are *computed*, so as new records flow in (openFDA
ingester, AGMARKNET, future FSSAI) the scores update on the next run.

Methodology (interpretable, documented):
  - fail_rate   = failing tests / total tests (confidence >= 0.75, non-duplicate)
  - risk_score  = 100 * (0.85 * F + 0.15 * S), clamped 0-100, where
        F = 1 - (1 - fail_rate)^8    saturating curve (≈15% fails -> ≈73)
        S = mean( min(value/legal_limit, 5) / 5 )  severity of exceedances
  - 95% CI      = Wilson score interval on the fail proportion, mapped through
                  the same curve (honest interval that widens with small n)

Run:  python -m models.aggregate
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections import defaultdict
from datetime import date

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.aggregate")

CONF_MIN = 0.75
RISK_K = 8  # saturating-curve exponent


# ------------------------------------------------------------
# math helpers
# ------------------------------------------------------------

def _quarter(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _fail_curve(p: float) -> float:
    return 1.0 - (1.0 - p) ** RISK_K


def _wilson(fails: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = fails / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, center - margin), min(1.0, center + margin)


def _risk(fail_rate: float, severity: float) -> float:
    raw = 0.85 * _fail_curve(fail_rate) + 0.15 * severity
    return round(100 * min(1.0, max(0.0, raw)), 2)


def _severity(rows) -> float:
    """Mean normalised exceedance over records that have a value and a limit."""
    ratios = []
    for r in rows:
        val, limit = r["raw_value_ppb"], r["legal_limit_ppb"]
        if val and limit and float(limit) > 0 and float(val) > 0:
            ratios.append(min(float(val) / float(limit), 5.0) / 5.0)
    return sum(ratios) / len(ratios) if ratios else 0.0


# ------------------------------------------------------------
# data load
# ------------------------------------------------------------

def _load_records(conn):
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT er.test_date, er.district_id, er.commodity_id, er.contaminant_id,
                   er.brand_id, er.raw_value_ppb, er.legal_limit_ppb, er.pass_fail,
                   cnt.name_canonical AS contaminant
            FROM enforcement_records er
            JOIN contaminants cnt ON cnt.id = er.contaminant_id
            WHERE er.confidence_score >= %s AND er.is_duplicate = FALSE
            """,
            (CONF_MIN,),
        )
        return cur.fetchall()


# ------------------------------------------------------------
# aggregation
# ------------------------------------------------------------

def aggregate_districts(conn, records) -> int:
    groups = defaultdict(list)
    for r in records:
        if r["district_id"] is None:
            continue  # district-level agg needs a district (US recalls have none)
        q = _quarter(r["test_date"])
        groups[(r["district_id"], r["commodity_id"], q)].append(r)

    rows_out = []
    for (district_id, commodity_id, quarter), rows in groups.items():
        n = len(rows)
        fails = sum(1 for r in rows if r["pass_fail"] is False)
        fail_rate = fails / n if n else 0.0
        sev = _severity(rows)
        risk = _risk(fail_rate, sev)
        lo, hi = _wilson(fails, n)
        ci_lower = round(100 * (0.85 * _fail_curve(lo) + 0.15 * sev), 2)
        ci_upper = round(100 * (0.85 * _fail_curve(hi) + 0.15 * sev), 2)

        # top contaminants by per-contaminant fail rate
        by_cont = defaultdict(lambda: [0, 0])  # name -> [fails, total]
        for r in rows:
            by_cont[r["contaminant"]][1] += 1
            if r["pass_fail"] is False:
                by_cont[r["contaminant"]][0] += 1
        top = sorted(
            ({"name": name, "fail_rate": round(f / t, 4)} for name, (f, t) in by_cont.items()),
            key=lambda x: x["fail_rate"], reverse=True,
        )[:3]

        rows_out.append((district_id, commodity_id, quarter, round(fail_rate, 4), n,
                         risk, ci_lower, ci_upper, json.dumps(top)))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE agg_district_commodity_risk")
        cur.executemany(
            """INSERT INTO agg_district_commodity_risk
                 (district_id, commodity_id, quarter, fail_rate, n_tests,
                  risk_score, ci_lower, ci_upper, top_contaminants,
                  model_version, last_updated)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'agg-1.0',NOW())""",
            rows_out,
        )
    conn.commit()
    return len(rows_out)


def aggregate_brands(conn, records) -> int:
    groups = defaultdict(list)
    for r in records:
        if r["brand_id"] is None:
            continue
        groups[(r["brand_id"], r["commodity_id"])].append(r)

    rows_out = []
    for (brand_id, commodity_id), rows in groups.items():
        n = len(rows)
        fails = sum(1 for r in rows if r["pass_fail"] is False)
        fail_rate = fails / n if n else 0.0
        sev = _severity(rows)
        risk = _risk(fail_rate, sev)
        lo, hi = _wilson(fails, n)
        ci_lower = round(100 * (0.85 * _fail_curve(lo) + 0.15 * sev), 2)
        ci_upper = round(100 * (0.85 * _fail_curve(hi) + 0.15 * sev), 2)
        vals = [float(r["raw_value_ppb"]) for r in rows if r["raw_value_ppb"]]
        avg_ppb = round(sum(vals) / len(vals), 4) if vals else None
        inference = "direct_test" if n > 0 else "insufficient_data"
        rows_out.append((brand_id, commodity_id, n, fails, avg_ppb, risk,
                         ci_lower, ci_upper, inference))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE agg_brand_safety_profile")
        cur.executemany(
            """INSERT INTO agg_brand_safety_profile
                 (brand_id, commodity_id, n_tests, n_failures, avg_ppb, risk_score,
                  ci_lower, ci_upper, inference_type, model_version, last_updated)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'agg-1.0',NOW())""",
            rows_out,
        )
    conn.commit()
    return len(rows_out)


def run_aggregation(conn) -> dict:
    records = _load_records(conn)
    d = aggregate_districts(conn, records)
    b = aggregate_brands(conn, records)
    summary = {"records": len(records), "district_rows": d, "brand_rows": b}
    logger.info("Aggregation complete: %s", summary)
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Recompute aggregation tables").parse_args()
    conn = pg_connect()
    try:
        summary = run_aggregation(conn)
    finally:
        conn.close()
    print("\n=== AGGREGATION SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
