"""
Codex Alimentarius maximum levels for contaminants and toxins — the General
Standard for Contaminants and Toxins in Food and Feed (CXS 193-1995, last
amended 2025), read from FAO's official PDF.

The schedule has one section per contaminant (its start page is listed in the
standard's own index, Table A1, page 11). Each section opens with the WHY —
'Reference to JECFA' and 'Toxicological guidance value' (e.g. JECFA's
withdrawal of the lead PTWI because it was no longer health-protective) — and
then a table: Commodity/product name | Maximum level (ML) | Portion | Notes.

-> food_standards           (jurisdiction 'CODEX', contaminant_ml), one row per ML
-> hazard_reference_values  (body 'JECFA', value_type 'guidance'): the printed
                            toxicological guidance text for each contaminant,
                            verbatim, as the reason the limits exist

Rules: a row is kept only if its ML cell is one number; the unit comes from the
table header ('mg/kg' / 'µg/kg'). Radionuclide guideline levels (Bq/kg) are not
maximum levels and are not loaded. A row whose notes say the ML is for
inorganic arsenic is labelled 'Arsenic (inorganic)' (the section is 'total
arsenic unless otherwise mentioned').

Run: python -m pipeline.sources.standards_codex_contaminants [--dry-run] [--pdf local.pdf]
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Optional

from pipeline.sources.standards_common import (StandardRow, clean_text, hazard_key, replace_snapshot, sha256_bytes,
                                               summarise)

logger = logging.getLogger("foodsafe.standards_codex_contaminants")

PDF_URL = "https://openknowledge.fao.org/server/api/core/bitstreams/4d0e7245-8166-49ca-b822-ca80a1ff5cfe/content"
USER_AGENT = "Mozilla/5.0 (FoodSafe-India public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
PARSER_VERSION = "codex-cxs193-1"
LEGAL_REF = "Codex CXS 193-1995 (General Standard for Contaminants and Toxins in Food and Feed)"

CLASSES = {
    "Aflatoxins, total": "mycotoxin", "Aflatoxin M1": "mycotoxin", "Deoxynivalenol (DON)": "mycotoxin",
    "Fumonisins": "mycotoxin", "Ochratoxin A": "mycotoxin", "Patulin": "mycotoxin",
    "Arsenic": "heavy_metal", "Cadmium": "heavy_metal", "Lead": "heavy_metal", "Mercury": "heavy_metal",
    "Methylmercury": "heavy_metal", "Tin": "heavy_metal", "Acrylonitrile": "process_contaminant",
    "Chloropropanols": "process_contaminant", "Hydrocyanic acid": "natural_toxin", "Melamine": "other",
    "Vinylchloride monomer": "process_contaminant",
}
SKIP = {"Marine biotoxins", "Radionuclides"}


def parse_index(page_text: str) -> list[tuple[str, int]]:
    """Table A1 lines 'Aflatoxins, total 15' -> [(name, start page)]. 'Aflatoxin M 43'
    (subscript 1 printed on the next line) becomes 'Aflatoxin M1'."""
    out = []
    for line in page_text.split("\n"):
        m = re.match(r"^([A-Z][A-Za-z ,()-]+?)\s+(\d{1,3})$", line.strip())
        if m and m.group(1) not in ("NAME PAGE",):
            name = m.group(1).strip()
            if name == "Aflatoxin M":
                name = "Aflatoxin M1"
            out.append((name, int(m.group(2))))
    return out


def guidance_text(page_text: str) -> Optional[str]:
    m = re.search(r"Toxicological guidance value:\s*(.*?)\s*Contaminant definition:", page_text, re.S)
    if not m:
        return None
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return t or None


def _num(s: str) -> Optional[Decimal]:
    """'0.35' / '15' / '4 000' (space as thousands separator) -> Decimal."""
    t = (s or "").strip()
    if re.fullmatch(r"\d{1,3}(?: \d{3})+", t):
        t = t.replace(" ", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_section(name: str, tables: list[tuple[int, list[list[Optional[str]]]]]) -> list[StandardRow]:
    rows = []
    hclass = CLASSES.get(name, "other")
    unit = None
    for page_no, table in tables:
        if not table:
            continue
        header = " ".join(clean_text(c) for c in table[0] if c).lower()
        # Only ML tables: 'Commodity/product name | Maximum level (ML) <unit> | ...'. The
        # sampling-plan annexes ('Maximum level | 2 000 µg/kg DON', 'Lot weight (t) | ...')
        # have no commodity column and are skipped; ML tables repeat their header on
        # every page, so a header-less table is never an ML continuation.
        if not ("commodity" in header and "maximum level" in header):
            continue
        unit = "µg/kg" if re.search(r"[µμu]g/kg", header) else ("mg/kg" if "mg/kg" in header else None)
        if unit is None:
            continue
        body = table[1:]
        for r in body:
            cells = [clean_text(c) for c in (r + [None] * 4)[:4]]
            commodity, ml, portion, notes = cells
            if not commodity or "maximum level" in ml.lower():
                continue
            v = _num(ml)
            if v is None:
                continue
            hname = name
            if name == "Arsenic" and re.search(r"inorganic arsenic|As-in", notes, re.I):
                hname = "Arsenic (inorganic)"
            elif name == "Arsenic":
                hname = "Arsenic (total)"
            rows.append(StandardRow(
                jurisdiction="CODEX", standard_type="contaminant_ml", hazard_raw=hname, hazard_class=hclass,
                food_raw=commodity, limit_raw=ml, limit_value=v, limit_unit=unit, parse_status="exact",
                note=notes[:500] or None, legal_reference=LEGAL_REF, source_url=PDF_URL, source_page=page_no,
                extra={"portion": portion[:300]} if portion else {},
            ))
    return rows


def parse_pdf(data: bytes) -> tuple[list[StandardRow], list[dict], dict]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
        index_page = next((i for i, t in enumerate(texts) if "Table A1: Index of contaminants" in t), None)
        if index_page is None:
            raise RuntimeError("CXS 193 layout changed: no 'Table A1: Index of contaminants'")
        sections = parse_index(texts[index_page])
        if len(sections) < 15:
            raise RuntimeError(f"index lists only {len(sections)} contaminants")
        bounds = [(n, p, sections[i + 1][1] if i + 1 < len(sections) else len(texts) + 1)
                  for i, (n, p) in enumerate(sections)]
        rows, guidance = [], []
        for name, start, end in bounds:
            if name in SKIP:
                continue
            tables = []
            for pno in range(start, min(end, len(texts) + 1)):
                for t in pdf.pages[pno - 1].find_tables():
                    tables.append((pno, t.extract()))
            got = parse_section(name, tables)
            rows += got
            g = guidance_text(texts[start - 1])
            if g:
                guidance.append({"hazard_name": name, "hazard_key": hazard_key(
                    "Arsenic (inorganic)" if name == "Arsenic" else name), "raw_text": g, "page": start})
            logger.info("CXS 193 %-24s pages %d-%d: %d MLs", name, start, end - 1, len(got))
    return rows, guidance, {"contaminants": len(sections), "with_guidance": len(guidance)}


def load_guidance(conn, guidance: list[dict]) -> int:
    with conn.cursor() as cur:
        for g in guidance:
            if not g["hazard_key"]:
                continue
            cur.execute(
                """INSERT INTO hazard_reference_values (hazard_key, body, value_type, value, unit, raw_text, year,
                                                        source_ref, source_url)
                   VALUES (%s,'JECFA','guidance',NULL,NULL,%s,NULL,%s,%s)
                   ON CONFLICT (hazard_key, body, value_type) DO UPDATE SET raw_text=EXCLUDED.raw_text,
                     source_ref=EXCLUDED.source_ref, source_url=EXCLUDED.source_url, loaded_at=NOW()""",
                (g["hazard_key"], g["raw_text"], f"{LEGAL_REF}, p. {g['page']} (toxicological guidance value)",
                 PDF_URL))
    conn.commit()
    return len(guidance)


def run(dry_run: bool = False, pdf_path: Optional[str] = None) -> dict:
    if pdf_path:
        data = open(pdf_path, "rb").read()
    else:
        req = urllib.request.Request(PDF_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("CXS 193 download is not a PDF")
    rows, guidance, info = parse_pdf(data)
    info.update(summarise(rows))
    if len(rows) < 100:
        raise RuntimeError(f"only {len(rows)} Codex MLs parsed; refusing to load")
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "CODEX", {"contaminant_ml"}, rows, document_title=LEGAL_REF,
                               document_url=PDF_URL, document_version="last amended 2025",
                               document_sha256=sha256_bytes(data), parser_version=PARSER_VERSION)
        res["guidance_loaded"] = load_guidance(conn, guidance)
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pdf")
    a = ap.parse_args()
    print(run(a.dry_run, a.pdf))


if __name__ == "__main__":
    main()
