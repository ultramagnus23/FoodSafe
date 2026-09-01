"""
FoodSafe India — State/UT Commissioner of Food Safety Directory (headless browser)

Real, FSSAI-published contact directory at
https://fssai.gov.in/business/commissioners-of-food-safety — a State/UT
Commissioner of Food Safety, address, contact number(s), email(s), and
designated Nodal Officer(s) for every state and UT.

The raw HTTP response for this URL is an empty React app shell (`<div
id="root">`, ~3KB) — the table is rendered client-side, so a plain
requests/urllib fetch returns nothing useful. This mirrors fssai_recall.py's
approach: drive a real headless browser and read the rendered DOM.

Honest scope: this is contact/escalation metadata, not enforcement or
contamination data. It does NOT feed enforcement_records or risk
aggregation — it answers "who do we contact in this state," a real gap this
repo had no answer to before. See schema_migration_011.sql.

Requires:  pip install playwright && python -m playwright install chromium
Run:       python -m pipeline.sources.fssai_commissioners
"""

from __future__ import annotations

import argparse
import logging

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.fssai_commissioners")

URL = "https://fssai.gov.in/business/commissioners-of-food-safety"


def fetch_commissioners(timeout_ms: int = 45000) -> list[dict]:
    """Render the commissioners page and return one dict per state/UT row."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && "
            "python -m playwright install chromium"
        )

    rows_out: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="networkidle", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            logger.warning("page load warning: %s", e)
        page.wait_for_selector("table tr", timeout=timeout_ms)

        # Header row's <th>State / UT</th> etc. confirms this is the right
        # table; every subsequent <tr> is one state/UT's data row. Cells
        # contain nested <div>s for multi-line fields (address, multiple
        # emails/phones) — inner_text() flattens those to newline-joined text.
        trs = page.query_selector_all("table tr")
        for tr in trs[1:]:  # skip header
            cells = tr.query_selector_all("td")
            if len(cells) < 6:
                continue
            texts = [c.inner_text().strip() for c in cells]
            rows_out.append({
                "state": texts[0],
                "commissioner_name": texts[1],
                "address": texts[2],
                "contact": texts[3],
                "email": texts[4],
                "nodal_officer": texts[5],
            })
        browser.close()

    logger.info("scraped %d state/UT commissioner rows", len(rows_out))
    return rows_out


def ingest(conn, rows: list[dict]) -> dict:
    summary = {"scraped": len(rows), "inserted": 0, "updated": 0, "skipped": 0}
    for r in rows:
        state = (r.get("state") or "").strip()
        if not state:
            summary["skipped"] += 1
            continue
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO state_commissioners
                     (state, commissioner_name, address, contact, email, nodal_officer, source_url, fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT (state) DO UPDATE SET
                     commissioner_name = EXCLUDED.commissioner_name,
                     address           = EXCLUDED.address,
                     contact           = EXCLUDED.contact,
                     email             = EXCLUDED.email,
                     nodal_officer     = EXCLUDED.nodal_officer,
                     source_url        = EXCLUDED.source_url,
                     fetched_at        = NOW()
                   RETURNING (xmax = 0) AS inserted""",
                (state, r.get("commissioner_name"), r.get("address"), r.get("contact"),
                 r.get("email"), r.get("nodal_officer"), URL),
            )
            was_insert = cur.fetchone()[0]
            summary["inserted" if was_insert else "updated"] += 1
    conn.commit()
    return summary


def run() -> dict:
    rows = fetch_commissioners()
    if not rows:
        return {"scraped": 0, "note": "no rows rendered (page structure may have changed)"}
    conn = pg_connect()
    try:
        return ingest(conn, rows)
    finally:
        conn.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Scrape FSSAI state commissioner directory").parse_args()
    summary = run()
    print("\n=== FSSAI COMMISSIONER DIRECTORY SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
