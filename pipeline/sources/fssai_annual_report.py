"""
FoodSafe India — FSSAI Annual Report "Progress on Enforcement Metrics" Ingester

Real, national-level FSSAI enforcement metrics — samples analysed, the
non-conforming breakdown (unsafe / sub-standard / labelling), and civil +
criminal case outcomes with penalty amounts — one row per fiscal year,
straight from FSSAI's own Annual Report PDFs (fssai.gov.in/knowledge-hub,
tab=annual-report).

No URL formula exists across years (filenames vary: "Annual_Report_2023-
24.pdf", "FSSAIAnnualReport_2022-23.pdf", "FSSAI_Annual_Report_2021-
22.pdf", ...) — this is a maintained manifest (YEAR_MANIFEST below), not a
generator, same discipline as pipeline/sources/fssai_commissioners.py's
landing-page discovery.

File-size reality check (confirmed via HEAD request, 2026-09-02): recent
years' PDFs are enormous — 2023-24 is 614MB, 2022-23 is 352MB, 2017-18 is
128MB, 2024-25 is 176MB — apparently high-resolution scanned/embedded
images rather than the lean digitally-typeset documents older years are.
Only 2018-19 through 2021-22 (7-8MB each) are currently ingested; the
larger years are deliberately NOT in YEAR_MANIFEST rather than attempted
and skipped at runtime, because downloading 600MB to extract one table is
a real cost (bandwidth, CI runtime) worth a human decision, not a silent
default. See docs/FSSAI_INGESTION.md.

No fixed page number works either — the table lands on a different
absolute PDF page each year (bilingual reports put the English half
100+ pages in) — so this locates it by searching for the table's own
header row ("Enforcement Metric" + "Numbers" columns) rather than a page
index, and classifies each row by matching keywords in its metric-label
cell (robust to minor year-to-year phrasing drift, e.g. "food samples
analysed" vs "number of food samples collected and analysed") rather than
assuming stable row numbering (the report's own sub-item lettering a/b/c
already shows numbering isn't stable).

Run:  python -m pipeline.sources.fssai_annual_report
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import urllib.request

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.fssai_annual_report")

# Maintained manifest: fiscal_year -> PDF URL. Only years with a
# reasonably-sized PDF (checked via HEAD request) AND a table shape this
# module's classifier understands are included — see module docstring.
# Add a year here only after confirming both.
#
# 2018-19 is deliberately excluded despite its PDF being small (8MB): its
# "Progress on enforcement metrics" table uses an entirely different,
# coarser shape — civil/criminal figures merged into single rows ("Civil
# proceedings launched", one merged "Convictions" row, one merged "Cases
# where penalty was Imposed") rather than this module's field set. Running
# it through this classifier silently produced wrong numbers (confirmed:
# samples_analyzed came back as 106 instead of ~106,459 — the source PDF
# renders it as "1,06, 459" with a stray space that truncated the regex
# match, and several fields FSSAI didn't disaggregate that year picked up
# values from unrelated table rows via keyword collision). A correct
# import of 2018-19 needs its own dedicated parser, not a bugfix to this
# one — not done here.
YEAR_MANIFEST: dict[str, str] = {
    "2019-2020": "https://fssai.gov.in/docs/annual-report/FSSAI_Annual_Report_2019_20_English_Hindi.pdf",
    "2020-2021": "https://fssai.gov.in/docs/annual-report/FSSAI_Annual_Report_2020-21.pdf",
    "2021-2022": "https://fssai.gov.in/docs/annual-report/FSSAI_Annual_Report_2021-22.pdf",
}

_METRIC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("samples_analyzed", re.compile(r"food samples analys", re.I)),
    ("samples_non_conforming", re.compile(r"total samples found non", re.I)),
    ("non_conforming_unsafe", re.compile(r"non-conforming samples-unsafe|non conforming samples-unsafe", re.I)),
    ("non_conforming_substandard", re.compile(r"sub[- ]?standard", re.I)),
    ("non_conforming_labelling", re.compile(r"labelling defects|misleading|miscellaneous", re.I)),
    ("civil_cases_launched", re.compile(r"civil cases launched", re.I)),
    # "decided" (2019-20/2020-21 phrasing) and "convictions in" (2021-22
    # phrasing) are NOT the same thing — decided cases can include
    # non-conviction outcomes — so these stay separate columns rather than
    # merging into one that would misrepresent whichever year used
    # "decided" as if it meant "convicted".
    ("civil_cases_decided", re.compile(r"civil cases decided", re.I)),
    ("civil_cases_convictions", re.compile(r"convictions in civil", re.I)),
    ("civil_penalty_amount", re.compile(r"penalty imposed in civil", re.I)),
    ("criminal_cases_launched", re.compile(r"criminal cases launched", re.I)),
    ("criminal_cases_decided", re.compile(r"criminal cases decided", re.I)),
    ("criminal_cases_convictions", re.compile(r"convictions in criminal", re.I)),
    ("criminal_penalty_amount", re.compile(r"penalty imposed in criminal", re.I)),
    ("criminal_acquittals", re.compile(r"acquittals in criminal", re.I)),
    ("total_penalty_amount", re.compile(r"total amount of penalty|total value of penalt", re.I)),
]

_NUM_RE = re.compile(r"[\d,]+(?:\.\d+)?")
_CRORE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*cr", re.I)


def _parse_number(text: str) -> int | None:
    """Extract an integer from text like '1,44,345', '? 53,39,15,801'
    (the '?' is a mis-rendered rupee symbol from the PDF's font encoding),
    or a crore-denominated figure like 'Rs. 32.57 cr' (multiply by 1e7).
    Indian digit grouping (lakh/crore commas) parses fine once commas are
    stripped. A stray space can appear inside a digit group from PDF text
    extraction (e.g. '1,06, 459' instead of '1,06,459') — collapsed here
    before matching, since otherwise the number regex stops at the space
    and silently returns a truncated value (caught via a real example:
    this exact case parsed as 106 instead of 106459 before this fix)."""
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    crore_m = _CRORE_RE.search(text)
    if crore_m:
        return round(float(crore_m.group(1)) * 1_00_00_000)
    m = _NUM_RE.search(text)
    if not m:
        return None
    return int(float(m.group(0).replace(",", "")))


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_enforcement_table(pdf_bytes: bytes) -> dict | None:
    """Find the "Progress on enforcement metrics" table by its own header
    row (not a fixed page number — this shifts every year) and classify
    each row by matching the metric-label cell against known patterns.
    Returns None if the table isn't found in this PDF at all."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                header = [(c or "").strip() for c in (table[0] if table else [])]
                if not any("enforcement metric" in h.lower() for h in header):
                    continue
                result: dict = {}
                for row in table[1:]:
                    if not row or len(row) < 3:
                        continue
                    label = (row[1] or "").strip()
                    value_text = (row[2] or "").strip()
                    if not label or not value_text:
                        continue
                    for field, pattern in _METRIC_PATTERNS:
                        if pattern.search(label):
                            result[field] = _parse_number(value_text)
                            break
                if result:
                    return result
    return None


def ingest(conn, fiscal_year: str, metrics: dict, source_url: str) -> bool:
    fields = [
        "samples_analyzed", "samples_non_conforming", "non_conforming_unsafe",
        "non_conforming_substandard", "non_conforming_labelling", "civil_cases_launched",
        "civil_cases_decided", "civil_cases_convictions", "civil_penalty_amount",
        "criminal_cases_launched", "criminal_cases_decided", "criminal_cases_convictions",
        "criminal_penalty_amount", "criminal_acquittals", "total_penalty_amount",
    ]
    values = [metrics.get(f) for f in fields]
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO national_enforcement_annual
                  (fiscal_year, {", ".join(fields)}, source_url, fetched_at)
                VALUES (%s, {", ".join(["%s"] * len(fields))}, %s, NOW())
                ON CONFLICT (fiscal_year) DO UPDATE SET
                  {", ".join(f"{f} = EXCLUDED.{f}" for f in fields)},
                  source_url = EXCLUDED.source_url, fetched_at = NOW()""",
            (fiscal_year, *values, source_url),
        )
    conn.commit()
    return True


def run() -> dict:
    summary = {"years_attempted": 0, "years_matched": 0, "inserted": 0, "skipped": 0}
    conn = pg_connect()
    try:
        for fiscal_year, url in YEAR_MANIFEST.items():
            summary["years_attempted"] += 1
            try:
                pdf_bytes = _download(url)
                metrics = parse_enforcement_table(pdf_bytes)
            except Exception as e:  # noqa: BLE001
                logger.warning("failed to fetch/parse %s (%s): %s", fiscal_year, url, e)
                summary["skipped"] += 1
                continue
            if not metrics:
                logger.warning("%s: enforcement table not found in PDF", fiscal_year)
                summary["skipped"] += 1
                continue
            ingest(conn, fiscal_year, metrics, url)
            summary["years_matched"] += 1
            summary["inserted"] += 1
            logger.info("%s: %s", fiscal_year, metrics)
    finally:
        conn.close()
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Ingest FSSAI Annual Report national enforcement metrics").parse_args()
    summary = run()
    print("\n=== FSSAI ANNUAL REPORT ENFORCEMENT METRICS SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
