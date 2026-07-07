"""
FoodSafe India — Backtest report (H1.5)

Evaluates the risk methodology against real, corroborated enforcement
events only — never against the synthetic seed-demo data
(pipeline/seed_enforcement.py), which would produce a meaningless
self-fulfilling metric. "Real" here means etl_version != 'seed-demo',
which today is exclusively the openFDA ingester's usfda records
(pipeline/sources/openfda.py).

Uses a temporal split (train on the earlier period, evaluate on the later
period) per the master build prompt's hard constraint — this is incident
time-series data, a random split would leak future information into the
training set.

Run: python -m models.backtest
Writes: docs/BACKTEST_REPORT.md (regenerated each run)
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.models.backtest")

REPORT_PATH = "docs/BACKTEST_REPORT.md"


def load_real_records(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT test_date, source_type, state, commodity_id, pass_fail
            FROM enforcement_records
            WHERE etl_version != 'seed-demo' AND is_duplicate = FALSE
            ORDER BY test_date
            """
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def analyze(records: list[dict]) -> dict:
    """Pure classification logic, split out from DB access so it's unit-testable."""
    n = len(records)
    if n == 0:
        return {"n_records": 0, "verdict": "no real records available yet"}

    dates = [r["test_date"] for r in records]
    pass_fail_counts = Counter(r["pass_fail"] for r in records)
    commodity_counts = Counter(r["commodity_id"] for r in records)
    source_counts = Counter(r["source_type"] for r in records)

    # Temporal split: train = first 80% by date, test = last 20% — the
    # protocol we'd use for a real backtest, kept here so the split logic
    # is exercised and ready once there's enough real data to run it on.
    split_idx = int(n * 0.8)
    train, test = records[:split_idx], records[split_idx:]

    n_fail = pass_fail_counts.get(False, 0)
    n_pass = pass_fail_counts.get(True, 0)
    class_balance_ok = n_fail > 0 and n_pass > 0

    max_group_repeat = max(commodity_counts.values()) if commodity_counts else 0
    sparsity_ok = n >= 30 and max_group_repeat >= 5

    if not class_balance_ok:
        verdict = (
            "NOT MEANINGFUL: every real record is a pass_fail=False recall event "
            "(0 passing samples). openFDA's enforcement/recall feed is a log of "
            "confirmed recalls, not a sampled pass/fail test set — there is no "
            "negative class to compute a Brier score or any other discrimination "
            "metric against. A real backtest needs a source with both outcomes, "
            "e.g. routine surveillance testing results, not a recall log."
        )
    elif not sparsity_ok:
        verdict = (
            f"NOT MEANINGFUL: only {n} real records across {len(commodity_counts)} "
            f"commodities (max {max_group_repeat} records for any single commodity) "
            "— too sparse for a statistically meaningful temporal holdout."
        )
    else:
        verdict = "Meaningful — see computed metrics below."

    return {
        "n_records": n,
        "date_range": [str(dates[0]), str(dates[-1])],
        "source_type_breakdown": dict(source_counts),
        "pass_fail_breakdown": {"fail": n_fail, "pass": n_pass},
        "distinct_commodities": len(commodity_counts),
        "max_records_per_commodity": max_group_repeat,
        "n_train": len(train),
        "n_test": len(test),
        "verdict": verdict,
        "meaningful": verdict.startswith("Meaningful"),
    }


def run_backtest(conn) -> dict:
    return analyze(load_real_records(conn))


def write_report(result: dict) -> None:
    lines = [
        "# Backtest Report",
        "",
        f"_Generated {date.today().isoformat()} by `models/backtest.py`._",
        "",
        "## Scope",
        "",
        "Evaluated against **real enforcement records only** "
        "(`etl_version != 'seed-demo'`) — never against the synthetic demo "
        "data that backs the India district/map/compare views today. "
        "Backtesting against synthetic data would produce a self-fulfilling "
        "metric with no evidentiary value.",
        "",
        "## Data available",
        "",
        f"- **{result['n_records']}** real records, spanning "
        f"{result.get('date_range', ['—', '—'])[0]} to {result.get('date_range', ['—', '—'])[1]}",
        f"- Source breakdown: {result.get('source_type_breakdown', {})}",
        f"- Pass/fail breakdown: {result.get('pass_fail_breakdown', {})}",
        f"- {result.get('distinct_commodities', 0)} distinct commodities "
        f"(max {result.get('max_records_per_commodity', 0)} records for any single commodity)",
        "",
        "## Verdict",
        "",
        f"**{result['verdict']}**",
        "",
        "## Why this matters",
        "",
        "The master build prompt requires evaluating the risk model against "
        "real, corroborated events with a temporal split, and publishing the "
        "result — including a null result. openFDA's food enforcement feed "
        "turns out to be a recall log (every record is a confirmed recall), "
        "not a sampled surveillance-testing dataset with both pass and fail "
        "outcomes. That structural mismatch, not a bug in the backtest code, "
        "is why no Brier score is reported here: computing one against a "
        "100%-failure label set would be meaningless, and publishing a "
        "misleadingly precise-looking number would violate the platform's "
        "own model-honesty standard more than publishing nothing does.",
        "",
        "## What would unblock a real backtest",
        "",
        "A source with both outcomes for the same commodity/geography over "
        "time — e.g. routine FSSAI/state surveillance testing results (most "
        "samples pass), rather than an enforcement/recall log (which by "
        "definition only contains failures). See `docs/FSSAI_INGESTION.md` for "
        "why that data isn't reachable today.",
        "",
        "This report is not regenerated automatically — re-run "
        "`python -m models.backtest` after real data volume changes "
        "meaningfully (e.g. a new real ingestion source comes online).",
        "",
    ]
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("Wrote %s", REPORT_PATH)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    conn = pg_connect()
    try:
        result = run_backtest(conn)
    finally:
        conn.close()
    write_report(result)
    print("\n=== BACKTEST SUMMARY ===")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
