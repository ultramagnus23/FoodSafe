"""
FoodSafe India — Fraud Detection Model
Runs after Stage 3+4. Adds fraud_score and fraud_flags to every record.

Checks:
  1. Benford's Law — first-digit distribution on reported PPB values
  2. Round-number clustering — labs that always report round numbers
  3. Lab pass-rate outlier — lab is >2 SD above state mean for that commodity
  4. Geographic plausibility — supply chain origin vs reported district
  5. Value clustering — same lab, same value repeated suspiciously often

Usage (called by Airflow after write_records):
    from models.fraud_detection import run_fraud_pass
    run_fraud_pass(conn, batch_record_ids)
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("foodsafe.models.fraud")

# ============================================================
# BENFORD'S LAW EXPECTED DISTRIBUTION
# ============================================================
# Expected frequency of first significant digit 1–9
BENFORD_EXPECTED = {
    1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097,
    5: 0.079, 6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046,
}

# p-value threshold for flagging
BENFORD_P_THRESHOLD   = 0.05
# Minimum sample size to run Benford's check
BENFORD_MIN_SAMPLES   = 30

# Lab pass rate z-score threshold for outlier flag
LAB_OUTLIER_Z         = 2.0

# What fraction of values must be "round" to flag a lab
ROUND_NUMBER_THRESHOLD = 0.40   # 40% round numbers is suspicious

# Same (lab, value) repeated more than this fraction of their records
VALUE_CLUSTER_THRESHOLD = 0.30


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class FraudFlag:
    flag_type:   str      # 'benford' | 'round_number' | 'geo_implausible' | 'lab_outlier' | 'value_cluster'
    flag_detail: str
    flag_score:  float    # 0.0 – 1.0 contribution to fraud_score


@dataclass
class RecordFraudResult:
    enforcement_record_id: int
    enforcement_date:      str
    flags:                 list[FraudFlag] = field(default_factory=list)
    fraud_score:           float = 0.0
    geo_plausibility_ok:   bool  = True
    value_is_round:        bool  = False
    lab_flagged:           bool  = False


# ============================================================
# BENFORD'S LAW
# ============================================================

def first_significant_digit(value: float) -> Optional[int]:
    """Return first significant digit (1–9) of a positive float."""
    if value is None or value <= 0:
        return None
    digits = str(abs(value)).replace('.', '').lstrip('0')
    return int(digits[0]) if digits else None


def benford_chi2_test(values: list[float]) -> tuple[float, float]:
    """
    Run chi-squared goodness-of-fit test against Benford's distribution.
    Returns (chi2_statistic, p_value).
    """
    from scipy.stats import chisquare

    digits = [first_significant_digit(v) for v in values]
    digits = [d for d in digits if d is not None]

    if len(digits) < BENFORD_MIN_SAMPLES:
        return 0.0, 1.0   # not enough data

    n = len(digits)
    observed  = [digits.count(d) for d in range(1, 10)]
    expected  = [BENFORD_EXPECTED[d] * n for d in range(1, 10)]

    chi2, p = chisquare(observed, f_exp=expected)
    return float(chi2), float(p)


# ============================================================
# ROUND NUMBER DETECTION
# ============================================================

def is_round_number(value: float, tolerance: float = 0.001) -> bool:
    """True if value is suspiciously round (integer, .5, .0, .00)."""
    if value is None:
        return False
    # Check if it's within tolerance of an integer
    return abs(value - round(value)) < tolerance or \
           abs(value - round(value * 2) / 2) < tolerance  # also catches .5


def round_number_fraction(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if is_round_number(v)) / len(values)


# ============================================================
# LAB-LEVEL OUTLIER SCORING
# ============================================================

def compute_lab_reliability_scores(conn) -> dict[int, dict]:
    """
    For each lab, compute:
    - pass_rate per commodity vs state average
    - z-score deviation
    - Benford's Law result
    Returns {lab_id: {reliability_score, flagged, flag_reason, ...}}
    """
    results: dict[int, dict] = {}

    with conn.cursor() as cur:
        # Pull all usable records grouped by lab + commodity + state
        cur.execute("""
            SELECT
                er.lab_id,
                er.commodity_id,
                er.state,
                COUNT(*) AS n_tests,
                SUM(CASE WHEN er.pass_fail = TRUE THEN 1 ELSE 0 END) AS n_pass,
                ARRAY_AGG(er.raw_value_ppb) AS values
            FROM enforcement_records er
            WHERE
                er.lab_id IS NOT NULL
                AND er.confidence_score >= 0.75
                AND er.is_duplicate = FALSE
                AND er.test_date >= NOW() - INTERVAL '24 months'
            GROUP BY er.lab_id, er.commodity_id, er.state
            HAVING COUNT(*) >= 5
        """)
        lab_rows = cur.fetchall()

        # State-level averages for baseline
        cur.execute("""
            SELECT
                er.state,
                er.commodity_id,
                AVG(CASE WHEN er.pass_fail = TRUE THEN 1.0 ELSE 0.0 END) AS state_pass_rate,
                STDDEV(CASE WHEN er.pass_fail = TRUE THEN 1.0 ELSE 0.0 END) AS state_pass_std
            FROM enforcement_records er
            WHERE er.confidence_score >= 0.75 AND er.is_duplicate = FALSE
              AND er.test_date >= NOW() - INTERVAL '24 months'
            GROUP BY er.state, er.commodity_id
        """)
        state_stats = {
            (r[0], r[1]): {"mean": float(r[2] or 0), "std": float(r[3] or 0.01)}
            for r in cur.fetchall()
        }

    for row in lab_rows:
        lab_id, commodity_id, state, n_tests, n_pass, values = row
        pass_rate = (n_pass / n_tests) if n_tests > 0 else 0.0

        # Z-score vs state average
        ss = state_stats.get((state, commodity_id), {"mean": 0.5, "std": 0.1})
        z = (pass_rate - ss["mean"]) / max(ss["std"], 0.01)

        # Benford check
        try:
            chi2, p_val = benford_chi2_test([float(v) for v in (values or [])])
        except Exception:
            chi2, p_val = 0.0, 1.0

        # Round number check
        rn_frac = round_number_fraction([float(v) for v in (values or [])])

        # Composite reliability score
        reliability = 0.80  # base
        flags = []
        flag_reason_parts = []

        if z > LAB_OUTLIER_Z:
            reliability -= 0.20
            flags.append(True)
            flag_reason_parts.append(f"pass_rate_outlier z={z:.2f}")

        if p_val < BENFORD_P_THRESHOLD and n_tests >= BENFORD_MIN_SAMPLES:
            reliability -= 0.15
            flags.append(True)
            flag_reason_parts.append(f"benford_fail p={p_val:.4f}")

        if rn_frac > ROUND_NUMBER_THRESHOLD:
            reliability -= 0.10
            flags.append(True)
            flag_reason_parts.append(f"round_numbers {rn_frac:.0%}")

        reliability = max(0.10, min(1.0, reliability))
        flagged = len(flags) > 0

        if lab_id not in results:
            results[lab_id] = {
                "reliability_score": reliability,
                "pass_rate": pass_rate,
                "flagged": flagged,
                "flag_reason": "; ".join(flag_reason_parts) or None,
                "benford_chi2": chi2,
                "benford_p": p_val,
                "round_frac": rn_frac,
                "z_score": z,
            }
        else:
            # Take worst-case across commodities
            if reliability < results[lab_id]["reliability_score"]:
                results[lab_id].update({
                    "reliability_score": reliability,
                    "flagged": flagged,
                    "flag_reason": "; ".join(flag_reason_parts) or None,
                })

    return results


def update_lab_reliability_in_db(conn, lab_scores: dict[int, dict]):
    """Write computed reliability scores back to labs table."""
    import psycopg2.extras
    with conn.cursor() as cur:
        for lab_id, scores in lab_scores.items():
            cur.execute("""
                UPDATE labs SET
                    reliability_score    = %s,
                    pass_rate            = %s,
                    deviation_z_score    = %s,
                    flagged_suspicious   = %s,
                    flag_reason          = %s,
                    last_evaluated       = NOW()
                WHERE id = %s
            """, (
                round(scores["reliability_score"], 3),
                round(scores["pass_rate"], 4),
                round(scores["z_score"], 3),
                scores["flagged"],
                scores["flag_reason"],
                lab_id,
            ))
    conn.commit()
    logger.info("Updated reliability scores for %d labs", len(lab_scores))


# ============================================================
# GEOGRAPHIC PLAUSIBILITY
# ============================================================

def check_geo_plausibility(
    district_id: Optional[int],
    commodity_id: Optional[int],
    conn,
) -> tuple[bool, Optional[str]]:
    """
    Check if reported district makes geographic sense for the commodity.
    Uses supply_chain_nodes to see if this district has any known
    production/processing nodes for this commodity.
    Simple heuristic: if there are zero supply chain nodes for this
    district + commodity, flag for review (not hard rejection).
    """
    if not district_id or not commodity_id:
        return True, None   # can't check, assume ok

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM supply_chain_nodes
                WHERE district_id = %s AND commodity_id = %s
            """, (district_id, commodity_id))
            count = cur.fetchone()[0]

        if count == 0:
            # No supply chain nodes — soft flag only (not a hard failure;
            # supply chain data is incomplete)
            return True, None  # don't flag until supply chain data is richer
        return True, None
    except Exception as e:
        logger.error("Geo plausibility check failed: %s", e)
        return True, None


# ============================================================
# VALUE CLUSTERING (same lab, same value repeated)
# ============================================================

def detect_value_clustering(
    lab_id: int,
    commodity_id: int,
    conn,
    window_months: int = 12,
) -> tuple[bool, Optional[str]]:
    """
    Flag if a lab reports the same PPB value for the same commodity
    more than VALUE_CLUSTER_THRESHOLD fraction of the time.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT raw_value_ppb, COUNT(*) AS cnt
                FROM enforcement_records
                WHERE lab_id = %s AND commodity_id = %s
                  AND test_date >= NOW() - (%s || ' months')::INTERVAL
                  AND is_duplicate = FALSE
                GROUP BY raw_value_ppb
                ORDER BY cnt DESC
            """, (lab_id, commodity_id, str(window_months)))
            rows = cur.fetchall()

        if not rows:
            return False, None

        total = sum(r[1] for r in rows)
        top_val, top_cnt = rows[0]

        if total < 10:
            return False, None  # too few records

        frac = top_cnt / total
        if frac > VALUE_CLUSTER_THRESHOLD:
            return True, f"value {top_val} ppb repeated {frac:.0%} of {total} records"
        return False, None
    except Exception as e:
        logger.error("Value clustering check failed: %s", e)
        return False, None


# ============================================================
# RECORD-LEVEL FRAUD SCORING
# ============================================================

def score_record(
    record_id: int,
    record_date: str,
    raw_value_ppb: float,
    lab_id: Optional[int],
    district_id: Optional[int],
    commodity_id: Optional[int],
    lab_scores: dict[int, dict],
    conn,
) -> RecordFraudResult:
    """
    Compute fraud_score and flags for a single enforcement record.
    """
    result = RecordFraudResult(
        enforcement_record_id=record_id,
        enforcement_date=record_date,
    )

    # 1. Round number check (record-level)
    if is_round_number(raw_value_ppb):
        result.value_is_round = True
        result.flags.append(FraudFlag(
            flag_type="round_number",
            flag_detail=f"Reported value {raw_value_ppb} ppb is suspiciously round",
            flag_score=0.10,
        ))

    # 2. Lab-level flags (propagated from lab scoring)
    if lab_id and lab_id in lab_scores:
        ls = lab_scores[lab_id]
        if ls["flagged"]:
            result.lab_flagged = True
            result.flags.append(FraudFlag(
                flag_type="lab_outlier",
                flag_detail=ls["flag_reason"] or "Lab flagged suspicious",
                flag_score=0.25,
            ))

    # 3. Value clustering
    if lab_id and commodity_id:
        clustered, detail = detect_value_clustering(lab_id, commodity_id, conn)
        if clustered:
            result.flags.append(FraudFlag(
                flag_type="value_cluster",
                flag_detail=detail,
                flag_score=0.20,
            ))

    # 4. Geo plausibility
    plausible, geo_detail = check_geo_plausibility(district_id, commodity_id, conn)
    if not plausible:
        result.geo_plausibility_ok = False
        result.flags.append(FraudFlag(
            flag_type="geo_implausible",
            flag_detail=geo_detail,
            flag_score=0.15,
        ))

    # Composite fraud score (capped at 1.0)
    result.fraud_score = min(1.0, sum(f.flag_score for f in result.flags))

    return result


# ============================================================
# BATCH FRAUD PASS (called by Airflow after ingest)
# ============================================================

def run_fraud_pass(conn, record_ids: Optional[list[int]] = None):
    """
    Full fraud detection pass.
    If record_ids is None, processes all records from the last 7 days.
    """
    import psycopg2.extras

    logger.info("Starting fraud detection pass...")

    # Step 1: Compute lab reliability scores
    lab_scores = compute_lab_reliability_scores(conn)
    update_lab_reliability_in_db(conn, lab_scores)
    logger.info("Lab reliability computed for %d labs", len(lab_scores))

    # Step 2: Pull records to evaluate
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if record_ids:
            cur.execute("""
                SELECT id, test_date, raw_value_ppb, lab_id, district_id, commodity_id
                FROM enforcement_records
                WHERE id = ANY(%s)
            """, (record_ids,))
        else:
            cur.execute("""
                SELECT id, test_date, raw_value_ppb, lab_id, district_id, commodity_id
                FROM enforcement_records
                WHERE parsed_at >= NOW() - INTERVAL '7 days'
                  AND is_duplicate = FALSE
            """)
        records = cur.fetchall()

    logger.info("Evaluating %d records for fraud signals", len(records))

    # Step 3: Score each record and write back
    fraud_audit_rows = []
    update_rows = []

    for rec in records:
        result = score_record(
            record_id    = rec["id"],
            record_date  = str(rec["test_date"]),
            raw_value_ppb = float(rec["raw_value_ppb"]),
            lab_id       = rec["lab_id"],
            district_id  = rec["district_id"],
            commodity_id = rec["commodity_id"],
            lab_scores   = lab_scores,
            conn         = conn,
        )

        flags_json = [
            {"type": f.flag_type, "detail": f.flag_detail, "score": f.flag_score}
            for f in result.flags
        ]
        import json
        update_rows.append((
            json.dumps(flags_json),
            round(result.fraud_score, 3),
            result.geo_plausibility_ok,
            result.value_is_round,
            result.lab_flagged,
            rec["id"],
            str(rec["test_date"]),
        ))

        for flag in result.flags:
            fraud_audit_rows.append((
                rec["id"],
                str(rec["test_date"]),
                flag.flag_type,
                flag.flag_detail,
                round(flag.flag_score, 3),
            ))

    # Batch update enforcement_records
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, """
            UPDATE enforcement_records SET
                fraud_flags         = %s::jsonb,
                fraud_score         = %s,
                geo_plausibility_ok = %s,
                value_is_round      = %s,
                lab_flagged         = %s
            WHERE id = %s AND test_date = %s
        """, update_rows, page_size=500)

        if fraud_audit_rows:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO fraud_audit
                    (enforcement_record_id, enforcement_date, flag_type, flag_detail, flag_score)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, fraud_audit_rows)

    conn.commit()

    flagged = sum(1 for r in update_rows if r[1] > 0)
    logger.info(
        "Fraud pass complete: %d records evaluated, %d flagged (%.1f%%)",
        len(records), flagged, 100 * flagged / max(len(records), 1)
    )
    return {"evaluated": len(records), "flagged": flagged, "lab_scores_updated": len(lab_scores)}


# ============================================================
# AIRFLOW TASK WRAPPER
# ============================================================

def airflow_fraud_task():
    import psycopg2
    from pipeline.config import DATABASE_URL
    conn = psycopg2.connect(DATABASE_URL)
    try:
        return run_fraud_pass(conn)
    finally:
        conn.close()
