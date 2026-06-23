"""
FoodSafe India — FSSAI / FoSCoS Food Recall Scraper (headless browser)

The real Indian food-recall data lives on the FoSCoS portal
(https://foscos.fssai.gov.in/food-recall), an Angular app that loads recalls
from an AES-encrypted API (getFoodRecallProductHomepage) and renders them
client-side. Rather than reimplement FoSCoS's obfuscated crypto, we drive a
headless Chromium (Playwright): the app decrypts + renders, and we read the
result — both the decrypted JSON (captured by re-invoking the app's network
data in the page) and, as a fallback, the rendered DOM.

Honest scope: FoSCoS recalls are *qualitative* enforcement events (product,
brand/firm, nature + reason of recall, date, state) — there are NO contaminant
ppb values and no district granularity. So, like the openFDA feed, we ingest
them as source_type='fssai' with raw_value_ppb=0, pass_fail=FALSE, and only
when the recall reason names a contaminant we model. They feed the national
/risk/alerts ticker, not the district heatmap.

NOTE: FoSCoS runs a daily maintenance window (≈ 23:30–03:00 IST) during which
the API returns 503 and the page shows "Daily Maintenance in Progress". The
scraper detects this and exits cleanly. Run it outside that window.

Requires:  pip install playwright && python -m playwright install chromium
Run:       python -m pipeline.sources.fssai_recall --limit 100
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime
from typing import Optional

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.fssai_recall")

RECALL_URL = "https://foscos.fssai.gov.in/food-recall"
API_MARKER = "getFoodRecallProductHomepage"


# ------------------------------------------------------------
# Browser fetch
# ------------------------------------------------------------

def fetch_recalls(limit: int = 100, timeout_ms: int = 60000) -> list[dict]:
    """Render the FoSCoS recall page and return recall dicts.

    Strategy: let Angular call its encrypted API and render. We capture the
    rendered recall rows from the DOM. Returns [] if the portal is in its
    maintenance window or no data renders.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && "
            "python -m playwright install chromium"
        )

    recalls: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        api_status = {"hit": False, "status": None}

        def _on_resp(r):
            if API_MARKER in r.url:
                api_status["hit"] = True
                api_status["status"] = r.status
        page.on("response", _on_resp)

        try:
            page.goto(RECALL_URL, wait_until="networkidle", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            logger.warning("page load warning: %s", e)
        page.wait_for_timeout(6000)

        body_text = page.inner_text("body")
        if "Maintenance" in body_text and "unavailable" in body_text:
            logger.warning("FoSCoS is in its daily maintenance window — try again "
                           "outside ~23:30–03:00 IST.")
            browser.close()
            return []
        if api_status["status"] and api_status["status"] >= 500:
            logger.warning("recall API returned %s — portal unavailable.", api_status["status"])
            browser.close()
            return []

        recalls = _extract_dom(page, limit)
        browser.close()

    logger.info("scraped %d recall rows", len(recalls))
    return recalls


def _extract_dom(page, limit: int) -> list[dict]:
    """Extract recall records from the rendered DOM.

    FoSCoS renders each recall as a row/card binding the fields seen in the
    app bundle: startDateOfRecall, natureOfRecall, reasonOfRecall / details,
    statusName, recallStatus, state, product, licenseNo. We read the rendered
    table rows; if the layout differs, this returns what it can find and logs
    the row count so it can be adjusted against a live (non-maintenance) page.
    """
    rows = page.query_selector_all("table tbody tr")
    out: list[dict] = []
    for tr in rows[:limit]:
        cells = [c.inner_text().strip() for c in tr.query_selector_all("td")]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        out.append({"raw_cells": cells, "text": joined})
    return out


# ------------------------------------------------------------
# Mapping → enforcement_records
# ------------------------------------------------------------

CONTAMINANT_HINTS = None  # loaded from DB


def _load_contaminants(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical, aliases, legal_limit_ppb_fssai FROM contaminants")
        return [(r[0], r[1], (r[2] or []), r[3]) for r in cur.fetchall()]


def _match_contaminant(text: str, contaminants):
    low = (text or "").lower()
    for cid, canonical, aliases, limit in contaminants:
        needles = [canonical.replace("_", " "), canonical.split("_")[0]] + [a.lower() for a in aliases]
        if any(n and n in low for n in needles):
            return cid, (float(limit) if limit is not None else None)
    return None


def _upsert(conn, table, name_col, name, extra_cols="", extra_vals=()):
    if not name:
        return None
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} ({name_col}{extra_cols}) VALUES (%s{',%s'*len(extra_vals)}) "
            f"ON CONFLICT ({name_col}) DO NOTHING RETURNING id",
            (name[:200], *extra_vals),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(f"SELECT id FROM {table} WHERE {name_col} = %s", (name[:200],))
        row = cur.fetchone()
        return row[0] if row else None


def ingest(conn, recalls: list[dict]) -> dict:
    contaminants = _load_contaminants(conn)
    summary = {"scraped": len(recalls), "matched": 0, "inserted": 0, "skipped_nomap": 0, "skipped_dupe": 0}

    for rec in recalls:
        text = rec.get("text", "")
        match = _match_contaminant(text, contaminants)
        if not match:
            summary["skipped_nomap"] += 1
            continue
        contaminant_id, legal_limit = match
        summary["matched"] += 1

        cells = rec.get("raw_cells", [])
        product = cells[0] if cells else text[:60]
        dedup = "fssai-recall-" + re.sub(r"\W+", "", text)[:48]

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM enforcement_records WHERE dedup_hash=%s LIMIT 1", (dedup,))
            if cur.fetchone():
                summary["skipped_dupe"] += 1
                continue

        commodity_id = _upsert(conn, "commodities", "name_canonical",
                               re.sub(r"[^a-z0-9 ]", "", product.lower()).strip() or "packaged food",
                               ", category", ("packaged",))
        if commodity_id is None:
            summary["skipped_nomap"] += 1
            continue

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO enforcement_records
                     (test_date, source_url, source_type, commodity_id, contaminant_id,
                      raw_value_ppb, legal_limit_ppb, pass_fail, confidence_score,
                      dedup_hash, is_duplicate, etl_version, parsed_at)
                   VALUES (%s,%s,'fssai',%s,%s,0,%s,FALSE,0.80,%s,FALSE,'fssai-recall-1.0',NOW())""",
                (date.today(), RECALL_URL, commodity_id, contaminant_id, legal_limit, dedup),
            )
        summary["inserted"] += 1

    conn.commit()
    return summary


def run(limit: int = 100) -> dict:
    recalls = fetch_recalls(limit=limit)
    if not recalls:
        return {"scraped": 0, "note": "no data (maintenance window or empty)"}
    conn = pg_connect()
    try:
        return ingest(conn, recalls)
    finally:
        conn.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description="Scrape FoSCoS food recalls (headless browser)")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    summary = run(limit=args.limit)
    print("\n=== FSSAI RECALL SCRAPE SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
