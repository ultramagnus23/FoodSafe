"""
FoodSafe India — Lok Sabha (Parliament) Written Answer Ingester

Real, primary-source State/UT-wise FSSAI enforcement data — via Parliament,
not FSSAI's own channels. FSSAI/FoSCoS publish no structured district- or
state-level enforcement data (confirmed by direct API probing — see
docs/FSSAI_INGESTION.md), and the RTI filed 2026-07-11 (FSSAI/R/E/26/00836)
came back unable to provide it directly. But MPs regularly ask the Ministry
of Health & Family Welfare exactly this question in Lok Sabha, and the
written answers — including full State/UT x fiscal-year tables of samples
analysed, civil/criminal cases, and license cancellations — are published
as ordinary PDFs at sansad.in, discoverable through a plain, unauthenticated
JSON search API (no encryption, unlike FoSCoS's statistics gateway).

This is a genuinely different access story from every other FSSAI-adjacent
source in this pipeline: sansad.in's search endpoint
(GET /api_ls/question/qetFilteredQuestionsAns) returns clean JSON with
direct PDF links, callable with plain urllib/curl — no headless browser
needed for discovery (unlike fssai_commissioners.py / fssai_labs.py, whose
landing pages are client-rendered shells).

Table shape handled: Parliament answers vary in format (some report only
national 5-year totals, no state breakdown — see this module's docstring
note below). This ingester specifically targets and validates the
"State/UT-wise, N fiscal years" annexure shape (one row per state, a
repeating block of columns per fiscal year) and skips — logging why,
not crashing — any answer that doesn't match it, rather than guessing at
a generic parser for every possible table Parliament might produce.

Run:  python -m pipeline.sources.loksabha_qa
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.loksabha_qa")

SEARCH_API = "https://sansad.in/api_ls/question/qetFilteredQuestionsAns"
LOKSABHA_NO = 18  # current (18th) Lok Sabha

# Keywords likely to surface FSSAI/food-safety enforcement questions. Kept
# broad on purpose — false positives are cheap (the table-shape check below
# filters them out), false negatives (missing a real Q&A) are not.
SEARCH_KEYWORDS = [
    "food safety",
    "food adulteration",
    "FSSAI enforcement",
    "food samples",
    "Food Safety and Standards Act",
]

_YEAR_RE = re.compile(r"\((\d{4})-(\d{4})\)")


def _search(keyword: str, page_size: int = 50) -> list[dict]:
    params = urllib.parse.urlencode({
        "loksabhaNo": LOKSABHA_NO, "pageNo": 1, "locale": "en",
        "pageSize": page_size, "keyWord": keyword,
    })
    req = urllib.request.Request(f"{SEARCH_API}?{params}", headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data[0].get("listOfQuestions", []) if data else []


def discover_questions() -> list[dict]:
    """Search several keywords, dedupe by question number, keep only
    HEALTH AND FAMILY WELFARE questions (FSSAI's parent ministry)."""
    seen: dict[int, dict] = {}
    for kw in SEARCH_KEYWORDS:
        try:
            for q in _search(kw):
                if q.get("ministry", "").strip().upper() != "HEALTH AND FAMILY WELFARE":
                    continue
                seen[q["quesNo"]] = q
        except Exception as e:  # noqa: BLE001
            logger.warning("search failed for keyword %r: %s", kw, e)
    return list(seen.values())


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _parse_date(d: str) -> str | None:
    # source format: "13.03.2026"
    try:
        dd, mm, yyyy = d.split(".")
        return f"{yyyy}-{mm}-{dd}"
    except Exception:  # noqa: BLE001
        return None


def parse_state_annexure(pdf_bytes: bytes) -> list[dict]:
    """Find and parse a "State/UT-wise, N fiscal years" table if one exists
    in this PDF. Returns [] (not an exception) if the shape doesn't match —
    e.g. an answer with only a national-level table, or a state list but
    a different column layout than the one this parser understands."""
    import pdfplumber

    all_rows: list[list] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                all_rows.extend(table)

    # Locate the year-header row: contains 2+ cells matching "(YYYY-YYYY)".
    year_row_idx = None
    year_cols: list[tuple[int, str]] = []  # (column index, "YYYY-YYYY")
    for i, row in enumerate(all_rows):
        matches = [(j, _YEAR_RE.search(c or "")) for j, c in enumerate(row)]
        hits = [(j, m.group(1) + "-" + m.group(2)) for j, m in matches if m]
        if len(hits) >= 2:
            year_row_idx = i
            year_cols = hits
            break
    if year_row_idx is None or len(year_cols) not in (2, 3, 4, 5):
        return []  # not this table shape

    # Each year block is 4 columns wide (Samples Analysed, Civil Cases
    # Decided w/ Penalty, Criminal Cases Convictions, Cancelled License),
    # starting at the column the year label appears in.
    block_width = 4
    blocks = [(col, year) for col, year in year_cols]

    out: list[dict] = []
    for row in all_rows[year_row_idx + 1:]:
        if not row or len(row) < blocks[-1][0] + block_width:
            continue
        state_raw = (row[1] or "").replace("\n", " ").strip()
        sno = (row[0] or "").strip()
        if not state_raw or not sno.isdigit():
            continue  # header continuation / page-break artifact / Total row
        for col, year in blocks:
            vals = [(row[col + k] or "").replace(",", "").strip() for k in range(block_width)]
            if not any(vals):
                continue
            try:
                samples, civil, criminal, cancelled = (int(v) if v else None for v in vals)
            except ValueError:
                continue
            out.append({
                "state": state_raw,
                "fiscal_year": year,
                "samples_analyzed": samples,
                "civil_cases_decided_penalty": civil,
                "criminal_cases_convictions": criminal,
                "licenses_cancelled": cancelled,
            })
    return out


def ingest(conn, question: dict, rows: list[dict]) -> int:
    inserted = 0
    now = datetime.now(timezone.utc)
    answered_date = _parse_date(question.get("date", ""))
    subject = (question.get("subjects") or "").strip()
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO state_enforcement_annual
                     (state, fiscal_year, samples_analyzed, civil_cases_decided_penalty,
                      criminal_cases_convictions, licenses_cancelled, source_question_no,
                      source_ministry, source_question_subject, answered_date, source_url, fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (state, fiscal_year, source_question_no) DO UPDATE SET
                     samples_analyzed = EXCLUDED.samples_analyzed,
                     civil_cases_decided_penalty = EXCLUDED.civil_cases_decided_penalty,
                     criminal_cases_convictions = EXCLUDED.criminal_cases_convictions,
                     licenses_cancelled = EXCLUDED.licenses_cancelled,
                     fetched_at = EXCLUDED.fetched_at""",
                (r["state"], r["fiscal_year"], r["samples_analyzed"], r["civil_cases_decided_penalty"],
                 r["criminal_cases_convictions"], r["licenses_cancelled"], question["quesNo"],
                 question.get("ministry"), subject, answered_date, question["questionsFilePath"], now),
            )
            inserted += 1
    conn.commit()
    return inserted


def run() -> dict:
    # "inserted" (not just "rows_inserted") so pipeline.run_and_log's
    # _rows_ingested() recognizes a non-zero result — it only checks
    # {"inserted", "fetched", "scraped"}.
    summary = {"questions_found": 0, "questions_matched": 0, "rows_inserted": 0, "inserted": 0, "skipped": 0}
    questions = discover_questions()
    summary["questions_found"] = len(questions)
    conn = pg_connect()
    try:
        for q in questions:
            url = q.get("questionsFilePath")
            if not url:
                summary["skipped"] += 1
                continue
            try:
                pdf_bytes = _download(url)
                rows = parse_state_annexure(pdf_bytes)
            except Exception as e:  # noqa: BLE001
                logger.warning("failed to fetch/parse Q%s (%s): %s", q.get("quesNo"), url, e)
                summary["skipped"] += 1
                continue
            if not rows:
                summary["skipped"] += 1
                continue
            summary["questions_matched"] += 1
            n = ingest(conn, q, rows)
            summary["rows_inserted"] += n
            summary["inserted"] += n
            logger.info("Q%s (%s): %d rows", q["quesNo"], q.get("subjects", "").strip()[:60], len(rows))
    finally:
        conn.close()
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Ingest Lok Sabha written answers on FSSAI enforcement").parse_args()
    summary = run()
    print("\n=== LOK SABHA Q&A INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
