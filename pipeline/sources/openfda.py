"""
FoodSafe India — openFDA Food Enforcement Ingester

Real, no-OCR data source: the openFDA food enforcement API
(https://api.fda.gov/food/enforcement.json) — public, no API key, structured
JSON of US FDA food recalls/enforcement actions.

Why this source: the FSSAI PDF pipeline needs OCR + NER + live gov listing
pages whose URLs have changed. openFDA is reachable and structured, so it is
the path that actually pulls *real* records into the database today.

Scope / honesty note: these are US-geographic recalls. We map them to
source_type='usfda' with the US distribution state in `state` and
district_id = NULL. They therefore appear in the national /risk/alerts feed,
not the India district heatmap (which needs Indian-source data).

Run:
  python -m pipeline.sources.openfda --limit 50
Idempotent: dedups on the openFDA recall_number (stored in dedup_hash).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Optional

import psycopg2

from pipeline.config import UNIT_TO_PPB, pg_connect

logger = logging.getLogger("foodsafe.openfda")

OPENFDA_URL = "https://api.fda.gov/food/enforcement.json"

# Contaminant search terms → we query openFDA per term so we only pull recalls
# that can map onto a contaminant we model (contaminant_id is NOT NULL).
SEARCH_TERMS = ["lead", "aflatoxin", "melamine", "arsenic", "cadmium", "ochratoxin"]

# value + unit pattern in free-text reason, e.g. "2.2 ppm lead", "150 ug/kg"
_VALUE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ppm|ppb|mg/kg|µg/kg|ug/kg|mcg/kg|ng/g|mg/l)",
    re.IGNORECASE,
)


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def _fetch(search: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode({"search": search, "limit": limit})
    url = f"{OPENFDA_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("results", [])
    except urllib.error.HTTPError as e:
        if e.code == 404:  # openFDA returns 404 when a search has zero results
            return []
        logger.warning("openFDA HTTP %s for search=%s", e.code, search)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("openFDA fetch failed for search=%s: %s", search, e)
        return []


# ------------------------------------------------------------
# Mapping helpers
# ------------------------------------------------------------

def _load_contaminants(conn) -> list[tuple[int, str, list[str]]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical, aliases, legal_limit_ppb_fssai FROM contaminants")
        return [(r[0], r[1], (r[2] or []), r[3]) for r in cur.fetchall()]


def _match_contaminant(reason: str, contaminants) -> Optional[tuple[int, Optional[float]]]:
    """Return (contaminant_id, legal_limit_ppb) if the reason text names a
    contaminant we model, else None."""
    low = reason.lower()
    for cid, canonical, aliases, limit in contaminants:
        needles = [canonical.replace("_", " ")] + [a.lower() for a in aliases]
        # also match the leading token, e.g. 'aflatoxin' from 'aflatoxin_b1'
        needles.append(canonical.split("_")[0])
        if any(n and n in low for n in needles):
            return cid, (float(limit) if limit is not None else None)
    return None


def _extract_value_ppb(reason: str) -> float:
    m = _VALUE_RE.search(reason or "")
    if not m:
        return 0.0  # qualitative recall — no stated level
    val = float(m.group(1))
    unit = m.group(2).lower()
    return val * UNIT_TO_PPB.get(unit, 1.0)


def _upsert_commodity(conn, product_desc: str) -> Optional[int]:
    """Match product description against existing commodities/aliases; else
    upsert a new 'packaged' commodity from a cleaned product name."""
    desc = (product_desc or "").strip()
    if not desc:
        return None
    low = desc.lower()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical, aliases FROM commodities")
        for cid, canonical, aliases in cur.fetchall():
            needles = [canonical] + [a.lower() for a in (aliases or [])]
            if any(n and n in low for n in needles):
                return cid
        # no match → create a short canonical name from the description
        name = re.sub(r"[^a-z0-9 ]", "", low).strip()[:60] or "packaged food"
        cur.execute(
            """INSERT INTO commodities (name_canonical, category)
               VALUES (%s, 'packaged') ON CONFLICT (name_canonical) DO NOTHING
               RETURNING id""",
            (name,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM commodities WHERE name_canonical = %s", (name,))
        row = cur.fetchone()
        return row[0] if row else None


def _upsert_brand(conn, name: str) -> Optional[int]:
    name = (name or "").strip()
    if not name or name.lower() in ("n/a", "none"):
        return None
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO brands (name_canonical) VALUES (%s)
               ON CONFLICT (name_canonical) DO NOTHING RETURNING id""",
            (name[:200],),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM brands WHERE name_canonical = %s", (name[:200],))
        row = cur.fetchone()
        return row[0] if row else None


def _parse_date(yyyymmdd: Optional[str]) -> Optional[date]:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    try:
        return datetime.strptime(yyyymmdd, "%Y%m%d").date()
    except ValueError:
        return None


# ------------------------------------------------------------
# Main ingest
# ------------------------------------------------------------

def run_openfda_ingest(conn, limit_per_term: int = 30) -> dict:
    """Fetch + map + write openFDA food enforcement records. Idempotent."""
    contaminants = _load_contaminants(conn)
    summary = {"fetched": 0, "matched": 0, "inserted": 0, "skipped_dupe": 0, "skipped_nomap": 0}
    seen_recall_numbers: set[str] = set()

    for term in SEARCH_TERMS:
        results = _fetch(f"reason_for_recall:{term}", limit_per_term)
        summary["fetched"] += len(results)

        for r in results:
            recall_no = r.get("recall_number")
            if not recall_no or recall_no in seen_recall_numbers:
                continue
            seen_recall_numbers.add(recall_no)

            reason = r.get("reason_for_recall") or ""
            match = _match_contaminant(reason, contaminants)
            if not match:
                summary["skipped_nomap"] += 1
                continue
            contaminant_id, legal_limit = match
            summary["matched"] += 1

            test_date = _parse_date(r.get("recall_initiation_date"))
            # keep within the existing yearly partitions (2020-2026)
            if not test_date or not (date(2020, 1, 1) <= test_date < date(2027, 1, 1)):
                summary["skipped_nomap"] += 1
                continue

            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM enforcement_records WHERE dedup_hash = %s LIMIT 1", (recall_no,))
                if cur.fetchone():
                    summary["skipped_dupe"] += 1
                    continue

            commodity_id = _upsert_commodity(conn, r.get("product_description") or "")
            brand_id = _upsert_brand(conn, r.get("recalling_firm") or "")
            if commodity_id is None:
                summary["skipped_nomap"] += 1
                continue

            value_ppb = _extract_value_ppb(reason)
            source_url = (
                "https://www.accessdata.fda.gov/scripts/ires/index.cfm?action="
                "search.recall&recall_number=" + urllib.parse.quote(recall_no)
            )

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO enforcement_records (
                                test_date, source_url, source_type,
                                commodity_id, contaminant_id,
                                raw_value_ppb, legal_limit_ppb, pass_fail,
                                state, brand_id,
                                confidence_score, dedup_hash, is_duplicate,
                                etl_version, parsed_at
                            ) VALUES (%s,%s,'usfda',%s,%s,%s,%s,FALSE,%s,%s,%s,%s,FALSE,'openfda-1.0',NOW())""",
                        (
                            test_date, source_url,
                            commodity_id, contaminant_id,
                            value_ppb, legal_limit, r.get("state"),
                            brand_id, 0.85, recall_no,
                        ),
                    )
                summary["inserted"] += 1
            except psycopg2.Error as e:
                logger.error("insert failed for %s: %s", recall_no, e)
                conn.rollback()

    conn.commit()
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Ingest openFDA food enforcement recalls")
    parser.add_argument("--limit", type=int, default=30, help="records per contaminant search term")
    args = parser.parse_args()

    conn = pg_connect()
    try:
        summary = run_openfda_ingest(conn, limit_per_term=args.limit)
    finally:
        conn.close()

    print("\n=== openFDA INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
