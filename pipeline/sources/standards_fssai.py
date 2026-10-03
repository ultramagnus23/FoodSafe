"""
India's legal food-safety limits: FSSAI's Food Safety and Standards (Contaminants,
Toxins and Residues) Regulations, 2011 — the regulator's own consolidated
compendium PDF — parsed into `food_standards` rows (jurisdiction 'IN').

What the compendium holds and what this parser takes from it
  2.1    metal contaminants (lead, copper, arsenic, tin, zinc, cadmium, mercury,
         methyl mercury, chromium, nickel, selenium ...)       -> contaminant_ml (mg/kg)
  2.2.1  crop contaminants: aflatoxins, aflatoxin M1, ochratoxin A, patulin, DON
                                                               -> contaminant_ml (µg/kg)
  2.2.2  naturally occurring toxic substances (agaric acid, hydrocyanic acid ...)
                                                               -> contaminant_ml (ppm)
  2.2.3  other contaminants (PCBs, benzo(a)pyrene)             -> contaminant_ml (unit in cell)
  2.3.1  pesticide maximum residue limits (~213 insecticides)  -> pesticide_mrl (mg/kg)
  2.3.2  antibiotic tolerance limits in seafood, and the list of
         antimicrobials/drugs not permitted in food animals    -> vet_drug_mrl / prohibited_substance
  The species x tissue veterinary-drug MRL table (2.3.2(4)) is not parsed yet:
  its layout nests species and tissues and needs its own validated parser.

How it is read (and why it can be trusted)
  pdfplumber's ruled-table extraction gives (S.No, name, food, limit) cells; the
  parser keeps every printed cell (`food_raw`, `limit_raw`) and stores a number
  only when the cell holds exactly one (`standards_common.parse_limit`). Amendment
  brackets ('16[ ... ]') are removed, footnote flags are decoded from the
  compendium's own legend: '*' = MRL fixed at the limit of quantification,
  '(F)' = fat basis, '$' = the copper metal limit applies. A cell such as
  'Wheat-0.05, Rice-2.0 and other food grains 0.1' is split into one row per
  food only if every number in it is accounted for; otherwise it stays one
  `compound` row with no value.
  Integrity checks (`check_pesticide_sequence`): the pesticide table's serial
  numbers must run 1..N without gaps or repeats, and N must equal the last serial
  number printed in the document — a dropped page or misread row fails the run
  instead of loading a silently short table.

Source: https://fssai.gov.in/upload/uploadfiles/files/Comp_Contaminants_Regulations_03_02_2026_IX.pdf
(Version IX, 03.02.2026). The URL is versioned by FSSAI; when a new compendium
is published, update COMPENDIUM_URL (the snapshot row records the sha256 of
whichever file was parsed).

Run: python -m pipeline.sources.standards_fssai [--pdf local.pdf] [--dry-run]
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import urllib.request
from decimal import Decimal
from typing import Optional

from pipeline.sources.standards_common import (
    StandardRow, clean_text, parse_limit, replace_snapshot, sha256_bytes, split_compound,
    strip_amendment_marks, summarise,
)

logger = logging.getLogger("foodsafe.standards_fssai")

COMPENDIUM_URL = "https://fssai.gov.in/upload/uploadfiles/files/Comp_Contaminants_Regulations_03_02_2026_IX.pdf"
COMPENDIUM_VERSION = "Version IX (03.02.2026)"
TITLE = "Food Safety and Standards (Contaminants, Toxins and Residues) Regulations, 2011 — FSSAI compendium"
PARSER_VERSION = "fssai-ctr-1"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"

REF = {
    "metals": "FSS (CTR) Regulations 2011, reg. 2.1 (metal contaminants)",
    "crop": "FSS (CTR) Regulations 2011, reg. 2.2.1 (crop contaminants)",
    "nots": "FSS (CTR) Regulations 2011, reg. 2.2.2 (naturally occurring toxic substances)",
    "other": "FSS (CTR) Regulations 2011, reg. 2.2 (other contaminants)",
    "pesticide": "FSS (CTR) Regulations 2011, reg. 2.3.1 (insecticide MRLs)",
    "antibiotic_tol": "FSS (CTR) Regulations 2011, reg. 2.3.2(1) (antibiotics in seafood)",
    "antibiotic_mrpl": "FSS (CTR) Regulations 2011, reg. 2.3.2(3) (MRPL, foods of animal origin)",
    "prohibited": "FSS (CTR) Regulations 2011, reg. 2.3.2(2) (not permitted in food-producing animals)",
    "histamine": "FSS (CTR) Regulations 2011, reg. 2.5.2 (histamine in fish and fishery products)",
}

def _section_of(header: list[Optional[str]]) -> Optional[tuple[str, Optional[str]]]:
    """A table header row -> (section, unit printed in the header). None if the
    row is not a header. Unknown headers return ('skip', None) so the rows under
    them (e.g. the histamine fish-species list) are never read as limits."""
    h = " ".join(clean_text(c) for c in header if c).lower()
    if not re.search(r"s\.\s*no|sl\.?\s*no|serial no|name of metal", h):
        return None
    unit = None
    if re.search(r"µg/kg|ug/kg|μg/kg", h):
        unit = "µg/kg"
    elif re.search(r"mg/kg|parts per\s*million|ppm", h):
        unit = "mg/kg"
    if "name of metal" in h:
        return "metals", unit or "mg/kg"
    if "name of the insecticide" in h:
        return "pesticide", unit or "mg/kg"
    if "naturally occur" in h:
        return "nots", unit or "mg/kg"
    if "histamine level" in h:
        return "histamine", "mg/kg"
    if "name of the contaminants" in h and unit == "µg/kg":
        return "crop", unit
    if "name of the contaminants" in h:
        return "other", unit
    if "name of antibiotics" in h and "mrpl" in h:
        return "antibiotic_mrpl", "µg/kg"
    if "name of antibiotics" in h:
        return "antibiotic_tol", "mg/kg"
    return "skip", None


def _hazard_class(section: str, name: str) -> str:
    n = clean_text(name).lower()
    if section == "metals":
        return "heavy_metal"
    if section == "pesticide":
        return "pesticide"
    if section.startswith("antibiotic"):
        return "veterinary_drug"
    if re.search(r"shellfish poison|azaspiracid|brevetoxin", n):
        return "marine_biotoxin"
    if section == "crop" or re.search(r"aflatoxin|ochratoxin|patulin|deoxynivalenol|fumonisin|zearalenone", n):
        return "mycotoxin"
    if section == "nots" or "histamine" in n:
        return "natural_toxin"
    if "benzo" in n:
        return "process_contaminant"
    if "polychlorinated" in n or "pcb" in n or "dioxin" in n:
        return "environmental_pollutant"
    return "other"


def _metal_name(cell: str) -> str:
    # '1. Lead' / '7. Methyl Mercury\n(Calculated as the\nelement)' -> 'Methyl Mercury (Calculated as the element)'
    t = clean_text(strip_amendment_marks(cell))
    return re.sub(r"^\d+\s*\.\s*", "", t).strip()


def _split_stacked(food: str, limit: str) -> Optional[list[tuple[str, str]]]:
    """'Nuts:\\nNuts for further processing\\nReady to eat' + '15\\n15' ->
    [('Nuts: Nuts for further processing', '15'), ('Nuts: Ready to eat', '15')].
    None when the cell is not such a stack."""
    f_lines = [l.strip() for l in (food or "").split("\n") if l.strip()]
    l_lines = [l.strip() for l in (limit or "").split("\n") if l.strip()]
    if len(l_lines) < 2 or not all(re.fullmatch(r"\d+(?:\.\d+)?\*?", l) for l in l_lines):
        return None
    if f_lines and f_lines[0].endswith(":") and len(f_lines) - 1 == len(l_lines):
        head = f_lines[0]
        return [(f"{head} {f}", v) for f, v in zip(f_lines[1:], l_lines)]
    return None


_BIOTOXIN_UNITS = [   # printed form -> multiplier to µg/kg
    (re.compile(r"^(\d+(?:\.\d+)?)\s*[µμu]g\s*/\s*100\s*g\b", re.I), Decimal(10)),
    (re.compile(r"^(\d+(?:\.\d+)?)\s*[µμu]g\s*/\s*g\b", re.I), Decimal(1000)),
    (re.compile(r"^(\d+(?:\.\d+)?)\s*[µμu]g\b[^/]*?/\s*kg\b", re.I), Decimal(1)),
]


def _biotoxin_limit(limit: str) -> Optional[Decimal]:
    """'80 μg/100g (Saxitoxin Equivalent)' -> 800 (µg/kg); '20 μg/g' -> 20000;
    '160 μg of Okadaic acid equivalent/Kg' -> 160. Mouse units -> None."""
    t = clean_text(strip_amendment_marks(limit))
    for rx, mult in _BIOTOXIN_UNITS:
        m = rx.match(t)
        if m:
            return Decimal(m.group(1)) * mult
    return None


_SAMPLING_PLAN = re.compile(r"n\s*=\s*(\d+)\s*,\s*c\s*=\s*(\d+)\s*;\s*m\s*=\s*(\d+(?:\.\d+)?)\s*mg/kg\s*,\s*M\s*=\s*"
                            r"(\d+(?:\.\d+)?)\s*mg/kg", re.I)


def parse_tables(pages: list[list[list[list[Optional[str]]]]]) -> tuple[list[StandardRow], list[int]]:
    """pages[i] = the tables pdfplumber found on page i+1 (each a list of rows).
    Returns the rows and the sequence of pesticide serial numbers seen (for the
    integrity check). Pure — testable without a PDF."""
    rows: list[StandardRow] = []
    serials: list[int] = []
    section: Optional[str] = None
    unit: Optional[str] = None
    hazard: Optional[str] = None
    last: Optional[StandardRow] = None

    def emit(sec: str, hz: str, food: str, limit: str, page: int):
        nonlocal last
        food_c = clean_text(strip_amendment_marks(food))
        limit_c = clean_text(limit)
        if not food_c and not limit_c:
            return
        stacked = _split_stacked(food, limit)
        if stacked:
            for f, v in stacked:
                emit(sec, hz, f, v, page)
            return
        unit_hint = "mg/l" if re.search(r"expressed in mg/l", food_c, re.I) else unit
        stype = "pesticide_mrl" if sec == "pesticide" else (
            "vet_drug_mrl" if sec.startswith("antibiotic") else "contaminant_ml")
        hclass = _hazard_class(sec, hz)
        base = dict(jurisdiction="IN", standard_type=stype, hazard_raw=hz, hazard_class=hclass,
                    legal_reference=REF.get(sec, REF["other"]), source_url=COMPENDIUM_URL, source_page=page)
        if hclass == "marine_biotoxin":
            v = _biotoxin_limit(limit_c)
            last = StandardRow(**base, food_raw=food_c, limit_raw=limit_c, limit_value=v,
                               limit_unit="µg/kg" if v is not None else None,
                               parse_status="exact" if v is not None else "not_numeric",
                               note="converted from the printed unit to µg/kg (toxin equivalents)" if v is not None
                               else "not a mass-fraction limit")
            rows.append(last)
            return
        if sec == "histamine":
            m = _SAMPLING_PLAN.search(limit_c)
            last = StandardRow(**base, food_raw=food_c, limit_raw=limit_c,
                               limit_value=Decimal(m.group(4)) if m else None, limit_unit="mg/kg",
                               parse_status="exact" if m else "not_numeric",
                               note=(f"sampling plan n={m.group(1)}, c={m.group(2)}, m={m.group(3)} mg/kg; "
                                     "the stored value is M (no unit may exceed it)") if m else None,
                               extra={"n": int(m.group(1)), "c": int(m.group(2)), "m": m.group(3)} if m else {})
            rows.append(last)
            return
        pl = parse_limit(limit_c, unit_hint)
        if pl.status == "compound":
            parts = split_compound(food_c, limit_c)
            if parts:
                for fname, val, loq in parts:
                    rows.append(StandardRow(**base, food_raw=fname, limit_raw=limit_c, limit_value=val,
                                            limit_unit=pl.unit, parse_status="compound_split", at_loq=loq,
                                            limit_basis=pl.basis))
                last = rows[-1]
                return
        last = StandardRow(**base, food_raw=food_c, limit_raw=limit_c, limit_value=pl.value, limit_unit=pl.unit,
                           parse_status=pl.status, at_loq=pl.at_loq, limit_basis=pl.basis, note=pl.note)
        rows.append(last)

    for pno, tables in enumerate(pages, start=1):
        for table in tables:
            for raw in table:
                cells = list(raw)
                texts = [clean_text(c) for c in cells if c]
                if not texts:
                    continue
                sec = _section_of(cells)
                if sec:
                    (section, unit), hazard, last = sec, None, None
                    continue
                if section in (None, "skip") or re.fullmatch(r"\(\d\)", texts[0] or ""):
                    continue
                if section == "metals":
                    name, food, limit = (cells + [None, None, None])[:3]
                    if name and clean_text(name):
                        hazard = _metal_name(name)
                    elif name == "" and last is not None and food and not (limit or "").strip():
                        last.food_raw = clean_text(last.food_raw + " " + food)       # wrapped over a page
                        continue
                    if hazard:
                        emit(section, hazard, food or "", limit or "", pno)
                elif section in ("crop", "nots", "other", "pesticide", "histamine"):
                    if section == "histamine":
                        # S.No | product category | applicable to (merged cell) | level
                        sno, name, food = cells[0], "Histamine", cells[1]
                        limit = cells[3] if len(cells) > 3 else None
                    else:
                        sno, name, food, limit = (cells + [None] * 4)[:4]
                    if sno and re.match(r"^\s*\d+\s*\.?\s*$", strip_amendment_marks(sno) or ""):
                        n = int(re.sub(r"\D", "", strip_amendment_marks(sno)))
                        if section == "pesticide":
                            serials.append(n)
                    if name and clean_text(name):
                        hazard = clean_text(strip_amendment_marks(name))
                    if hazard and (food or limit):
                        if (food or "").strip() and not (limit or "").strip() and last is not None \
                                and last.hazard_raw == hazard and not (name or "").strip():
                            last.food_raw = clean_text(last.food_raw + " " + food)    # wrapped food name
                            continue
                        emit(section, hazard, food or "", limit or "", pno)
                elif section in ("antibiotic_tol", "antibiotic_mrpl"):
                    sno, name, limit = (cells + [None] * 3)[:3]
                    if name and clean_text(name):
                        hazard = re.sub(r"^\([a-z]\)\s*", "", clean_text(name))
                        food = ("Sea foods incl. shrimps, prawns, fish and fishery products"
                                if section == "antibiotic_tol" else "Foods of animal origin")
                        emit(section, hazard, food, limit or "", pno)
    return rows, serials


def parse_prohibited(full_text: str) -> list[StandardRow]:
    """2.3.2(2): drugs not permitted at any stage of processing of food-producing
    animals. Read from the text between the clause and the next table."""
    m = re.search(r"\(2\)\s*Following antimicrobials and other drugs used in veterinary practices are not\s*"
                  r"permitted(.*?)(?:\(3\)|Table)", full_text, re.S)
    if not m:
        return []
    block = m.group(1)
    names = re.findall(r"^\s*(\d{1,2})\.\s*(.+?)\s*$", block, re.M)
    out = []
    for _, name in names:
        n = clean_text(strip_amendment_marks(name))
        if not n or len(n) > 120:
            continue
        out.append(StandardRow(jurisdiction="IN", standard_type="prohibited_substance", hazard_raw=n,
                               hazard_class="veterinary_drug", food_raw="Food-producing animals (any stage)",
                               limit_raw="not permitted", limit_value=None, limit_unit=None,
                               parse_status="prohibited", note="not permitted at any stage in food-producing animals",
                               legal_reference=REF["prohibited"], source_url=COMPENDIUM_URL))
    return out


def check_pesticide_sequence(serials: list[int], full_text: str) -> None:
    """Serials must run 1..N with no gap/repeat, and N must be the highest serial
    printed in the pesticide section of the text."""
    if not serials:
        raise ValueError("no pesticide rows found")
    expected = list(range(1, max(serials) + 1))
    if serials != expected:
        missing = sorted(set(expected) - set(serials))
        dup = sorted({s for s in serials if serials.count(s) > 1})
        raise ValueError(f"pesticide serials not 1..N: missing={missing[:10]} duplicated={dup[:10]}")
    sec = full_text.split("2.3.1", 1)[-1].split("2.3.2", 1)[0]
    printed = [int(x) for x in re.findall(r"^\s*(\d{1,3})\.\s+[A-Z0-9]", sec, re.M)]
    if printed and max(printed) != max(serials):
        raise ValueError(f"last printed pesticide serial {max(printed)} != parsed {max(serials)}")


def fetch_pdf(url: str = COMPENDIUM_URL) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    return data


def parse_pdf(data: bytes) -> tuple[list[StandardRow], dict]:
    import pdfplumber

    pages, texts = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for p in pdf.pages:
            pages.append([t.extract() for t in p.find_tables()])
            texts.append(p.extract_text() or "")
    full = "\n".join(texts)
    rows, serials = parse_tables(pages)
    check_pesticide_sequence(serials, full)
    rows += parse_prohibited(full)
    info = summarise(rows)
    info["pesticides"] = max(serials)
    return rows, info


def run(pdf_path: Optional[str] = None, dry_run: bool = False) -> dict:
    data = open(pdf_path, "rb").read() if pdf_path else fetch_pdf()
    rows, info = parse_pdf(data)
    logger.info("parsed %s", info)
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "IN", {"pesticide_mrl", "contaminant_ml", "vet_drug_mrl", "prohibited_substance"},
                               rows, document_title=TITLE, document_url=COMPENDIUM_URL,
                               document_version=COMPENDIUM_VERSION, document_sha256=sha256_bytes(data),
                               parser_version=PARSER_VERSION)
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(run(a.pdf, a.dry_run))


if __name__ == "__main__":
    main()
