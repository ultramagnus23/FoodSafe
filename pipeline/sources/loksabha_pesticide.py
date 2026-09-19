"""
Lok Sabha written answers -> pesticide-residue monitoring results (MPRNL).

The Ministry of Agriculture's "Monitoring of Pesticide Residues at National
Level" (MPRNL) scheme tests food commodities and reports how many samples were
above the FSSAI Maximum Residue Limit (MRL). Parliament is where those counts
have leaked out, in three shapes, all handled here:

  A. table   commodity rows x period column pairs (samples analysed / above MRL)
             e.g. LS16 Q3401 (11 commodities, FY 2014-15, 2015-16, Apr-Jul 2016)
  B. text    one block per commodity, one row per fiscal year, then a printed
             total   e.g. LS16 Q1312 ("Details of vegetable samples analysed
             under MPRNL (2012-18)"), LS16 Q127 ("Annexure II")
  C. prose   "During 2018-19; 29,410 samples ... 863 (2.93 %) ... above MRL"
             (national, all commodities)

This is REAL contamination data with a pass side (analysed - above MRL), unlike
the enforcement records FSSAI holds back. It is a national, commodity x year
grain: no state, district, brand or product.

Same discipline as loksabha_sampling.py: a block is accepted only if every
check passes, otherwise it is rejected whole with a logged reason —
  * every count is one clean integer and above_MRL <= analysed;
  * where the source prints a percentage it must match above/analysed to within
    one unit of its last printed digit (sources both round and truncate);
  * A and B require a printed Total/Grand Total equal to the sum of the rows
    (a missing or misread row fails it) — tier 'total_row_sum';
  * C has only the sentence, so the percentage check is its whole support —
    tier 'pct_consistent', the weaker tier, shown as such.
The same (commodity, period) is often disclosed in several answers at different
vintages (e.g. 2013-14 vegetables above MRL: 221 in a 2015 answer, 192 in a 2018
answer). All are kept with their source; none is merged.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from pipeline.config import pg_connect
from pipeline.sources import loksabha_qa as LQ
from pipeline.sources.loksabha_sampling import Reject, normalise_fy, parse_int_cell

logger = logging.getLogger("foodsafe.loksabha_pesticide")

PARSER_VERSION = "pesticide-1"

# 15th Lok Sabha search results carry no PDF URL, so only 16-18 are reachable.
PESTICIDE_TERMS: tuple[int, ...] = (18, 17, 16)

PESTICIDE_KEYWORDS = [
    "MPRNL",
    "Monitoring of Pesticide Residues at National Level",
    "pesticide residues",
    "pesticide residue",
    "banned pesticides",
    "maximum residue limit",
    "pesticides in vegetables",
]

_MINISTRY_PREFIXES = ("AGRICULTURE", "HEALTH AND FAMILY WELFARE", "CHEMICALS AND FERTILIZERS")

# What a PDF must mention before it is worth parsing at all.
_RELEVANT_RE = re.compile(r"MPRNL|pesticide\s*residue|Maximum\s*Residue", re.I)

# Printed label -> stable key. 'meat' (a 4-commodity block) and 'meat_egg' (an
# 11-commodity table) are kept apart: the labels differ, so scope is not assumed.
_COMMODITY_KEYS = {
    "vegetable": "vegetables", "vegetables": "vegetables",
    "fruit": "fruits", "fruits": "fruits",
    "meat": "meat", "meategg": "meat_egg",
    "spice": "spices", "spices": "spices",
    "fishmarine": "fish_marine", "milk": "milk", "pulses": "pulses", "rice": "rice",
    "tea": "tea", "water": "water", "wheat": "wheat",
}

MAX_COUNT = 1_000_000_000


@dataclass
class Block:
    """One accepted block of rows."""
    shape: str                              # 'table' | 'text_block' | 'sentence'
    page: int
    verification: str                       # 'total_row_sum' | 'pct_consistent'
    rows: list[dict] = field(default_factory=list)
    # {commodity, label, period_label, fiscal_year|None, period_kind, analysed, above, pct|None}


# ---------------------------------------------------------------- helpers

def _key(label: str) -> Optional[str]:
    return _COMMODITY_KEYS.get(re.sub(r"[^a-z]", "", (label or "").lower()))


def _flat(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def _count(s: str) -> Optional[int]:
    v, status = parse_int_cell(s)
    return v if status == "ok" else None


_PCT_RE = r"\(\s*([\d.]+)\s*%?\s*\)?"
_COUNT_PCT_RE = re.compile(rf"^([\d,\s]*\d)(?:\s*{_PCT_RE})?\s*$")


def _count_and_pct(cell: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """'542 (2.6 %)' -> (542, '2.6'); '306' -> (306, None); junk -> (None, None)."""
    m = _COUNT_PCT_RE.match(_flat(cell))
    if not m:
        return None, None
    return _count(m.group(1).strip()), m.group(2)


def pct_consistent(above: int, analysed: int, printed: Optional[str]) -> bool:
    """True if the printed percentage is within one unit of its last printed
    digit of above/analysed (or if none was printed). One unit, not half: the
    answers both round and truncate (98/6336 = 1.5467 is printed 1.54 in one
    and 2.9343 as 2.93 in another). Counts are guarded separately by the printed
    totals; this catches a misread digit in a percentage-bearing cell."""
    if printed is None:
        return True
    if analysed <= 0:
        return False
    decimals = len(printed.split(".")[1]) if "." in printed else 0
    tol = 10 ** (-decimals) + 1e-9
    return abs(100.0 * above / analysed - float(printed)) <= tol


def parse_table_period(header: str) -> Optional[dict]:
    """'April, 2014- March, 15' -> full fiscal year; 'April, 2016- July, 2016' ->
    part year. Anything else -> None (the table is rejected)."""
    h = re.sub(r"[^a-z0-9]", "", (header or "").lower())
    m = re.fullmatch(r"april(\d{4})march(\d{2}|\d{4})", h)
    if m:
        fy = normalise_fy(m.group(1), m.group(2))
        if fy:
            return {"period_label": fy[:4] + "-" + fy[7:], "fiscal_year": fy, "period_kind": "fiscal_year"}
    m = re.fullmatch(r"(april)(\d{4})(july|june|may|august|september|october|november|december|january|february)(\d{4})", h)
    if m:
        label = f"{m.group(1)[:3].title()} {m.group(2)}-{m.group(3)[:3].title()} {m.group(4)}"
        return {"period_label": label, "fiscal_year": None, "period_kind": "partial_year"}
    return None


# ---------------------------------------------------------------- shape A: tables

def parse_commodity_table(rows: list[list], page: int) -> tuple[Optional[Block], Optional[Reject]]:
    """Commodity rows x (analysed, above MRL) column pairs, one pair per period."""
    if len(rows) < 4:
        return None, None
    first = [_flat(c) for c in rows[0]]
    if not first or re.sub(r"[^a-z]", "", first[0].lower()) != "commodity":
        return None, None
    periods = []
    for c, cell in enumerate(first):
        if c == 0 or not cell:
            continue
        p = parse_table_period(cell)
        if p is None:
            return None, Reject(page, "table_period_unreadable", cell[:60])
        periods.append((c, p))
    if not periods:
        return None, Reject(page, "table_no_periods")
    if len({p["period_label"] for _, p in periods}) != len(periods):
        return None, Reject(page, "table_duplicate_periods")
    sub = [_flat(c).lower() for c in rows[1]]
    for c, _ in periods:
        if c + 1 >= len(sub) or "analys" not in sub[c] or ("above" not in sub[c + 1] and "mrl" not in sub[c + 1]):
            return None, Reject(page, "table_subheader_mismatch", " | ".join(sub)[:80])

    out: list[dict] = []
    total_cells: Optional[list] = None
    for r in rows[2:]:
        label = _flat(r[0]) if r else ""
        if not label:
            continue
        if re.sub(r"[^a-z]", "", label.lower()) == "total":
            total_cells = r
            break
        commodity = _key(label)
        if commodity is None:
            return None, Reject(page, "unrecognised_commodity", label[:40])
        for c, p in periods:
            analysed, _ = _count_and_pct(r[c] if c < len(r) else None)
            above, pct = _count_and_pct(r[c + 1] if c + 1 < len(r) else None)
            if analysed is None or above is None:
                return None, Reject(page, "malformed_number", f"{label} / {p['period_label']}")
            if above > analysed:
                return None, Reject(page, "above_exceeds_analysed", f"{label} / {p['period_label']}")
            if not pct_consistent(above, analysed, pct):
                return None, Reject(page, "percent_mismatch", f"{label} / {p['period_label']}")
            out.append({"commodity": commodity, "label": label, "analysed": analysed, "above": above, "pct": pct, **p})
    if total_cells is None:
        return None, Reject(page, "table_no_total")
    if len({o["commodity"] for o in out}) < 2:
        return None, Reject(page, "table_too_few_commodities")
    for c, p in periods:
        analysed, _ = _count_and_pct(total_cells[c] if c < len(total_cells) else None)
        above, pct = _count_and_pct(total_cells[c + 1] if c + 1 < len(total_cells) else None)
        mine = [o for o in out if o["period_label"] == p["period_label"]]
        if analysed is None or above is None:
            return None, Reject(page, "total_unusable", p["period_label"])
        if (sum(o["analysed"] for o in mine), sum(o["above"] for o in mine)) != (analysed, above):
            return None, Reject(page, "total_mismatch", p["period_label"])
        if not pct_consistent(above, analysed, pct):
            return None, Reject(page, "percent_mismatch", f"Total / {p['period_label']}")
    return Block("table", page, "total_row_sum", out), None


# ---------------------------------------------------------------- shape B: per-commodity text blocks

_BLOCK_TITLE_RE = re.compile(r"^Details of\s+(\w+)\s+samples analy[sz]ed under MPRNL", re.I)
_BARE_TITLE_RE = re.compile(r"^(Fruits|Vegetables|Meat|Spices)\s*$", re.I)
_YEAR_ROW_RE = re.compile(
    r"^(?:\d+\.\s+)?(\d{4})\s*-\s*(\d{2,4})\s+([\d,]+)\s+([\d,]+)(?:\s*\(\s*([\d.]+)\s*%\s*\)|\s+([\d.]+))?\s*$"
)
_TOTAL_ROW_RE = re.compile(
    r"^(?:Grand\s+)?Total:?\s+([\d,]+)\s+([\d,]+)(?:\s*\(\s*([\d.]+)\s*%\s*\)|\s+([\d.]+))?\s*$", re.I
)


def parse_text_blocks(text: str, page: int = 0) -> tuple[list[Block], list[Reject]]:
    """Per-commodity year tables in running text. A block ends at its printed
    total and is accepted only if the year rows sum to it."""
    blocks: list[Block] = []
    rejects: list[Reject] = []
    lines = [_flat(l) for l in text.splitlines()]
    i = 0
    while i < len(lines):
        m = _BLOCK_TITLE_RE.match(lines[i])
        title = m.group(1) if m else None
        if not m:
            m2 = _BARE_TITLE_RE.match(lines[i])
            # A bare commodity word only starts a block if a header line follows.
            if m2 and i + 1 < len(lines) and re.match(r"^S\.?\s*No", lines[i + 1], re.I):
                title = m2.group(1)
        if title is None:
            i += 1
            continue
        commodity = _key(title)
        i += 1
        rows: list[dict] = []
        total: Optional[tuple[int, int, Optional[str]]] = None
        bad: Optional[Reject] = None
        while i < len(lines):
            line = lines[i]
            if _BLOCK_TITLE_RE.match(line) or (_BARE_TITLE_RE.match(line) and i + 1 < len(lines)
                                                and re.match(r"^S\.?\s*No", lines[i + 1], re.I)):
                break
            ym = _YEAR_ROW_RE.match(line)
            if ym:
                fy = normalise_fy(ym.group(1), ym.group(2))
                analysed, above = _count(ym.group(3)), _count(ym.group(4))
                pct = ym.group(5) or ym.group(6)
                if fy is None or analysed is None or above is None:
                    bad = Reject(page, "malformed_row", line[:60])
                elif above > analysed:
                    bad = Reject(page, "above_exceeds_analysed", line[:60])
                elif not pct_consistent(above, analysed, pct):
                    bad = Reject(page, "percent_mismatch", line[:60])
                else:
                    rows.append({"commodity": commodity, "label": title, "analysed": analysed, "above": above,
                                 "pct": pct, "period_label": fy[:4] + "-" + fy[7:], "fiscal_year": fy,
                                 "period_kind": "fiscal_year"})
                i += 1
                if bad:
                    break
                continue
            tm = _TOTAL_ROW_RE.match(line)
            if tm:
                total = (_count(tm.group(1)), _count(tm.group(2)), tm.group(3) or tm.group(4))
                i += 1
                break
            i += 1
        if commodity is None:
            rejects.append(Reject(page, "unrecognised_commodity", title))
        elif bad:
            rejects.append(bad)
        elif not rows:
            rejects.append(Reject(page, "block_no_rows", title))
        elif total is None or total[0] is None or total[1] is None:
            rejects.append(Reject(page, "block_no_total", title))
        elif (sum(r["analysed"] for r in rows), sum(r["above"] for r in rows)) != (total[0], total[1]):
            rejects.append(Reject(page, "total_mismatch", title))
        elif not pct_consistent(total[1], total[0], total[2]):
            rejects.append(Reject(page, "percent_mismatch", f"{title} total"))
        elif len({r["period_label"] for r in rows}) != len(rows):
            rejects.append(Reject(page, "duplicate_period", title))
        else:
            blocks.append(Block("text_block", page, "total_row_sum", rows))
    return blocks, rejects


# ---------------------------------------------------------------- shape C: prose

_SENTENCE_RE = re.compile(
    r"During\s+(\d{4})\s*-\s*(\d{2,4})\s*[;,:]?\s*(?:a\s+total\s+of\s+)?([\d,]+)\s+samples\b[^.]{0,120}?"
    r"analy[sz]ed[^.]{0,80}?\b([\d,]+)\s*\(\s*([\d.]+)\s*%\s*\)\s*samples\b[^.]{0,60}?(?:above|exceeding)",
    re.I,
)


def parse_sentences(text: str, page: int = 0) -> tuple[list[Block], list[Reject]]:
    """National all-commodity totals quoted in prose. Only the percentage check
    supports these, so they are the weakest tier."""
    flat = re.sub(r"\s+", " ", text)
    blocks, rejects, seen = [], [], set()
    for m in _SENTENCE_RE.finditer(flat):
        start, end = m.group(1), m.group(2)
        end_year = int(end) + (int(start) // 100) * 100 if len(end) == 2 else int(end)
        span = end_year - int(start)
        analysed, above, pct = _count(m.group(3)), _count(m.group(4)), m.group(5)
        if analysed is None or above is None or span < 1 or span > 10:
            rejects.append(Reject(page, "sentence_malformed", m.group(0)[:70]))
            continue
        if above > analysed or not pct_consistent(above, analysed, pct):
            rejects.append(Reject(page, "sentence_inconsistent", m.group(0)[:70]))
            continue
        if span == 1:
            fy = f"{start}-{end_year}"
            period = {"period_label": f"{start}-{str(end_year)[2:]}", "fiscal_year": fy, "period_kind": "fiscal_year"}
        else:
            period = {"period_label": f"{start}-{str(end_year)[2:]}", "fiscal_year": None, "period_kind": "multi_year_pool"}
        if period["period_label"] in seen:
            continue
        seen.add(period["period_label"])
        blocks.append(Block("sentence", page, "pct_consistent",
                            [{"commodity": "all_commodities", "label": "all commodities", "analysed": analysed,
                              "above": above, "pct": pct, **period}]))
    return blocks, rejects


# ---------------------------------------------------------------- whole document

def parse_document(pages: list[dict]) -> tuple[list[Block], list[Reject]]:
    """pages: [{'page': n, 'text': str, 'tables': [rows, ...]}]"""
    blocks: list[Block] = []
    rejects: list[Reject] = []
    for pg in pages:
        for rows in pg["tables"]:
            b, r = parse_commodity_table(rows, pg["page"])
            if b:
                blocks.append(b)
            if r:
                rejects.append(r)
    # Text blocks can straddle a page break, so parse the joined text once.
    full = "\n".join(pg["text"] for pg in pages)
    tb, tr = parse_text_blocks(full)
    blocks += tb
    rejects += tr
    sb, sr = parse_sentences(full)
    blocks += sb
    rejects += sr
    # Two blocks giving DIFFERENT figures for the same (commodity, period) within
    # ONE answer are ambiguous — reject both rather than choose. Identical figures
    # repeated (a table and its prose summary) are harmless.
    seen: dict[tuple[str, str], list[tuple[Block, tuple[int, int]]]] = {}
    for b in blocks:
        for r in b.rows:
            seen.setdefault((r["commodity"], r["period_label"]), []).append((b, (r["analysed"], r["above"])))
    clash = {id(b) for entries in seen.values() if len({v for _, v in entries}) > 1 for b, _ in entries}
    if clash:
        rejects.append(Reject(0, "same_period_twice_in_one_answer", f"{len(clash)} blocks disagree"))
        blocks = [b for b in blocks if id(b) not in clash]
    return blocks, rejects


def read_pdf(pdf_bytes: bytes) -> list[dict]:
    import pdfplumber
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            pages.append({"page": i, "text": pg.extract_text() or "", "tables": pg.extract_tables() or []})
    return pages


def is_relevant(pages: list[dict]) -> bool:
    return bool(_RELEVANT_RE.search("\n".join(p["text"] for p in pages)))


# ---------------------------------------------------------------- discovery

def discover(terms: tuple[int, ...] | None = None) -> list[dict]:
    """Raises loksabha_qa.SearchUnavailable if every search failed."""
    found, errors, attempts = LQ.discover(
        tuple(terms or PESTICIDE_TERMS), PESTICIDE_KEYWORDS,
        lambda q: (q.get("ministry") or "").strip().upper().startswith(_MINISTRY_PREFIXES),
    )
    LQ.raise_if_unavailable(errors, attempts)
    return found


# ---------------------------------------------------------------- database
# The question log is shared with loksabha_sampling (schema_migration_019); the
# parser_version column keeps the two parsers' entries apart.

def processed_keys(conn) -> set[tuple[int, int]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lok_sabha_no, source_question_no FROM loksabha_question_log "
            "WHERE parser_version = %s AND status <> 'fetch_error'",
            (PARSER_VERSION,),
        )
        return {(r[0], r[1]) for r in cur.fetchall()}


def record_question(conn, question: dict, status: str, blocks: list[Block], rejects: list[Reject]) -> None:
    detail = [{"page": r.page, "reason": r.reason, "detail": r.detail} for r in rejects]
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO loksabha_question_log
                 (lok_sabha_no, source_question_no, parser_version, status, groups_accepted, groups_rejected,
                  reject_detail, source_url, processed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
               ON CONFLICT (lok_sabha_no, source_question_no, parser_version) DO UPDATE SET
                 status = EXCLUDED.status, groups_accepted = EXCLUDED.groups_accepted,
                 groups_rejected = EXCLUDED.groups_rejected, reject_detail = EXCLUDED.reject_detail,
                 source_url = EXCLUDED.source_url, processed_at = NOW()""",
            (int(question["lokNo"]), int(question["quesNo"]), PARSER_VERSION, status,
             len(blocks), len(rejects), json.dumps(detail), question.get("questionsFilePath")),
        )
    conn.commit()


def ingest_blocks(conn, question: dict, blocks: list[Block]) -> int:
    """Replace this question's rows with what the current parse accepted (delete
    and insert share one transaction, so a stricter parser never leaves its
    predecessor's rows behind)."""
    n = 0
    answered = LQ._parse_date(question.get("date", ""))
    subject = (question.get("subjects") or "").strip()
    lok, qno = int(question["lokNo"]), int(question["quesNo"])
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pesticide_residue_annual WHERE lok_sabha_no = %s AND source_question_no = %s",
                    (lok, qno))
        for b in blocks:
            for r in b.rows:
                cur.execute(
                    """INSERT INTO pesticide_residue_annual
                         (commodity, commodity_label, period_label, fiscal_year, period_kind,
                          samples_analyzed, samples_above_mrl, printed_pct, verification, shape,
                          lok_sabha_no, source_question_no, source_question_subject, answered_date,
                          source_url, parser_version, fetched_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                       ON CONFLICT (commodity, period_label, lok_sabha_no, source_question_no)
                       DO UPDATE SET samples_analyzed = EXCLUDED.samples_analyzed,
                                     samples_above_mrl = EXCLUDED.samples_above_mrl,
                                     printed_pct = EXCLUDED.printed_pct, verification = EXCLUDED.verification,
                                     shape = EXCLUDED.shape, parser_version = EXCLUDED.parser_version,
                                     fetched_at = NOW()""",
                    (r["commodity"], r["label"], r["period_label"], r["fiscal_year"], r["period_kind"],
                     r["analysed"], r["above"], r["pct"], b.verification, b.shape,
                     lok, qno, subject, answered, question["questionsFilePath"], PARSER_VERSION),
                )
                n += 1
    conn.commit()
    return n


def run(terms: tuple[int, ...] | None = None) -> dict:
    summary = {"questions_found": 0, "questions_processed": 0, "questions_skipped_already_done": 0,
               "blocks_accepted": 0, "blocks_rejected": 0, "inserted": 0, "fetch_errors": 0}
    questions = discover(terms)
    summary["questions_found"] = len(questions)
    conn = pg_connect()
    try:
        done = processed_keys(conn)
        for q in questions:
            try:
                lok, qno = int(q["lokNo"]), int(q["quesNo"])
                if (lok, qno) in done:
                    summary["questions_skipped_already_done"] += 1
                    continue
                url = q.get("questionsFilePath")
                if not url:
                    record_question(conn, q, "fetch_error", [], [Reject(0, "fetch_error", "no PDF URL in the search result")])
                    summary["fetch_errors"] += 1
                    continue
                try:
                    pages = read_pdf(LQ._download(url))
                    blocks, rejects = parse_document(pages) if is_relevant(pages) else ([], [])
                except Exception as e:  # noqa: BLE001
                    logger.warning("LS%s Q%s fetch/parse failed: %s", lok, qno, e)
                    record_question(conn, q, "fetch_error", [], [Reject(0, "fetch_error", str(e)[:120])])
                    summary["fetch_errors"] += 1
                    continue
                status = "parsed" if blocks else ("rejected_only" if rejects else "no_sampling_table")
                n = ingest_blocks(conn, q, blocks)
                record_question(conn, q, status, blocks, rejects)
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                logger.error("LS%s Q%s skipped after an unexpected error: %s", q.get("lokNo"), q.get("quesNo"), e)
                summary["fetch_errors"] += 1
                continue
            summary["questions_processed"] += 1
            summary["blocks_accepted"] += len(blocks)
            summary["blocks_rejected"] += len(rejects)
            summary["inserted"] += n
            if blocks or rejects:
                logger.info("LS%s Q%s: %d blocks accepted (%d rows), %d rejected %s", lok, qno, len(blocks), n,
                            len(rejects), sorted({r.reason for r in rejects}))
            time.sleep(0.6)
    finally:
        conn.close()
    if summary["inserted"] == 0 and summary["questions_skipped_already_done"] > 0 and summary["fetch_errors"] == 0:
        summary["note"] = (f"nothing new: all {summary['questions_skipped_already_done']} questions already "
                           f"processed at parser {PARSER_VERSION}")
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Ingest MPRNL pesticide-residue results from Lok Sabha answers").parse_args()
    summary = run()
    print("\n=== LOK SABHA PESTICIDE-RESIDUE INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
