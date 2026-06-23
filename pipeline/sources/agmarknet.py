"""
FoodSafe India — AGMARKNET (data.gov.in) Ingester

Real Indian open-government feed: AGMARKNET daily mandi (market) data via the
data.gov.in API. Public, structured JSON, no OCR.

Scope / honesty note: AGMARKNET is commodity *price/arrival* data, not
contamination testing. It does NOT populate enforcement_records (there is no
open API for Indian district-level contamination data — that lives in FSSAI
PDFs). What it DOES give us is real Indian geographic + commodity coverage:
we upsert the real districts, states and commodities it reports. New districts
without enforcement records simply won't appear on the risk map (which is
aggregation-driven) until real test data exists for them.

Uses the documented data.gov.in sample API key by default; override with the
DATA_GOV_IN_KEY env var for higher rate limits.

Run:  python -m pipeline.sources.agmarknet --limit 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.parse
import urllib.request

from pipeline.config import STATE_ALIASES, pg_connect

logger = logging.getLogger("foodsafe.agmarknet")

# data.gov.in "Current Daily Price of Various Commodities from Various Markets (Mandi)"
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
DEFAULT_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"  # public sample key
API = "https://api.data.gov.in/resource/"


def _fetch(limit: int) -> list[dict]:
    key = os.environ.get("DATA_GOV_IN_KEY", DEFAULT_KEY)
    params = urllib.parse.urlencode({"api-key": key, "format": "json", "limit": limit})
    url = f"{API}{RESOURCE_ID}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode()).get("records", [])


def _canon_state(s: str) -> str:
    return STATE_ALIASES.get((s or "").strip().lower(), (s or "").strip())


def run_agmarknet_ingest(conn, limit: int = 1000) -> dict:
    records = _fetch(limit)
    districts: set[tuple[str, str]] = set()
    commodities: set[str] = set()
    for r in records:
        district = (r.get("district") or "").strip()
        state = _canon_state(r.get("state") or "")
        commodity = (r.get("commodity") or "").strip().lower()
        if district and state:
            districts.add((district, state))
        if commodity:
            commodities.add(commodity)

    d_new = c_new = 0
    with conn.cursor() as cur:
        for name, state in districts:
            cur.execute(
                """INSERT INTO districts (name_canonical, state)
                   VALUES (%s, %s) ON CONFLICT (name_canonical, state) DO NOTHING""",
                (name, state),
            )
            d_new += cur.rowcount
        for name in commodities:
            cur.execute(
                """INSERT INTO commodities (name_canonical, category)
                   VALUES (%s, 'produce') ON CONFLICT (name_canonical) DO NOTHING""",
                (name[:60],),
            )
            c_new += cur.rowcount
    conn.commit()

    summary = {
        "fetched": len(records),
        "distinct_districts": len(districts),
        "new_districts": d_new,
        "distinct_commodities": len(commodities),
        "new_commodities": c_new,
    }
    logger.info("AGMARKNET ingest: %s", summary)
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    p = argparse.ArgumentParser(description="Ingest AGMARKNET districts/commodities from data.gov.in")
    p.add_argument("--limit", type=int, default=1000)
    args = p.parse_args()
    conn = pg_connect()
    try:
        summary = run_agmarknet_ingest(conn, limit=args.limit)
    finally:
        conn.close()
    print("\n=== AGMARKNET INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
