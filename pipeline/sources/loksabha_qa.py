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

# Lok Sabha terms to search, newest first. Question numbers RESTART each term
# (Q1234 in the 17th is unrelated to Q1234 in the 16th), which is why
# state_enforcement_annual's uniqueness key includes lok_sabha_no
# (schema_migration_018.sql) and why questions are deduplicated on
# (lokNo, quesNo), never quesNo alone.
LOKSABHA_TERMS: tuple[int, ...] = (18,)

# Keywords likely to surface FSSAI/food-safety enforcement questions. Kept
# broad on purpose — false positives are cheap (the table-shape check below
# filters them out), false negatives (missing a real Q&A) are not.
SEARCH_KEYWORDS = [
    "food safety",
    "food adulteration",
    "FSSAI enforcement",
    "food samples",
    "Food Safety and Standards Act",
    "FSSAI",
    "adulterated milk",
    "milk adulteration",
    "food business operator",
    "unsafe food",
    "FSSAI inspections",
    "food license",
    "food testing",
]

_YEAR_RE = re.compile(r"\((\d{4})-(\d{4})\)")

# PDF cell text for State/UT names arrives mangled in inconsistent ways
# across different answers — multi-line cells joined without a space
# ("TamilNadu", "AndNicobar"), abbreviations ("A&N Islands", "J&K"), and
# at least one outright misspelling ("Chattisgarh" for Chhattisgarh,
# confirmed in AU3459's own table). Without canonicalizing, the same state
# fragments across three separate source questions instead of merging,
# which defeats the point of cross-referencing multiple Parliamentary
# answers. This list is explicit rather than fuzzy-matched — silently
# guessing at a state name is worse than skipping an unrecognized one.
_STATE_CANON_RAW: dict[str, str] = {
    "andamanandnicobarislands": "Andaman and Nicobar Islands",
    "a&nislands": "Andaman and Nicobar Islands",
    "andhrapradesh": "Andhra Pradesh",
    "arunachalpradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chandigarh": "Chandigarh",
    "chhattisgarh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "dadraandnagarhaveli&daman&diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadranh&dd": "Dadra and Nagar Haveli and Daman and Diu",
    "delhi": "Delhi",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachalpradesh": "Himachal Pradesh",
    "jammu&kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "lakshwadeep": "Lakshadweep",
    "madhyapradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "maharasthra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "orissa": "Odisha",
    "odisha": "Odisha",
    "puducherry": "Puducherry",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamilnadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttarpradesh": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "westbengal": "West Bengal",
}

# Keys above are written human-readably (some contain "&") but the lookup
# in _canon_state() strips everything but letters before matching — so the
# dict keys must go through the identical transform, or e.g. "J&K" (key
# "j&k") would never match a normalized lookup of "jk". Built once here
# rather than trusting every key above to already be pre-stripped by hand.
_STATE_CANON: dict[str, str] = {
    re.sub(r"[^a-z]", "", k): v for k, v in _STATE_CANON_RAW.items()
}


def _canon_state(raw: str) -> str | None:
    """Normalize a scraped state/UT name to a canonical form, or None if
    unrecognized (caller should skip the row rather than guess)."""
    key = re.sub(r"[^a-z]", "", raw.lower())
    return _STATE_CANON.get(key)


def _search(keyword: str, loksabha_no: int, page_size: int = 200) -> list[dict]:
    params = urllib.parse.urlencode({
        "loksabhaNo": loksabha_no, "pageNo": 1, "locale": "en",
        "pageSize": page_size, "keyWord": keyword,
    })
    req = urllib.request.Request(f"{SEARCH_API}?{params}", headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if not data:
        return []
    first = data[0]
    total = first.get("totalRecordSize") or 0
    if total > page_size:
        # No pagination implemented — surface it instead of silently
        # dropping the tail. Observed totals are far below this today.
        logger.warning("keyword %r, LS%s: %s matches but only %s fetched", keyword, loksabha_no, total, page_size)
    return first.get("listOfQuestions", [])


def question_key(q: dict) -> tuple[int, str]:
    """Identity of a Parliamentary question: (Lok Sabha number, question no.)."""
    return int(q["lokNo"]), str(q["quesNo"]).strip()


def discover_questions(terms: tuple[int, ...] | None = None) -> list[dict]:
    """Search several keywords across Lok Sabha terms, dedupe on
    (lokNo, quesNo), keep only HEALTH AND FAMILY WELFARE questions
    (FSSAI's parent ministry)."""
    seen: dict[tuple[int, str], dict] = {}
    for term in (terms or LOKSABHA_TERMS):
        for kw in SEARCH_KEYWORDS:
            try:
                for q in _search(kw, term):
                    if q.get("ministry", "").strip().upper() != "HEALTH AND FAMILY WELFARE":
                        continue
                    seen[question_key(q)] = q
            except Exception as e:  # noqa: BLE001
                logger.warning("search failed for keyword %r (LS%s): %s", kw, term, e)
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
        state = _canon_state(state_raw)
        if state is None:
            logger.warning("unrecognized state/UT name %r — skipping row", state_raw)
            continue
        for col, year in blocks:
            vals = [(row[col + k] or "").replace(",", "").strip() for k in range(block_width)]
            if not any(vals):
                continue
            try:
                samples, civil, criminal, cancelled = (int(v) if v else None for v in vals)
            except ValueError:
                continue
            out.append({
                "state": state,
                "fiscal_year": year,
                "samples_analyzed": samples,
                "civil_cases_decided_penalty": civil,
                "criminal_cases_convictions": criminal,
                "licenses_cancelled": cancelled,
            })
    return out


_BARE_YEAR_RE = re.compile(r"\b(20\d{2})[-–](\d{2,4})\b")
_METRIC_KEYWORDS = [
    ("licenses_cancelled", ("cancel",)),
    ("samples_analyzed", ("sample", "analys")),
    ("civil_cases_decided_penalty", ("civil",)),
    ("criminal_cases_convictions", ("criminal", "convict")),
]


def _classify_metric(header_text: str) -> str | None:
    low = header_text.lower()
    for field, keywords in _METRIC_KEYWORDS:
        if any(k in low for k in keywords):
            return field
    return None


def parse_single_metric_annexure(pdf_bytes: bytes) -> list[dict]:
    """A second, simpler "State/UT x year" shape seen in some answers (e.g.
    AU4786 "FSSAI Inspections"): no S.No column, no 4-column-per-year
    block — each year is exactly one column, reporting a single metric
    (e.g. licenses cancelled), with the metric name only identifiable from
    the header text (not position), and years written bare ("2021-22")
    rather than "(2021-2022)". Independent of parse_state_annexure above —
    tried as a fallback in run(), not a replacement."""
    import pdfplumber

    all_rows: list[list] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                all_rows.extend(table)

    header_idx = None
    year_cols: list[tuple[int, str, str]] = []  # (col, "YYYY-YYYY", metric_field)
    for i, row in enumerate(all_rows):
        if not row or not (row[0] or "").strip().lower().startswith("state"):
            continue
        hits = []
        for j, c in enumerate(row):
            if j == 0 or not c:
                continue
            m = _BARE_YEAR_RE.search(c)
            if not m:
                continue
            yr2 = m.group(2)
            year = f"{m.group(1)}-{yr2}" if len(yr2) == 4 else f"{m.group(1)}-20{yr2}"
            metric = _classify_metric(c)
            if metric:
                hits.append((j, year, metric))
        if len(hits) >= 2:
            header_idx = i
            year_cols = hits
            break
    if header_idx is None:
        return []

    # Keyed by (state, fiscal_year) so multiple single-metric columns for
    # the same year (if a table ever has them) merge into one row instead
    # of separately-inserted rows clobbering each other via upsert.
    merged: dict[tuple[str, str], dict] = {}
    for row in all_rows[header_idx + 1:]:
        if not row:
            continue
        state_raw = (row[0] or "").replace("\n", " ").strip()
        if not state_raw or not re.search(r"[A-Za-z]{2,}", state_raw) or state_raw.lower().startswith("total"):
            continue
        state = _canon_state(state_raw)
        if state is None:
            logger.warning("unrecognized state/UT name %r — skipping row", state_raw)
            continue
        for col, year, metric in year_cols:
            if col >= len(row):
                continue
            val = (row[col] or "").replace(",", "").strip()
            if not val:
                continue
            try:
                num = int(val)
            except ValueError:
                continue
            key = (state, year)
            entry = merged.setdefault(key, {
                "state": state, "fiscal_year": year,
                "samples_analyzed": None, "civil_cases_decided_penalty": None,
                "criminal_cases_convictions": None, "licenses_cancelled": None,
            })
            entry[metric] = num
    return list(merged.values())


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
                      criminal_cases_convictions, licenses_cancelled, lok_sabha_no, source_question_no,
                      source_ministry, source_question_subject, answered_date, source_url, fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (state, fiscal_year, lok_sabha_no, source_question_no) DO UPDATE SET
                     samples_analyzed = EXCLUDED.samples_analyzed,
                     civil_cases_decided_penalty = EXCLUDED.civil_cases_decided_penalty,
                     criminal_cases_convictions = EXCLUDED.criminal_cases_convictions,
                     licenses_cancelled = EXCLUDED.licenses_cancelled,
                     fetched_at = EXCLUDED.fetched_at""",
                (r["state"], r["fiscal_year"], r["samples_analyzed"], r["civil_cases_decided_penalty"],
                 r["criminal_cases_convictions"], r["licenses_cancelled"], int(question["lokNo"]), question["quesNo"],
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
                rows = parse_state_annexure(pdf_bytes) or parse_single_metric_annexure(pdf_bytes)
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
