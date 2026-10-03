"""
EU maximum levels for contaminants in food — Commission Regulation (EU)
2023/915, Annex I, read from EUR-Lex's consolidated HTML text (the version in
force, including every later amendment).

  https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02023R0915-YYYYMMDD

Annex I is a set of tables, one per contaminant: a header row ('1.2 |
Ochratoxin A | Maximum level (μg/kg) | Remarks'), optional column-label rows
(aflatoxins: 'B1 | Sum of B1, B2, G1 and G2 | M1'), then entries ('1.2.9 |
Unprocessed cereal grains | 5,0 | remark'). The parser keeps every entry's
printed food text and number, one row per (entry, value column):
  * EU number format: decimal comma ('5,0'), space as thousands separator ('1 250');
  * a value printed with a dated replacement ('100 50 as from 1 July 2024') takes
    the later value once that date has passed, and keeps both in the note;
  * an entry with no number (a group heading such as '1.2.1 Dried fruits') is
    not a limit and is skipped; its text becomes context for its children.
The latest consolidated version is discovered from the Publications Office's
SPARQL endpoint (highest 02023R0915-YYYYMMDD) and fetched from CELLAR by content
negotiation, so amendments arrive without a code change. (The EUR-Lex web pages
answer scripts with a bot challenge; CELLAR serves the identical text.)

-> food_standards (jurisdiction 'EU', contaminant_ml)

Run: python -m pipeline.sources.standards_eu_contaminants [--dry-run] [--html local.html]
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pipeline.sources.standards_common import StandardRow, replace_snapshot, sha256_bytes, summarise

logger = logging.getLogger("foodsafe.standards_eu_contaminants")

TXT_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}"    # human-facing source link
CELLAR_URL = "http://publications.europa.eu/resource/celex/{celex}"                    # machine fetch (same text)
SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
SPARQL_LATEST = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT ?celex WHERE { "
                 "?w cdm:resource_legal_id_celex ?celex . FILTER(STRSTARTS(STR(?celex), '02023R0915')) }")
USER_AGENT = "Mozilla/5.0 (FoodSafe-India public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
PARSER_VERSION = "eu-2023-915-1"

# Annex I section code -> (hazard name, hazard class). Multi-column tables are
# split by their column labels (COLUMN_HAZARDS).
SECTIONS = {
    "1.1": ("Aflatoxins", "mycotoxin"), "1.2": ("Ochratoxin A", "mycotoxin"), "1.3": ("Patulin", "mycotoxin"),
    "1.4": ("Deoxynivalenol", "mycotoxin"), "1.5": ("Zearalenone", "mycotoxin"), "1.6": ("Fumonisins", "mycotoxin"),
    "1.7": ("Citrinin", "mycotoxin"), "1.8": ("Ergot", "mycotoxin"), "1.9": ("T-2 and HT-2 toxins", "mycotoxin"),
    "2.1": ("Erucic acid", "natural_toxin"), "2.2": ("Tropane alkaloids", "natural_toxin"),
    "2.3": ("Hydrocyanic acid", "natural_toxin"), "2.4": ("Pyrrolizidine alkaloids", "natural_toxin"),
    "2.5": ("Opium alkaloids", "natural_toxin"), "2.6": ("Delta-9-tetrahydrocannabinol", "natural_toxin"),
    "3.1": ("Lead", "heavy_metal"), "3.2": ("Cadmium", "heavy_metal"), "3.3": ("Mercury", "heavy_metal"),
    "3.4": ("Arsenic (inorganic)", "heavy_metal"), "3.5": ("Tin (inorganic)", "heavy_metal"),
    "3.6": ("Nickel", "heavy_metal"),
    "4.1": ("Dioxins and PCBs", "environmental_pollutant"), "4.2": ("Perfluoroalkyl substances",
                                                                     "environmental_pollutant"),
    "5.1": ("Polycyclic aromatic hydrocarbons", "process_contaminant"), "5.2": ("3-MCPD", "process_contaminant"),
    "5.3": ("3-MCPD and 3-MCPD fatty acid esters", "process_contaminant"),
    "5.4": ("Glycidyl fatty acid esters", "process_contaminant"), "5.5": ("Acrylamide", "process_contaminant"),
    "6.1": ("Nitrate", "other"), "6.2": ("Melamine", "other"), "6.3": ("Perchlorate", "other"),
}
COLUMN_HAZARDS = [   # (regex on the column label, hazard name used for the row)
    (re.compile(r"^B\s*1$", re.I), "Aflatoxin B1"),
    (re.compile(r"^Sum of B\s*1\s*,\s*B\s*2\s*,\s*G\s*1\s*and\s*G\s*2", re.I), "Aflatoxins (total)"),
    (re.compile(r"^M\s*1$", re.I), "Aflatoxin M1"),
    (re.compile(r"^Benzo\s*\(a\)\s*pyrene", re.I), "Benzo(a)pyrene"),
    (re.compile(r"^Sum of benzo\s*\(a\)\s*pyrene", re.I), "PAH4 (sum of benzo(a)pyrene, benz(a)anthracene, "
                                                        "benzo(b)fluoranthene and chrysene)"),
]


def _txt(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _cells(row_html: str) -> list[str]:
    return [_txt(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def eu_number(s: str) -> Optional[Decimal]:
    """'5,0' -> 5.0, '1 250' -> 1250, '0,050' -> 0.05. Anything else -> None."""
    t = (s or "").strip()
    if not re.fullmatch(r"\d{1,3}(?: \d{3})*(?:,\d+)?|\d+(?:,\d+)?", t):
        return None
    try:
        return Decimal(t.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


_DATED = re.compile(r"^(\S+(?: \d{3})*)\s+(\S+(?: \d{3})*)\s+as from\s+(\d{1,2} \w+ \d{4})$")


def eu_value(cell: str, today: Optional[date] = None) -> tuple[Optional[Decimal], Optional[str]]:
    """A value cell -> (value in force, note). '100 50 as from 1 July 2024' ->
    (50, '100 until 1 July 2024') once that date has passed."""
    t = (cell or "").strip()
    v = eu_number(t)
    if v is not None:
        return v, None
    m = _DATED.match(t)
    if m:
        try:
            when = datetime.strptime(m.group(3), "%d %B %Y").date()
        except ValueError:
            return None, None
        old, new = eu_number(m.group(1)), eu_number(m.group(2))
        if old is None or new is None:
            return None, None
        if (today or date.today()) >= when:
            return new, f"{m.group(1)} until {m.group(3)}"
        return old, f"{m.group(2)} applies from {m.group(3)}"
    return None, None


def _unit(label: str) -> Optional[str]:
    m = re.search(r"\((μg|µg|mg|g|ng)/kg[^)]*\)", label)
    if not m:
        return None
    return {"μg": "µg/kg", "µg": "µg/kg", "mg": "mg/kg", "g": "g/kg", "ng": "ng/kg"}[m.group(1)]


def parse_annex(doc_html: str, source_url: str, legal_ref: str, today: Optional[date] = None) -> list[StandardRow]:
    rows: list[StandardRow] = []
    for table in re.findall(r"<table[^>]*>.*?</table>", doc_html, re.S):
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
        section = hazard_name = hazard_class = unit = None
        value_labels: list[str] = []
        parents: dict[str, str] = {}
        for tr in trs:
            c = _cells(tr)
            if not c or not any(c):
                continue
            code = c[0]
            label_cells = [x for x in c[2:] if x]
            # header: '1.2 | Ochratoxin A | Maximum level (μg/kg) | Remarks'
            if re.fullmatch(r"\d\.\d{1,2}", code) and len(c) >= 3 and "Maximum level" in (c[2] if len(c) > 2 else ""):
                section = code
                hazard_name, hazard_class = SECTIONS.get(code, (c[1], "other"))
                unit = _unit(c[2])
                value_labels = []
                parents = {}
                continue
            if re.fullmatch(r"\d\.\d{1,2}\.\d{1,2}", code) and len(c) >= 3 and "Maximum level" in c[2]:
                # sub-section header inside a table (e.g. '1.8.1 | Ergot sclerotia | Maximum level (g/kg)')
                hazard_name, unit, value_labels = c[1], _unit(c[2]), []
                continue
            if section is None:
                continue
            if code == "" and len(c) >= 3 and c[1] == "":
                # column labels for multi-value tables; ignore pure remark rows
                labs = [x for x in c[2:]]
                if any(rx.match(l) for l in labs for rx, _ in COLUMN_HAZARDS):
                    value_labels = labs
                continue
            if not re.fullmatch(r"\d\.\d{1,2}(?:\.\d{1,2}){1,3}", code) or len(c) < 3:
                continue
            food = c[1]
            parent_code = code.rsplit(".", 1)[0]
            context = parents.get(parent_code)
            if context and food[:1].islower():
                # '3.2.17.1 placed on the market as powder ...' continues its parent's text
                food = f"{context} — {food}"
            values = c[2:]
            if value_labels:
                pairs = [(values[i], value_labels[i]) for i in range(min(len(values), len(value_labels)))]
            else:
                pairs = [(values[0], None)]
            numeric_any = False
            for raw, lab in pairs:
                v, note = eu_value(raw, today)
                if v is None:
                    continue
                numeric_any = True
                hname = hazard_name
                if lab:
                    for rx, nm in COLUMN_HAZARDS:
                        if rx.match(lab):
                            hname = nm
                            break
                    else:
                        hname = f"{hazard_name} ({lab})"
                remark = values[len(pairs)] if len(values) > len(pairs) else ""
                rows.append(StandardRow(
                    jurisdiction="EU", standard_type="contaminant_ml", hazard_raw=hname, hazard_class=hazard_class,
                    food_raw=food, food_code=code, limit_raw=raw, limit_value=v, limit_unit=unit,
                    parse_status="exact",
                    note="; ".join(x for x in (note, f"under: {context}" if context else None,
                                               remark[:400] if remark else None) if x) or None,
                    legal_reference=f"{legal_ref}, Annex I, entry {code}", source_url=source_url,
                    extra={"section": section},
                ))
            if not numeric_any:
                parents[code] = food
    return rows


def _fetch(url: str, accept: str = "text/html") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                               "Accept-Language": "eng"})
    with urllib.request.urlopen(req, timeout=180) as r:
        if r.status != 200:
            raise RuntimeError(f"{url}: HTTP {r.status}")
        return r.read()


def latest_celex() -> str:
    """Highest consolidated version, from the Publications Office's SPARQL endpoint
    (CELLAR). The EUR-Lex web pages sit behind a bot challenge (HTTP 202 with an
    empty body) that a scheduled job cannot pass; CELLAR is the machine interface
    to the same documents."""
    q = urllib.parse.urlencode({"query": SPARQL_LATEST})
    data = json.loads(_fetch(f"{SPARQL_URL}?{q}", "application/sparql-results+json"))
    versions = sorted(b["celex"]["value"] for b in data["results"]["bindings"]
                      if re.fullmatch(r"02023R0915-\d{8}", b["celex"]["value"]))
    if not versions:
        raise RuntimeError("no consolidated version of Regulation (EU) 2023/915 listed in CELLAR")
    return versions[-1]


def run(dry_run: bool = False, html_path: Optional[str] = None) -> dict:
    celex = "local" if html_path else latest_celex()
    url = TXT_URL.format(celex=celex) if not html_path else "local file"
    data = open(html_path, "rb").read() if html_path else _fetch(CELLAR_URL.format(celex=celex),
                                                                   "application/xhtml+xml")
    doc = data.decode("utf-8", "replace")
    ref = f"Regulation (EU) 2023/915 (consolidated {celex[-8:] if celex != 'local' else 'local copy'})"
    rows = parse_annex(doc, url, ref)
    info = {**summarise(rows), "celex": celex}
    if len(rows) < 300:
        raise RuntimeError(f"only {len(rows)} EU contaminant limits parsed (expected 400+); refusing to load")
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "EU", {"contaminant_ml"}, rows,
                               document_title="Commission Regulation (EU) 2023/915 — maximum levels for contaminants "
                                              "(consolidated)", document_url=url, document_version=celex,
                               document_sha256=sha256_bytes(data), parser_version=PARSER_VERSION)
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--html")
    a = ap.parse_args()
    print(run(a.dry_run, a.html))


if __name__ == "__main__":
    main()
