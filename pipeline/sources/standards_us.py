"""
US legal pesticide limits: EPA tolerances in 40 CFR Part 180, Subpart C
("Specific Tolerances"), read from the official eCFR versioner API (Office of the
Federal Register / GPO; no key) as XML.

  https://www.ecfr.gov/api/versioner/v1/full/{date}/title-40.xml?part=180

Each section '§ 180.342 Chlorpyrifos; tolerances for residues.' holds tables of
(commodity, parts per million) under lettered paragraphs:
  (a) General                              -> loaded (applicability 'General')
  (b) Section 18 emergency exemptions      -> loaded, flagged 'Time-limited (section 18)'
  (c) Tolerances with regional registrations -> loaded ('Regional registration')
  (d) Indirect or inadvertent residues     -> loaded ('Indirect or inadvertent')
Only sections whose heading says 'tolerances for residues' are read; Subpart D
(exemptions from the requirement of a tolerance) carries no numeric limit.

US convention: no tolerance = no legal residue (a residue on a food without a
tolerance makes the food adulterated) — so an absent US row is the strictest
possible limit, not a missing value. Comparisons must say so.

-> food_standards (jurisdiction 'US', pesticide_mrl; ppm stored as mg/kg)

Run: python -m pipeline.sources.standards_us [--dry-run] [--xml local.xml]
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Optional

from pipeline.sources.standards_common import StandardRow, clean_text, replace_snapshot, sha256_bytes, summarise

logger = logging.getLogger("foodsafe.standards_us")

TITLES_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"
PART_URL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-40.xml?part=180"
SECTION_URL = "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-E/part-180/section-{sec}"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
PARSER_VERSION = "ecfr-40cfr180-1"

PARAGRAPHS = {
    "a": "General",
    "b": "Time-limited (section 18 emergency exemption)",
    "c": "Regional registration",
    "d": "Indirect or inadvertent residues",
}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
    return data


def current_date() -> str:
    titles = json.loads(_fetch(TITLES_URL))
    for t in titles["titles"]:
        if int(t["number"]) == 40:
            return t["up_to_date_as_of"]
    raise RuntimeError("title 40 not listed by the eCFR API")


def _text(el) -> str:
    """Element text with footnote markers (<SU>1</SU>) dropped."""
    parts = []

    def walk(e):
        if e.tag in ("SU", "FTREF", "sup", "SUP"):
            if e.tail:
                parts.append(e.tail)
            return
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
        if e.tail and e is not el:
            parts.append(e.tail)

    walk(el)
    return clean_text(html.unescape("".join(parts)))


_SEC_HEAD = re.compile(r"§\s*(180\.\d+)\s+(.+?);\s*tolerances? for residues", re.I)


def _dec(s: str) -> Optional[Decimal]:
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return v if v.is_finite() and v >= 0 else None


def parse_part(xml_bytes: bytes) -> list[StandardRow]:
    root = ET.fromstring(xml_bytes)
    rows: list[StandardRow] = []
    for sec in root.iter("DIV8"):
        head_el = sec.find("HEAD")
        head = _text(head_el) if head_el is not None else ""
        m = _SEC_HEAD.search(head)
        if not m:
            continue
        sec_no, chem = m.group(1), clean_text(m.group(2))
        para = None
        for child in sec:
            if child.tag == "P":
                pm = re.match(r"^\(([a-d])\)", _text(child))
                if pm:
                    para = pm.group(1)
            tables = [child] if child.tag == "TABLE" else list(child.iter("TABLE"))
            for tb in tables:
                header = [_text(th).lower() for th in tb.iter("TH")]
                if not any("parts per million" in h or "ppm" in h for h in header):
                    continue
                for tr in tb.iter("TR"):
                    tds = tr.findall("TD")
                    if len(tds) < 2:
                        continue
                    commodity, ppm_raw = _text(tds[0]), _text(tds[1])
                    if not commodity:
                        continue
                    num = re.sub(r"\s*\(N\)$", "", ppm_raw)      # (N) = negligible residue tolerance
                    # unambiguous typographic variants in the official text: '.5', '6. 0',
                    # '0.01 ppm', US thousands separator '1,000'
                    num = re.sub(r"\s*ppm$", "", num)
                    num = re.sub(r"^\.(\d)", r"0.\1", num)
                    num = re.sub(r"^(\d+)\.\s+(\d+)$", r"\1.\2", num)
                    num = re.sub(r"^(\d{1,3}),(\d{3})$", r"\1\2", num)
                    value = _dec(num) if re.fullmatch(r"\d+(?:\.\d+)?", num) else None
                    expires = _text(tds[2]) if len(tds) > 2 else None
                    rows.append(StandardRow(
                        jurisdiction="US", standard_type="pesticide_mrl", hazard_raw=chem, hazard_class="pesticide",
                        food_raw=commodity, limit_raw=ppm_raw, limit_value=value, limit_unit="mg/kg",
                        parse_status="exact" if value is not None else "not_numeric",
                        applicability=PARAGRAPHS.get(para or "a", "General"),
                        note="; ".join(x for x in (
                            "(N): negligible residue tolerance" if num != ppm_raw else "",
                            f"expiration/revocation date: {expires}" if expires else "") if x) or None,
                        legal_reference=f"40 CFR {sec_no}({para or 'a'})",
                        source_url=SECTION_URL.format(sec=sec_no),
                        extra={"section": sec_no, "paragraph": para},
                    ))
    return rows


def run(dry_run: bool = False, xml_path: Optional[str] = None) -> dict:
    date = current_date() if not xml_path else "local"
    data = open(xml_path, "rb").read() if xml_path else _fetch(PART_URL.format(date=date))
    rows = parse_part(data)
    info = summarise(rows)
    info["ecfr_date"] = date
    info["sections"] = len({r.extra["section"] for r in rows})
    if info["sections"] < 300:
        raise RuntimeError(f"only {info['sections']} tolerance sections parsed — expected 300+; refusing to load")
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "US", {"pesticide_mrl"}, rows,
                               document_title="40 CFR Part 180 Subpart C — tolerances for pesticide chemicals in food",
                               document_url=PART_URL.format(date=date), document_version=date,
                               document_sha256=sha256_bytes(data), parser_version=PARSER_VERSION)
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--xml")
    a = ap.parse_args()
    print(run(a.dry_run, a.xml))


if __name__ == "__main__":
    main()
