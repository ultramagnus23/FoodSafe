"""
FoodSafe India — FSSAI Notified Food Testing Laboratories (PDF table extraction)

Real, FSSAI-published lab directories at
https://fssai.gov.in/food-testing/food-laboratories — three separate PDF
lists (Primary/NABL-accredited, Referral, National Reference Labs). The
landing page itself is a client-rendered React shell (confirmed: raw HTTP
response is an empty <div id="root">), so a headless browser is used only
to discover the current PDF URLs (they carry an "as on <date>" version and
are re-issued periodically under slightly different filenames — no stable
URL formula). The PDFs themselves are ordinary digitally-typeset,
non-JS-rendered files, fetched directly and parsed with pdfplumber.

Each list has a different table shape:
  - Primary (NABL-accredited): state appears as its own header row
    ('Delhi', rest of row blank) interleaved with numbered data rows.
    Region headers ('A. NORTHERN REGION') and an "Annexure II" section
    (expired/suspended labs — explicitly out of scope, we stop before it)
    also appear and must be filtered out, not treated as states.
  - Referral: state is a fill-down column — populated only on the first
    row of each state's block, blank (None) on subsequent rows for the
    same state.
  - NRL/ANRL: no state column at all; state is extracted from the free-text
    address (e.g., "..., Karnataka -570020" -> "Karnataka").

Maps onto the existing `labs` table (schema.sql) via tier: 1=ICAR/NABL,
2=state, 3=private (see that table's own CHECK comment). NRL/ANRL and the
NABL-accredited Primary list are both tier 1; Referral labs (state-notified
under FSS Act section 43) are tier 2. None of this is private/tier 3 —
these are all government-recognized labs, not commercial ones the pipeline
has no visibility into.

The 5 pre-existing `labs` rows (seed_enforcement.py demo data, e.g.
"QuickTest Pvt Labs") are left alone — enforcement_records already
reference them via lab_id FK — and are distinguishable from real rows by
source_url IS NULL (see schema_migration_012.sql).

Requires:  pip install playwright pdfplumber && python -m playwright install chromium
Run:       python -m pipeline.sources.fssai_labs
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import urllib.request
from datetime import datetime, timezone

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.fssai_labs")

LANDING_URL = "https://fssai.gov.in/food-testing/food-laboratories"

# Fallback URLs (as discovered 2026-09-01) if the landing-page scrape fails
# to find fresh links — better to ingest a slightly stale list than nothing.
FALLBACK_URLS = {
    "primary": "https://fssai.gov.in/docs/food-testing/food-lab/Validity%20order%20as%20on%2005_06_26.pdf",
    "referral": "https://fssai.gov.in/docs/food-testing/food-lab/Referral%20Laboratories%20notified%20under%20section%2043.pdf",
    "nrl": "https://fssai.gov.in/docs/food-testing/food-lab/Office%20Order%20of%20list%20of%20laboratories%20approved%20as%20NRLs.pdf",
}


def discover_pdf_urls(timeout_ms: int = 45000) -> dict:
    """Render the landing page and pick out the current Primary/Referral/NRL
    PDF links by matching on the page's own link text, not position (the
    page also links dozens of unrelated notices/orders PDFs)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed — using hardcoded fallback URLs")
        return dict(FALLBACK_URLS)

    urls = dict(FALLBACK_URLS)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(LANDING_URL, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(2000)
            links = page.eval_on_selector_all(
                "a", "els => els.map(a => ({text: a.textContent, href: a.href, "
                     "ctx: a.closest('div') ? a.closest('div').parentElement.textContent : ''}))"
            )
            browser.close()
        for link in links:
            href = link.get("href", "")
            ctx = (link.get("ctx") or "").lower()
            if not href.endswith(".pdf"):
                continue
            if "referral" in ctx and "referral" not in urls.get("_seen", ""):
                urls["referral"] = href
            elif "national reference" in ctx or "nrl" in ctx:
                urls["nrl"] = href
            elif "primary" in ctx or "nabl" in ctx:
                urls["primary"] = href
    except Exception as e:  # noqa: BLE001
        logger.warning("landing page discovery failed (%s) — using fallback URLs", e)
    return urls


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


# ------------------------------------------------------------
# Per-list parsers
# ------------------------------------------------------------

_REGION_RE = re.compile(r"^[A-Z]\.\s")
_STATE_FROM_ADDRESS_RE = re.compile(r",\s*([A-Za-z][A-Za-z &]+?)\s*[-–]?\s*\d{6}\s*$")


def parse_primary(pdf_bytes: bytes) -> list[dict]:
    import pdfplumber
    out = []
    current_state = None
    stop = False
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            if stop:
                break
            for table in page.extract_tables():
                for row in table:
                    if stop:
                        break
                    c0 = (row[0] or "").strip()
                    if not c0:
                        continue
                    if c0.startswith("Annexure II"):
                        stop = True  # expired/suspended labs — out of scope
                        break
                    if c0.startswith("Annexure") or len(c0) > 60:
                        continue  # title/footnote junk
                    rest_blank = all(not (c or "").strip() for c in row[1:3])
                    if rest_blank and not c0[0].isdigit():
                        if _REGION_RE.match(c0):
                            continue  # region header, not a state
                        current_state = c0.title() if c0.isupper() else c0
                        continue
                    if c0[0].isdigit() and current_state:
                        name_addr = (row[1] or "").split("\n")[0].strip()
                        nabl_cert = (row[3] or "").strip() if len(row) > 3 else ""
                        reg_no = (row[2] or "").strip() if len(row) > 2 else ""
                        if name_addr:
                            out.append({
                                "name": name_addr,
                                "tier": 1,
                                "state": current_state,
                                "accreditation": f"NABL-accredited (reg. {reg_no})" if reg_no else "NABL-accredited",
                                "accreditation_ref": nabl_cert or None,
                            })
    return out


def parse_referral(pdf_bytes: bytes) -> list[dict]:
    import pdfplumber
    out = []
    current_state = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    sno = (row[0] or "").strip()
                    if not sno or not sno.rstrip(".").isdigit():
                        continue
                    state_cell = (row[3] or "").strip() if len(row) > 3 else ""
                    if state_cell:
                        current_state = state_cell
                    name_addr = (row[-1] or "").split("\n")[0].strip()
                    if name_addr and current_state:
                        out.append({
                            "name": name_addr,
                            "tier": 2,
                            "state": current_state,
                            "accreditation": "Referral laboratory (FSS Act s.43)",
                            "accreditation_ref": None,
                        })
    return out


def parse_nrl(pdf_bytes: bytes) -> list[dict]:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    sno = (row[0] or "").strip()
                    if not sno or not sno.rstrip(".").isdigit():
                        continue
                    if len(row) < 3:
                        continue
                    # Unlike Primary/Referral, NRL's Name and Address are
                    # genuinely separate table columns (confirmed via the
                    # PDF's own header row: "Name of the Laboratory" vs
                    # "Address") — the name is often 2-3 lines on its own,
                    # so join it in full rather than truncating to line 1.
                    name = re.sub(r"\s+", " ", (row[1] or "")).strip()
                    address = (row[2] or "").replace("\n", " ")
                    m = _STATE_FROM_ADDRESS_RE.search(address)
                    state = m.group(1).strip() if m else None
                    area = (row[3] or "").replace("\n", " ").strip() if len(row) > 3 else ""
                    if name:
                        out.append({
                            "name": name,
                            "tier": 1,
                            "state": state,
                            "accreditation": f"National Reference Lab ({area})" if area else "National Reference Lab",
                            "accreditation_ref": None,
                        })
    return out


# ------------------------------------------------------------
# Ingest
# ------------------------------------------------------------

def ingest(conn, rows: list[dict], source_url: str) -> dict:
    summary = {"scraped": len(rows), "inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc)
    for r in rows:
        name = (r.get("name") or "").strip()[:250]
        if not name:
            summary["skipped"] += 1
            continue
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO labs (name, tier, state, accreditation, accreditation_ref, source_url, fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (name) DO UPDATE SET
                     tier = EXCLUDED.tier, state = EXCLUDED.state,
                     accreditation = EXCLUDED.accreditation,
                     accreditation_ref = EXCLUDED.accreditation_ref,
                     source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at
                   RETURNING (xmax = 0) AS inserted""",
                (name, r["tier"], r.get("state"), r.get("accreditation"),
                 r.get("accreditation_ref"), source_url, now),
            )
            was_insert = cur.fetchone()[0]
            summary["inserted" if was_insert else "updated"] += 1
    conn.commit()
    return summary


def run() -> dict:
    urls = discover_pdf_urls()
    total = {"scraped": 0, "inserted": 0, "updated": 0, "skipped": 0}
    conn = pg_connect()
    try:
        for key, parser in (("primary", parse_primary), ("referral", parse_referral), ("nrl", parse_nrl)):
            candidates = [urls.get(key), FALLBACK_URLS.get(key)]
            for url in dict.fromkeys(u for u in candidates if u):  # dedupe, keep order
                try:
                    pdf_bytes = _download(url)
                    rows = parser(pdf_bytes)
                except Exception as e:  # noqa: BLE001
                    logger.warning("failed to fetch/parse %s list (%s): %s", key, url, e)
                    continue
                if not rows:
                    # Landing-page link discovery is a best-effort heuristic
                    # over a page full of unrelated notice PDFs (see
                    # discover_pdf_urls' docstring) — it can grab the wrong
                    # link. Zero parsed rows from a "successfully downloaded"
                    # PDF means we probably got the wrong document; try the
                    # next candidate (the hardcoded fallback) before giving up.
                    logger.warning("%s: %s parsed to 0 rows, trying next candidate", key, url)
                    continue
                summary = ingest(conn, rows, url)
                logger.info("%s: %s", key, summary)
                for k in total:
                    total[k] += summary.get(k, 0)
                break
    finally:
        conn.close()
    return total


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Ingest FSSAI food testing lab directories").parse_args()
    summary = run()
    print("\n=== FSSAI LABS DIRECTORY SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
