"""
FoodSafe India — one-command database bootstrap.

Builds a complete FoodSafe schema on an empty PostgreSQL database (Supabase,
Render Postgres, or plain local) by applying schema.sql followed by every
schema_migration_*.sql in numeric order.

This exists because the 14 migrations had only ever been applied incrementally
to a database that grew with them. When the Supabase project backing this repo
was deleted (2026-09, confirmed NXDOMAIN on the project host — not merely
paused), there was no tested path from "empty database" to "working schema".
Verified 2026-09-11: all 15 files apply cleanly to a fresh database in one pass.

Idempotent: safe to re-run against a partially-built database. Each file runs in
its own transaction, so one failure does not leave the schema half-applied from
that file — though earlier files stay committed, which is what you want when
resuming after a network drop.

Usage:
    export DATABASE_URL="postgresql://...?sslmode=require"
    python -m scripts.bootstrap_db              # apply schema + migrations
    python -m scripts.bootstrap_db --check      # report state, change nothing
    python -m scripts.bootstrap_db --verify-only

On Supabase, use the IPv4 Session-pooler host — the direct db.<ref>.supabase.co
host is IPv6-only and unreachable from most networks (see memory/local-dev notes).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:  # pragma: no cover - dependency guidance
    sys.exit("psycopg2 is required:  pip install psycopg2-binary")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tables that must exist for the API to serve its core surface. Checked after
# apply so a "success" that silently produced nothing is caught here, not by a
# 500 in production.
CORE_TABLES = [
    "users",
    "districts",
    "commodities",
    "contaminants",
    "enforcement_records",
    "agg_district_commodity_risk",
    "agg_brand_safety_profile",
    "dose_response_params",
    "icmr_consumption",
    "localities",
    "labs",
    "state_enforcement_annual",
    "national_enforcement_annual",
    "state_sampling_annual",
    "loksabha_question_log",
]


def migration_files() -> list[Path]:
    """
    schema.sql, then reference geography, then schema_migration_NNN.sql in
    numeric order.

    schema_reference_districts.sql must run BEFORE the migrations: 009 and 010
    attach their locality seeds to districts by name, and on a real-only
    database those districts do not exist until this file creates them. Run it
    afterwards and both locality seeds silently insert zero rows. See that
    file's header for the full explanation.
    """
    base = REPO_ROOT / "schema.sql"
    if not base.exists():
        sys.exit(f"schema.sql not found at {base} — run this from the repo.")

    ordered = [base]

    reference = REPO_ROOT / "schema_reference_districts.sql"
    if reference.exists():
        ordered.append(reference)

    ordered += sorted(
        REPO_ROOT.glob("schema_migration_*.sql"),
        key=lambda p: int(re.search(r"(\d+)", p.name).group(1)),
    )
    return ordered


def connect(url: str):
    try:
        return psycopg2.connect(url, connect_timeout=30)
    except psycopg2.OperationalError as exc:
        msg = str(exc)
        hint = ""
        if "tenant or user not found" in msg.lower() or "ENOTFOUND" in msg:
            hint = (
                "\n\nThis usually means the Supabase project no longer exists "
                "(deleted, not paused) or the connection string's user is wrong. "
                "Check the project ref in the URL against your Supabase dashboard."
            )
        elif "could not translate host name" in msg.lower():
            hint = (
                "\n\nHost did not resolve. On Supabase use the Session-pooler "
                "host (aws-N-<region>.pooler.supabase.com), not db.<ref>.supabase.co, "
                "which is IPv6-only."
            )
        sys.exit(f"Could not connect: {msg}{hint}")


def existing_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        return {r[0] for r in cur.fetchall()}


# Postgres SQLSTATEs meaning "this object is already there". A file that stops
# on one of these has already been applied — on a re-run or a resumed deploy
# that is the expected outcome, not a failure. Anything else is a real error.
ALREADY_APPLIED = {
    "42P07",  # duplicate_table
    "42710",  # duplicate_object (constraint, index, role, type)
    "42P06",  # duplicate_schema
    "42701",  # duplicate_column
}


def apply_file(conn, path: Path) -> tuple[str, str]:
    """
    Apply one .sql file in its own transaction.

    Returns (status, detail) where status is "applied", "skipped" (already
    present) or "failed". Each file is its own transaction, so a failure here
    never leaves that file half-applied.
    """
    sql = path.read_text(encoding="utf-8")
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
        return "applied", ""
    except psycopg2.Error as exc:
        conn.rollback()
        detail = (exc.pgerror or str(exc)).strip().splitlines()[0]
        if getattr(exc, "pgcode", None) in ALREADY_APPLIED:
            return "skipped", detail
        return "failed", detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="report which tables exist and exit without changing anything",
    )
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="alias for --check",
    )
    args = ap.parse_args()
    check_only = args.check or args.verify_only

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")

    # Never print credentials, including into CI logs.
    safe = re.sub(r"://([^:]+):[^@]+@", r"://\1:****@", url)
    print(f"Target: {safe}\n")

    conn = connect(url)
    before = existing_tables(conn)
    print(f"Tables present before: {len(before)}")

    if check_only:
        missing = [t for t in CORE_TABLES if t not in before]
        if missing:
            print(f"\nMissing {len(missing)} core table(s): {', '.join(missing)}")
            print("Run without --check to apply the schema.")
            return 1
        print("\nAll core tables present. Schema looks complete.")
        return 0

    files = migration_files()
    print(f"Applying {len(files)} file(s)...\n")

    failures: list[tuple[str, str]] = []
    n_skipped = 0
    for path in files:
        status, detail = apply_file(conn, path)
        if status == "applied":
            print(f"  ok       {path.name}")
        elif status == "skipped":
            n_skipped += 1
            print(f"  present  {path.name} (already applied)")
        else:
            print(f"  FAIL     {path.name}: {detail}")
            failures.append((path.name, detail))

    after = existing_tables(conn)
    print(f"\nTables present after: {len(after)}  (+{len(after - before)})")
    if n_skipped:
        print(f"{n_skipped} file(s) were already applied.")

    missing = [t for t in CORE_TABLES if t not in after]
    if missing:
        print(f"\nMissing core table(s): {', '.join(missing)}")

    if failures or missing:
        print("\nBootstrap INCOMPLETE.")
        for name, detail in failures:
            print(f"  {name}: {detail}")
        return 1

    print("\nBootstrap complete. Next:")
    print("  python -m pipeline.run_and_log openfda --limit 200")
    print("  python -m pipeline.run_and_log agmarknet --limit 1000")
    print("  python -m pipeline.run_and_log loksabha_qa")
    print("  python -m pipeline.run_and_log fssai_annual_report")
    print("  python -m pipeline.run_and_log fssai_labs")
    print("  python -m models.aggregate")
    print("  python -m models.disease_burden compute_all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
