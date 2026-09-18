"""
FoodSafe India — Lok Sabha State/UT-wise sampling outcomes (samples analysed vs found non-conforming)

Real, primary-source pass/fail counts per State/UT per fiscal year, disclosed
in Lok Sabha written answers (sansad.in) — the "negative class" that
docs/BACKTEST_REPORT.md says no other source in this project provides.
pipeline/sources/loksabha_qa.py deliberately handles only four other metrics;
this module handles the shape those parsers reject: tables with a
"No. of samples analysed" column beside a "No. of samples found
non-conforming" (or, in older answers, "adulterated and misbranded") column.

Correctness policy: these PDFs extract badly (rows merged across two states,
totals fused into the last state row, names split across lines, interleaved
garbled characters). A table is therefore ACCEPTED only if every check below
passes, and otherwise REJECTED WHOLE with a logged reason — never partially
kept, never guessed at:

  * exactly one "samples analysed" column and exactly one "found ..." column
    are identified from the header text (no positional assumptions);
  * every numeric cell is a single clean integer (a cell holding two numbers,
    "Rs." amounts, or stray text rejects the table);
  * every row carrying numbers has a recognised State/UT name (an
    unrecognised or interleaved name rejects the table);
  * found <= analysed on every row;
  * a printed Total row, when present, must equal the column sums exactly;
  * the fiscal year comes from the table's own title (strong) or, failing
    that, from the text directly above it (weaker) — and only if exactly one
    year is named; ambiguity rejects the table;
  * milk-only / other commodity-specific tables and part-year tables are
    skipped, and tables continued on the next page are joined only when the
    serial numbers continue without a gap.

Two different definitions are kept apart, never merged: `non_conforming`
(post-2016-17 wording) and `adulterated_misbranded` (older answers). A
non-conforming sample is not necessarily unsafe.

Run:  python -m pipeline.sources.loksabha_sampling
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

logger = logging.getLogger("foodsafe.loksabha_sampling")

# Bump when parsing rules change: questions logged under an older version are
# re-processed, questions already handled at this version are skipped.
PARSER_VERSION = "sampling-1"

# Lok Sabha terms searched (newest first). Earlier terms use different
# formats (Prevention of Food Adulteration Act era) and were not examined.
SAMPLING_TERMS: tuple[int, ...] = (18, 17, 16)

_FY_RE = re.compile(r"(?<!\d)(20\d\d)\s*[-–—]\s*(?:20)?(\d\d)(?!\d)")

_ANALYSED_RE = re.compile(r"samples?analy[sz]")
_FOUND_NONCONF_RE = re.compile(r"samples?found(?:to be)?(?:non(?:conform|confirm))|foundnonconform|foundnonconfirm")
_FOUND_ADULT_RE = re.compile(r"samples?found(?:to be)?adult")

# Whole-table skips. Commodity words are matched with word boundaries on the raw
# text (squashed matching would hit 'tea' in 'instead', 'rice' in 'price');
# part-year words are distinctive enough to match squashed.
_COMMODITY_RE = re.compile(
    r"\b(?:milk|dairy|water|oils?|ghee|spices?|mango(?:es)?|fruits?|honey|salt|sweets?|paneer|khoa|mawa"
    r"|vanaspati|tea|atta|rice|meat|fish|eggs?|ripen\w*|beverages?|juices?)\b",
    re.IGNORECASE,
)
_PARTIAL_PERIOD_WORDS = ("halfyear", "quarter", "tillsep", "tilldec", "tillmar", "tilljun", "uptosep", "uptodec")

_NIL = {"nil", "0"}
_NA = {"", "-", "–", "—", "na", "n/a", "nr"}


@dataclass
class PageTable:
    page: int                      # 1-based
    rows: list[list]               # raw pdfplumber cells (str | None)
    above_text: str = ""           # text on the same page above the table


@dataclass
class Group:
    fiscal_year: str
    fy_source: str                 # 'table_title' | 'text_above'
    basis: str                     # 'non_conforming' | 'adulterated_misbranded'
    page: int
    rows: list[dict] = field(default_factory=list)   # {state, analysed, found}
    verification: str = "row_invariants"
    _last_sno: Optional[int] = None
    _pages: list[int] = field(default_factory=list)
    _ncols: int = 0
    _cols: tuple[int, int, int, Optional[int]] = (0, 0, 0, None)   # state, analysed, found, sno


@dataclass
class Reject:
    page: int
    reason: str
    detail: str = ""


# ---------------------------------------------------------------- small helpers

def _squash(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _flat(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def parse_int_cell(cell: Optional[str]) -> tuple[Optional[int], str]:
    """(value, status): status in ok | empty | na | malformed.

    A cell holding two numbers ('2837/1784', '99,353\\n1228'), a currency
    amount, or any stray text is 'malformed' — the caller rejects the table
    rather than picking one of the values.
    """
    if cell is None:
        return None, "empty"
    raw = cell.strip()
    low = raw.lower()
    if low in _NA:
        return None, ("empty" if low == "" else "na")
    if low == "nil":
        return 0, "ok"
    if "\n" in raw and len(re.findall(r"\d[\d,]*", raw)) != 1:
        return None, "malformed"
    compact = re.sub(r"[\s,]", "", raw)
    if not re.fullmatch(r"\d+", compact):
        return None, "malformed"
    return int(compact), "ok"


def normalise_fy(a: str, b: str) -> Optional[str]:
    """('2018', '19') -> '2018-2019'; None unless the end year is start+1."""
    start = int(a)
    end = int(b) + (start // 100) * 100 if len(b) == 2 else int(b)
    if end != start + 1:
        return None
    return f"{start}-{end}"


def find_fiscal_years(text: str) -> set[str]:
    out = set()
    for a, b in _FY_RE.findall(text or ""):
        fy = normalise_fy(a, b)
        if fy:
            out.add(fy)
    return out


def _serial(cell: Optional[str]) -> tuple[Optional[int], bool]:
    """(serial, malformed). '12.' -> 12; '1./2.' or '3/4' -> malformed."""
    t = (cell or "").strip().replace("\n", "")
    if not t:
        return None, False
    if re.fullmatch(r"\d+\.?", t):
        return int(t.rstrip(".")), False
    return None, True


# ---------------------------------------------------------------- header resolution

_TOTAL_LABEL_RE = re.compile(r"^(?:grand\s*)?total\s*:?$", re.IGNORECASE)


def _is_total_label(cell: Optional[str]) -> bool:
    return bool(_TOTAL_LABEL_RE.match(_flat(cell)))


_SERIAL_CELL_RE = re.compile(r"^\d+\.?$")


def _looks_like_data_row(row: list) -> bool:
    """A bare serial number followed by a text name: the shape of a state row
    even when its name is only half a State (a name split over two lines, with
    the figures possibly on the other line) and so isn't recognised on its own.
    Header rows never start with a bare serial, and a column-number row
    ('1 2 3') has no text name, so neither matches."""
    if len(row) < 3 or not _SERIAL_CELL_RE.match(_flat(row[0])):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", _flat(row[1])))


def _header_rows(rows: list[list]) -> int:
    """Number of leading rows before the first DATA row: one whose name cell is
    a recognised State/UT, a bare 'Total' label (a header cell such as 'Total
    No. of samples received' is not a bare label), or that has the shape of a
    state row (see _looks_like_data_row)."""
    for i, row in enumerate(rows):
        if _looks_like_data_row(row):
            return i
        for c in row[:3]:
            if LQ._canon_state(_flat(c)) or _is_total_label(c):
                return i
    return len(rows)


def resolve_columns(rows: list[list]) -> tuple[Optional[dict], Optional[str]]:
    """Identify columns from header text. Returns (info, reject_reason);
    (None, None) means 'not a sampling table this parser cares about'."""
    h = _header_rows(rows)
    if h == 0 or h > 8:
        return None, None
    header = rows[:h]
    ncols = max(len(r) for r in rows)
    col_text = [
        " ".join(_flat(r[j]) for r in header if j < len(r) and r[j])
        for j in range(ncols)
    ]
    sq = [_squash(t) for t in col_text]

    analysed = [j for j, t in enumerate(sq) if _ANALYSED_RE.search(t)]
    nonconf = [j for j, t in enumerate(sq) if _FOUND_NONCONF_RE.search(t)]
    adult = [j for j, t in enumerate(sq) if _FOUND_ADULT_RE.search(t)]
    if not analysed or not (nonconf or adult):
        return None, None
    if len(analysed) != 1 or len(nonconf) + len(adult) != 1:
        return None, "ambiguous_columns"

    # A merged header cell spanning several sub-columns (e.g. "samples found"
    # over "from samples lifted this year" | "from earlier years") means the
    # figure we would read is only one part of the total. Detect it: the cell to
    # the right is empty on the row that carries the anchor text but has text
    # on another header row. Reject rather than guess which part is wanted.
    for anchor_col, anchor_re in ((analysed[0], "analy"), ((nonconf or adult)[0], "found")):
        for r in header:
            if anchor_col < len(r) and re.search(anchor_re, _flat(r[anchor_col]).lower()):
                nxt = anchor_col + 1
                if nxt < ncols and not (nxt < len(r) and _flat(r[nxt])):
                    if any(nxt < len(o) and _flat(o[nxt]) for o in header if o is not r):
                        return None, "column_split_across_subheaders"

    # The State column is chosen from the DATA (most recognised State/UT names
    # among the first three columns), not from header text: a long title that
    # mentions "State/UT" often shares column 0 with the serial numbers.
    found_col = (nonconf or adult)[0]
    body = rows[h:]
    scores = {
        j: sum(1 for r in body if j < len(r) and LQ._canon_state(_flat(r[j])))
        for j in range(min(ncols, 3)) if j not in (analysed[0], found_col)
    }
    state_col = max(scores, key=lambda j: scores[j]) if scores else -1
    if state_col < 0 or scores[state_col] < 1:
        return None, "no_state_column"
    sno_col = 0 if state_col == 1 else None

    title_text = " ".join(_flat(c) for r in header for c in r if c)
    return {
        "h": h, "ncols": ncols, "state": state_col, "sno": sno_col,
        "analysed": analysed[0], "found": found_col,
        "basis": "non_conforming" if nonconf else "adulterated_misbranded",
        "title_text": title_text,
    }, None


# ---------------------------------------------------------------- row assembly

def _merge_split_rows(rows: list[list], state_col: int) -> tuple[list[list], Optional[str]]:
    """Join a State/UT name split over two or three physical lines when — and
    only when — the joined name is recognised, the continuation lines carry
    no serial number, and no cell is filled on more than one of the lines."""
    out: list[list] = []
    i = 0
    while i < len(rows):
        row = list(rows[i])
        name = _flat(row[state_col]) if state_col < len(row) else ""
        joined_len = 0
        if name and not LQ._canon_state(name) and not _is_total_label(name):
            parts = [name]
            for k in (1, 2):
                if i + k >= len(rows):
                    break
                nxt = rows[i + k]
                if state_col >= len(nxt):
                    break
                tail = _flat(nxt[state_col])
                sno_next = _flat(nxt[0]) if state_col != 0 and len(nxt) > 0 else ""
                if not tail or sno_next:
                    break
                parts.append(tail)
                if LQ._canon_state(" ".join(parts)):
                    joined_len = k
                    break
        if joined_len:
            group_rows = rows[i:i + joined_len + 1]
            width = max(len(r) for r in group_rows)
            merged: list = [None] * width
            for j in range(width):
                filled = [r[j] for r in group_rows if j < len(r) and _flat(r[j])]
                if j == state_col:
                    merged[j] = " ".join(_flat(r[j]) for r in group_rows)
                elif len(filled) > 1:
                    return [], f"split_row_conflict:{' '.join(parts)}"
                else:
                    merged[j] = filled[0] if filled else None
            out.append(merged)
            i += joined_len + 1
            continue
        out.append(row)
        i += 1
    return out, None


def _read_rows(rows: list[list], info: dict, prev_sno: Optional[int] = None) -> tuple[list[dict], Optional[dict], Optional[str], Optional[int]]:
    """Parse data rows -> (state_rows, total_row, reject_detail, last_serial).

    Structural problems (merged cells, unrecognised names, malformed numbers,
    a state name that has no serial while the table has serials, a gap in the
    serial sequence) return an error and the caller rejects the whole table:
    they are direct evidence the extractor put a name and its numbers on
    different rows. A row that is merely self-contradictory (found > analysed)
    is kept in the returned list flagged `ok: False` so it still counts toward
    the Total check but is not ingested.
    """
    sc, ac, fc, sno_col = info["state"], info["analysed"], info["found"], info["sno"]
    merged, err = _merge_split_rows(rows, sc)
    if err:
        return [], None, err, None
    state_rows: list[dict] = []
    total: Optional[dict] = None
    seen: set[str] = set()
    last_sno: Optional[int] = prev_sno
    for row in merged:
        if max(sc, ac, fc) >= len(row):
            if re.search(r"\d", " ".join(c for c in row if c)):
                return [], None, "short_row_with_numbers", None
            continue
        name = _flat(row[sc])
        sno_cell = row[sno_col] if sno_col is not None and sno_col < len(row) else None
        a_val, a_st = parse_int_cell(row[ac])
        f_val, f_st = parse_int_cell(row[fc])
        numeric_present = a_st in ("ok", "malformed") or f_st in ("ok", "malformed")

        # The 'Total' label may sit in the State column or in the serial column.
        if _is_total_label(name) or _is_total_label(sno_cell):
            if a_st == "malformed" or f_st == "malformed":
                return [], None, f"malformed_total:{name or _flat(sno_cell)!r}", None
            if a_st == "ok" and f_st == "ok":
                total = {"analysed": a_val, "found": f_val}
            continue

        if sno_col is not None:
            sno, bad = _serial(sno_cell)
            if bad and (numeric_present or LQ._canon_state(name)):
                return [], None, f"malformed_serial:{_flat(sno_cell)!r}", None
            if sno is None and LQ._canon_state(name):
                return [], None, f"state_row_without_serial:{name[:30]!r}", None
            if sno is not None:
                if last_sno is not None and sno != last_sno + 1:
                    return [], None, f"serial_gap:{last_sno}->{sno}", None
                last_sno = sno

        if not name:
            if numeric_present:
                return [], None, "numbers_without_state_name", None
            continue
        state = LQ._canon_state(name)
        if state is None:
            if numeric_present:
                return [], None, f"unrecognised_state:{name[:40]!r}", None
            continue
        if a_st == "malformed" or f_st == "malformed":
            return [], None, f"malformed_number:{state}", None
        if a_st != "ok" or f_st != "ok":
            continue    # state reported nothing usable this year
        if state in seen:
            return [], None, f"duplicate_state:{state}", None
        seen.add(state)
        state_rows.append({"state": state, "analysed": a_val, "found": f_val, "ok": f_val <= a_val})
    return state_rows, total, None, last_sno


# ---------------------------------------------------------------- document-level parse

_CLOSE_TOLERANCE = 0.001    # 0.1% — a source typo, not a missing row


def _totals_agree(rows: list[dict], total: dict) -> Optional[str]:
    """None if the printed Total does not match; else 'total_row_sum' (exact)
    or 'total_row_close' (each column within 0.1%)."""
    sa = sum(r["analysed"] for r in rows)
    sf = sum(r["found"] for r in rows)
    if (sa, sf) == (total["analysed"], total["found"]):
        return "total_row_sum"
    def close(a: int, b: int) -> bool:
        return b > 0 and abs(a - b) / b <= _CLOSE_TOLERANCE
    if close(sa, total["analysed"]) and close(sf, total["found"]):
        return "total_row_close"
    return None


def _finalise(group: Group, total: Optional[dict], groups: list[Group], rejects: list[Reject]) -> None:
    if not group.rows:
        rejects.append(Reject(group.page, "no_rows"))
        return
    if total is not None:
        level = _totals_agree(group.rows, total)
        if level is None:
            sa = sum(r["analysed"] for r in group.rows)
            sf = sum(r["found"] for r in group.rows)
            rejects.append(Reject(group.page, "total_mismatch",
                                  f"sum=({sa},{sf}) printed=({total['analysed']},{total['found']})"))
            return
        group.verification = level
    elif group._cols[3] is None:
        # No Total row to reconcile against AND no serial numbers to prove the
        # rows are contiguous and aligned: nothing supports the figures.
        rejects.append(Reject(group.page, "unverifiable_no_total_no_serials"))
        return
    # Self-contradictory rows were counted above; drop them before ingestion.
    for r in [r for r in group.rows if not r["ok"]]:
        rejects.append(Reject(group.page, "row_dropped_found_exceeds_analysed",
                              f"{r['state']} analysed={r['analysed']} found={r['found']}"))
    group.rows = [r for r in group.rows if r["ok"]]
    if not group.rows:
        rejects.append(Reject(group.page, "no_rows"))
        return
    groups.append(group)


def parse_sampling_tables(tables: list[PageTable]) -> tuple[list[Group], list[Reject]]:
    """Pure function over already-extracted tables (see extract_tables())."""
    groups: list[Group] = []
    rejects: list[Reject] = []
    current: Optional[Group] = None
    current_total: Optional[dict] = None

    def close():
        nonlocal current, current_total
        if current is not None:
            _finalise(current, current_total, groups, rejects)
        current, current_total = None, None

    def try_continue(tb: PageTable, data_rows: list[list], ncols: int, cols: Optional[tuple]) -> bool:
        """Append `data_rows` to the open group iff this table is on the very
        next page, has the same width, maps to the same columns (when it
        repeats a header), and either its serial numbers continue exactly
        where the group left off or it is just the closing Total row.
        Returns True if the table was consumed. A continuation that fails on
        its own content discards the open group (reject whole); a bare-Total
        tail that doesn't reconcile is treated as unrelated and ignored."""
        nonlocal current, current_total
        if current is None or current_total is not None:
            return False
        if current._cols[3] is None or tb.page != current._pages[-1] + 1 or ncols != current._ncols:
            return False
        if cols is not None and cols != current._cols:
            return False
        sc, ac, fc, sno_col = current._cols
        info = {"state": sc, "analysed": ac, "found": fc, "sno": sno_col}
        first_sno = next(
            (_serial(r[sno_col])[0] for r in data_rows if sno_col < len(r) and _serial(r[sno_col])[0] is not None),
            None,
        )
        total_first = bool(data_rows) and any(
            _is_total_label(c) for c in data_rows[0][:3]
        )
        if first_sno is None and not total_first:
            return False
        if first_sno is not None and (current._last_sno is None or first_sno != current._last_sno + 1):
            return False

        state_rows, total, err, last = _read_rows(data_rows, info, prev_sno=current._last_sno)
        if err:
            if total_first and first_sno is None:
                return False
            rejects.append(Reject(tb.page, "continuation_" + err.split(":")[0], err))
            current, current_total = None, None
            return True
        have = {r["state"] for r in current.rows}
        if any(r["state"] in have for r in state_rows):
            rejects.append(Reject(tb.page, "continuation_duplicate_state"))
            current, current_total = None, None
            return True
        if first_sno is None:
            # Bare-Total tail: only attach if it reconciles.
            if total is None or _totals_agree(current.rows + state_rows, total) is None:
                return False
        current.rows.extend(state_rows)
        if last is not None:
            current._last_sno = last
        current._pages.append(tb.page)
        current_total = total
        return True

    for tb in tables:
        rows = [r for r in tb.rows if r]
        if not rows:
            continue
        ncols = max(len(r) for r in rows)
        info, why = resolve_columns(rows)

        if info is None:
            # Header-less, or a header this parser can't resolve: it can only
            # ever be the continuation of an open group.
            if try_continue(tb, rows[_header_rows(rows) if _header_rows(rows) < len(rows) else 0:], ncols, None):
                continue
            if why is not None:
                close()
                rejects.append(Reject(tb.page, why))
            continue

        head_squash = _squash(info["title_text"])
        above_tail = tb.above_text[-400:] if tb.above_text else ""
        above_squash = _squash(above_tail[-200:])
        if any(w in head_squash or w in above_squash for w in _PARTIAL_PERIOD_WORDS):
            close(); rejects.append(Reject(tb.page, "partial_period")); continue
        if _COMMODITY_RE.search(info["title_text"]) or _COMMODITY_RE.search(above_tail[-200:]):
            close(); rejects.append(Reject(tb.page, "commodity_specific")); continue

        title_fys = find_fiscal_years(info["title_text"])
        fy, fy_src = None, ""
        if len(title_fys) == 1:
            fy, fy_src = next(iter(title_fys)), "table_title"
        elif len(title_fys) == 0:
            above_fys = find_fiscal_years(above_tail)
            if len(above_fys) == 1:
                fy, fy_src = next(iter(above_fys)), "text_above"
        if fy is None:
            # A repeated header on the next page carries no year of its own:
            # a continuation if (and only if) it lines up exactly.
            cols = (info["state"], info["analysed"], info["found"], info["sno"])
            if try_continue(tb, rows[info["h"]:], info["ncols"], cols):
                continue
            close(); rejects.append(Reject(tb.page, "fy_ambiguous", f"title={sorted(title_fys)}")); continue

        close()
        state_rows, total, err, last = _read_rows(rows[info["h"]:], info)
        if err:
            rejects.append(Reject(tb.page, err.split(":")[0], err))
            continue
        grp = Group(fiscal_year=fy, fy_source=fy_src, basis=info["basis"], page=tb.page, rows=state_rows)
        grp._last_sno = last
        grp._pages = [tb.page]
        grp._ncols = info["ncols"]
        grp._cols = (info["state"], info["analysed"], info["found"], info["sno"])
        current, current_total = grp, total

    close()

    # One question must not yield two tables for the same (year, basis): that
    # would be ambiguous, so neither is kept.
    counts: dict[tuple[str, str], int] = {}
    for g in groups:
        counts[(g.fiscal_year, g.basis)] = counts.get((g.fiscal_year, g.basis), 0) + 1
    kept: list[Group] = []
    for g in groups:
        if counts[(g.fiscal_year, g.basis)] > 1:
            rejects.append(Reject(g.page, "duplicate_period_in_question", f"{g.fiscal_year}/{g.basis}"))
        else:
            kept.append(g)
    return kept, rejects


def extract_tables(pdf_bytes: bytes) -> list[PageTable]:
    import pdfplumber

    out: list[PageTable] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            for tbl in page.find_tables():
                rows = tbl.extract()
                above = ""
                top = tbl.bbox[1]
                if top > 5:
                    try:
                        above = page.crop((0, 0, page.width, top)).extract_text() or ""
                    except Exception:  # noqa: BLE001
                        above = ""
                out.append(PageTable(page=pi, rows=rows, above_text=above))
    return out


# ---------------------------------------------------------------- database

def already_processed(conn, lok_no: int, q_no: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM loksabha_question_log WHERE lok_sabha_no=%s AND source_question_no=%s AND parser_version=%s",
            (lok_no, q_no, PARSER_VERSION),
        )
        row = cur.fetchone()
    return bool(row) and row[0] != "fetch_error"


def record_question(conn, question: dict, status: str, groups: list[Group], rejects: list[Reject]) -> None:
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
             len(groups), len(rejects), json.dumps(detail), question.get("questionsFilePath")),
        )
    conn.commit()


def ingest_groups(conn, question: dict, groups: list[Group]) -> int:
    n = 0
    answered = LQ._parse_date(question.get("date", ""))
    subject = (question.get("subjects") or "").strip()
    with conn.cursor() as cur:
        for g in groups:
            for r in g.rows:
                cur.execute(
                    """INSERT INTO state_sampling_annual
                         (state, fiscal_year, samples_analyzed, samples_non_conforming, non_conforming_basis,
                          verification, fy_source, lok_sabha_no, source_question_no, source_question_subject,
                          answered_date, source_url, source_page, parser_version, fetched_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                       ON CONFLICT (state, fiscal_year, non_conforming_basis, lok_sabha_no, source_question_no)
                       DO UPDATE SET samples_analyzed = EXCLUDED.samples_analyzed,
                                     samples_non_conforming = EXCLUDED.samples_non_conforming,
                                     verification = EXCLUDED.verification, fy_source = EXCLUDED.fy_source,
                                     source_page = EXCLUDED.source_page, parser_version = EXCLUDED.parser_version,
                                     fetched_at = NOW()""",
                    (r["state"], g.fiscal_year, r["analysed"], r["found"], g.basis, g.verification, g.fy_source,
                     int(question["lokNo"]), int(question["quesNo"]), subject, answered,
                     question["questionsFilePath"], g.page, PARSER_VERSION),
                )
                n += 1
    conn.commit()
    return n


def run(terms: tuple[int, ...] | None = None) -> dict:
    summary = {"questions_found": 0, "questions_processed": 0, "questions_skipped_already_done": 0,
               "tables_accepted": 0, "tables_rejected": 0, "inserted": 0, "fetch_errors": 0}
    questions = LQ.discover_questions(terms or SAMPLING_TERMS)
    summary["questions_found"] = len(questions)
    conn = pg_connect()
    try:
        for q in questions:
            url = q.get("questionsFilePath")
            lok, qno = int(q["lokNo"]), int(q["quesNo"])
            if not url:
                continue
            if already_processed(conn, lok, qno):
                summary["questions_skipped_already_done"] += 1
                continue
            try:
                pdf = LQ._download(url)
                groups, rejects = parse_sampling_tables(extract_tables(pdf))
            except Exception as e:  # noqa: BLE001
                logger.warning("LS%s Q%s fetch/parse failed: %s", lok, qno, e)
                record_question(conn, q, "fetch_error", [], [Reject(0, "fetch_error", str(e)[:120])])
                summary["fetch_errors"] += 1
                continue
            status = "parsed" if groups else ("rejected_only" if rejects else "no_sampling_table")
            n = ingest_groups(conn, q, groups)
            record_question(conn, q, status, groups, rejects)
            summary["questions_processed"] += 1
            summary["tables_accepted"] += len(groups)
            # Dropped single rows are informational, not rejected tables.
            summary["tables_rejected"] += sum(1 for r in rejects if not r.reason.startswith("row_dropped"))
            summary["inserted"] += n
            if groups or rejects:
                logger.info("LS%s Q%s: %d tables accepted (%d rows), %d rejected %s", lok, qno, len(groups), n,
                            len(rejects), sorted({r.reason for r in rejects}))
            time.sleep(0.6)
    finally:
        conn.close()
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    argparse.ArgumentParser(description="Ingest State/UT-wise samples analysed vs non-conforming from Lok Sabha answers").parse_args()
    summary = run()
    print("\n=== LOK SABHA SAMPLING INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
