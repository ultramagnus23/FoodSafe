"""
FoodSafe India — ingest wrapper with pipeline_runs logging (H1.3)

Invoked by .github/workflows/ingest.yml instead of `python -m
pipeline.sources.X` directly. Records a pipeline_runs row per source so
/admin can tell "FoSCoS blocked as expected" apart from "openFDA broke" at a
glance, instead of that distinction only living in workflow logs nobody
reads until something's already been silently missing for weeks.

Usage: python -m pipeline.run_and_log <source> [--limit N]
Exit code: 0 for success or expected_failure, 1 for a real failure (so the
GitHub Actions step outcome reflects only genuine regressions).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.run_and_log")

# (module path, ingest function name, kwarg name for --limit, whether the
# function opens its own DB connection or expects one passed in)
SOURCES = {
    "openfda":              ("pipeline.sources.openfda",              "run_openfda_ingest",   "limit_per_term", False),
    "agmarknet":            ("pipeline.sources.agmarknet",            "run_agmarknet_ingest", "limit",          False),
    "fssai_recall":         ("pipeline.sources.fssai_recall",         "run",                  "limit",          True),
    "local_news":           ("pipeline.sources.local_news",           "run",                  "limit",          True),
    "fssai_commissioners":  ("pipeline.sources.fssai_commissioners",  "run",                  None,             True),
    "fssai_labs":           ("pipeline.sources.fssai_labs",           "run",                  None,             True),
    "loksabha_qa":          ("pipeline.sources.loksabha_qa",          "run",                  None,             True),
    "loksabha_sampling":    ("pipeline.sources.loksabha_sampling",    "run",                  None,             True),
    "loksabha_pesticide":   ("pipeline.sources.loksabha_pesticide",   "run",                  None,             True),
    "fssai_annual_report":  ("pipeline.sources.fssai_annual_report",  "run",                  None,             True),
    "research_evidence":    ("pipeline.sources.research_evidence",    "run",                  "limit",          True),
    "europepmc_evidence":   ("pipeline.sources.europepmc_evidence",   "run",                  "limit",          True),
}

# Sources where zero rows ingested is a known, accepted outcome (documented
# gate or flaky public rate limit), not a regression worth alerting on.
# openFDA is deliberately excluded — it's the one confirmed-reliable real
# source, so zero rows there is worth knowing about. local_news is included:
# docs/LOCAL_NEWS_INGESTION.md's real test run found 1 relevant article out
# of 28 listing items in a single pull — a 0-row run is expected, not a
# regression, until this runs on a schedule and accumulates over days.
# loksabha_sampling skips questions already logged at the current parser
# version, so every run after the first legitimately inserts 0 rows; so does
# loksabha_pesticide, which works the same way.
EXPECTED_EMPTY_SOURCES = {"agmarknet", "fssai_recall", "local_news", "loksabha_sampling", "loksabha_pesticide"}


def _rows_ingested(summary: dict) -> int:
    for key in ("inserted", "fetched", "scraped"):
        if key in summary:
            return int(summary[key])
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", choices=sorted(SOURCES))
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    module_path, func_name, limit_kwarg, owns_connection = SOURCES[args.source]
    func = getattr(importlib.import_module(module_path), func_name)

    log_conn = pg_connect()
    with log_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (source, status) VALUES (%s, 'running') RETURNING id",
            (args.source,),
        )
        run_id = cur.fetchone()[0]
    log_conn.commit()

    status = "failed"
    rows = 0
    error_detail = None
    kwargs = {limit_kwarg: args.limit} if limit_kwarg else {}
    try:
        if owns_connection:
            summary = func(**kwargs)
        else:
            conn = pg_connect()
            try:
                summary = func(conn, **kwargs)
            finally:
                conn.close()

        rows = _rows_ingested(summary)
        if rows == 0 and args.source in EXPECTED_EMPTY_SOURCES:
            status = "expected_failure"
            error_detail = str(summary.get("note", "no rows ingested (known-flaky source)"))
        else:
            status = "success"

        print(f"\n=== {args.source} run summary ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    except Exception as e:  # noqa: BLE001 — any exception here is a real regression
        error_detail = f"{type(e).__name__}: {e}"
        status = "failed"
        logger.error("run failed for %s: %s", args.source, error_detail)

    with log_conn.cursor() as cur:
        cur.execute(
            """UPDATE pipeline_runs
               SET status=%s, rows_ingested=%s, error_detail=%s, finished_at=NOW()
               WHERE id=%s""",
            (status, rows, error_detail, run_id),
        )
    log_conn.commit()
    log_conn.close()

    if status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
