"""
Tests for pipeline/sources/loksabha_pesticide.py (MPRNL pesticide-residue
results from Lok Sabha answers). Fixtures are the real answers' tables/text
(LS16 Q3401, LS16 Q1312, LS16 Q127, LS17 Q3823/Q2630/Q1242), so each rule is
pinned to input that actually occurs. No network, no database.
"""
from __future__ import annotations

import copy

import pytest

from pipeline.sources import loksabha_pesticide as P

# ---- shape A: LS16 Q3401 (real pdfplumber output) -------------------------

TABLE_A = [
    ["Commodity", "April, 2014- March,\n15", None, "April, 2015- March, 16", None, "April, 2016- July, 2016", None],
    [None, "Samples\nanalysed", "Samples\nabove\nFSSAI\nMRL", "Samples\nanalysed", "Samples\nabove FSSAI\nMRL",
     "Samples\nanalysed", "Samples\nabove\nFSSAI MRL"],
    ["Fish/Marine", "893", "0", "837", "0", "249", "0"],
    ["Fruits", "2239", "40", "2364", "27", "714", "14"],
    ["Meat/Egg", "444", "0", "402", "0", "153", "0"],
    ["Milk", "459", "0", "462", "0", "153", "0"],
    ["Pulses", "715", "1", "749", "0", "239", "0"],
    ["Rice", "1076", "68", "1128", "45", "376", "16"],
    ["Spices", "1299", "106", "1390", "86", "466", "22"],
    ["Tea", "174", "4", "181", "8", "60", "9"],
    ["Vegetables", "10593", "306", "12035", "329", "3769", "59"],
    ["Water", "1921", "0", "1712", "0", "539", "0"],
    ["Wheat", "805", "17", "843", "27", "248", "2"],
    ["Total", "20,618", "542 (2.6\n%)", "22,103", "522 (2.4 %)", "6,966", "122 (1.8 %)"],
]


def table_a(edits):
    t = copy.deepcopy(TABLE_A)
    for (r, c), v in edits.items():
        t[r][c] = v
    return t


def test_the_real_commodity_table_is_accepted_with_a_verified_total():
    block, reject = P.parse_commodity_table(TABLE_A, page=2)
    assert reject is None and block.verification == "total_row_sum" and len(block.rows) == 33
    veg = {r["period_label"]: (r["analysed"], r["above"]) for r in block.rows if r["commodity"] == "vegetables"}
    assert veg == {"2014-15": (10593, 306), "2015-16": (12035, 329), "Apr 2016-Jul 2016": (3769, 59)}


def test_periods_are_full_fiscal_years_or_marked_partial():
    kinds = {r["period_label"]: r["period_kind"] for r in P.parse_commodity_table(TABLE_A, 2)[0].rows}
    assert kinds == {"2014-15": "fiscal_year", "2015-16": "fiscal_year", "Apr 2016-Jul 2016": "partial_year"}
    fy = next(r for r in P.parse_commodity_table(TABLE_A, 2)[0].rows if r["period_label"] == "2014-15")["fiscal_year"]
    assert fy == "2014-2015"


@pytest.mark.parametrize("edit,reason", [
    ({(3, 1): "2240"}, "total_mismatch"),                    # one misread digit
    ({(3, 2): "41"}, "total_mismatch"),
    ({(13, 2): "542 (2.9 %)"}, "percent_mismatch"),           # total right, printed pct wrong
    ({(3, 2): "9999"}, "above_exceeds_analysed"),
    ({(3, 1): "22 39"}, "malformed_number"),                  # two fused cells, never '2,239'
    ({(3, 1): "2239/40"}, "malformed_number"),
    ({(2, 0): "Fish and Chips"}, "unrecognised_commodity"),
])
def test_commodity_table_rejects_every_kind_of_misread(edit, reason):
    block, reject = P.parse_commodity_table(table_a(edit), 2)
    assert block is None and reject.reason == reason


def test_table_without_a_total_is_rejected():
    block, reject = P.parse_commodity_table(TABLE_A[:-1], 2)
    assert block is None and reject.reason == "table_no_total"


def test_a_dropped_commodity_row_fails_the_total():
    t = copy.deepcopy(TABLE_A)
    del t[6]
    block, reject = P.parse_commodity_table(t, 2)
    assert block is None and reject.reason == "total_mismatch"


def test_unreadable_period_header_rejects_the_table():
    t = table_a({(0, 1): "Q3 FY"})
    assert P.parse_commodity_table(t, 2)[1].reason == "table_period_unreadable"


def test_table_that_is_not_a_commodity_table_is_ignored_silently():
    assert P.parse_commodity_table([["Sr. No.", "State", "Samples"]] * 5, 1) == (None, None)


# ---- shape B: text blocks ---------------------------------------------------

TEXT_B1 = """Annexure I
Details of vegetable samples analysed under MPRNL (2012-18)
Year No. of samples No. of samples above FSSAI MRL
analysed
2012-13 7570 207 (2.7%)
2013-14 7591 192 (2.5%)
2014-15 10593 306 (2.9%)
2015-16 12035 329 (2.7%)
2016-17 11955 256 (2.1%)
2017-18 12821 246 (1.9%)
Grand Total 62565 1536 (2.5%)
Details of meat samples analysed under MPRNL (2012-18)
Year No. of samples No. of samples above FSSAI MRL
analysed
2012-13 439 0
2013-14 435 0
2014-15 444 0
2015-16 402 0
2016-17 417 0
2017-18 374 0
Grand Total 2511 0
*******"""

TEXT_B2 = """Annexure II
Year Wise Details of Sample Analysed
Fruits
S.No. Year Samples Samples Percentage of
Analysed above MRL samples above
MRL
1. 2012-13 1862 22 1.2
2. 2013-14 2235 36 1.6
3. 2014-15 2239 40 1.8
TOTAL 6336 98 1.54
Vegetables
S.No. Year Samples Samples Percentage of
Analysed above MRL samples above
MRL
1. 2012-13 7347 212 2.9
2. 2013-14 7591 221 2.9
3. 2014-15 10593 306 2.9
TOTAL 25531 739 2.9
"""


def test_text_blocks_in_the_titled_form_are_accepted_with_totals():
    blocks, rejects = P.parse_text_blocks(TEXT_B1)
    assert rejects == [] and len(blocks) == 2
    veg = next(b for b in blocks if b.rows[0]["commodity"] == "vegetables")
    assert len(veg.rows) == 6 and veg.rows[1]["above"] == 192 and veg.verification == "total_row_sum"


def test_text_blocks_in_the_annexure_form_are_accepted_and_truncated_percentages_pass():
    # 98/6336 = 1.5467 is printed 1.54 (truncated), 212/7347 = 2.885 is printed 2.9 (rounded).
    blocks, rejects = P.parse_text_blocks(TEXT_B2)
    assert rejects == [] and [b.rows[0]["commodity"] for b in blocks] == ["fruits", "vegetables"]


def test_a_missing_year_row_fails_the_printed_total():
    blocks, rejects = P.parse_text_blocks(TEXT_B1.replace("2015-16 12035 329 (2.7%)\n", ""))
    assert [r.reason for r in rejects] == ["total_mismatch"] and len(blocks) == 1   # the meat block is unaffected


def test_a_misread_count_fails_the_printed_total():
    blocks, rejects = P.parse_text_blocks(TEXT_B1.replace("2014-15 10593 306", "2014-15 10598 306"))
    assert [r.reason for r in rejects] == ["total_mismatch"]


def test_a_wrong_row_percentage_is_rejected():
    _, rejects = P.parse_text_blocks(TEXT_B1.replace("7591 192 (2.5%)", "7591 192 (3.5%)"))
    assert [r.reason for r in rejects] == ["percent_mismatch"]


def test_a_block_with_no_printed_total_is_rejected():
    text = "\n".join(l for l in TEXT_B1.splitlines() if not l.startswith("Grand Total 62565"))
    _, rejects = P.parse_text_blocks(text)
    assert "block_no_total" in [r.reason for r in rejects] or "total_mismatch" in [r.reason for r in rejects]


def test_a_bare_commodity_word_without_a_header_line_is_not_a_block():
    blocks, rejects = P.parse_text_blocks("Fruits\nare good for you\n2014-15 100 1\nTotal 100 1")
    assert blocks == [] and rejects == []


def test_above_exceeding_analysed_is_rejected_in_text():
    _, rejects = P.parse_text_blocks(TEXT_B1.replace("2012-13 439 0", "2012-13 439 900"))
    assert rejects[0].reason == "above_exceeds_analysed"


# ---- shape C: prose ---------------------------------------------------------

def test_the_real_single_year_sentence_is_accepted_as_the_weak_tier():
    text = ("During 2018-19; 29,410 samples of food commodities were analysed and 863 (2.93 %) samples "
            "were found with residue above Maximum Residue Limit.")
    blocks, rejects = P.parse_sentences(text)
    assert rejects == [] and len(blocks) == 1
    row = blocks[0].rows[0]
    assert blocks[0].verification == "pct_consistent" and row["commodity"] == "all_commodities"
    assert (row["analysed"], row["above"], row["period_kind"], row["fiscal_year"]) == (29410, 863, "fiscal_year", "2018-2019")


def test_a_multi_year_sentence_is_marked_a_pool_with_indian_digit_grouping():
    text = ("During 2014-19, a total of 1,18,035 samples have been collected and analyzed, out of which "
            "2,950 (2.5 %) samples were found exceeding Maximum Residue Level fixed by FSSAI.")
    row = P.parse_sentences(text)[0][0].rows[0]
    assert (row["analysed"], row["above"], row["period_kind"], row["fiscal_year"], row["period_label"]) == \
        (118035, 2950, "multi_year_pool", None, "2014-19")


def test_a_sentence_whose_percentage_disagrees_is_rejected():
    text = "During 2018-19; 29,410 samples were analysed and 863 (9.93 %) samples were found with residue above MRL."
    blocks, rejects = P.parse_sentences(text)
    assert blocks == [] and rejects[0].reason == "sentence_inconsistent"


def test_a_sentence_spanning_a_line_break_still_matches():
    text = "During 2012-18, a total of 1,21,944\nsamples have been collected and analyzed, out of which 2,878 (2.4 %)\nsamples were found exceeding FSSAI MRL"
    assert len(P.parse_sentences(text)[0]) == 1


# ---- whole document -----------------------------------------------------------

def _pages(text="", tables=()):
    return [{"page": 1, "text": text, "tables": list(tables)}]


def test_document_combines_all_three_shapes():
    text = TEXT_B1 + "\nDuring 2018-19; 29,410 samples were analysed and 863 (2.93 %) samples were found above MRL."
    blocks, rejects = P.parse_document(_pages(text, [TABLE_A]))
    assert rejects == [] and sorted(b.shape for b in blocks) == ["sentence", "table", "text_block", "text_block"]


def test_the_same_figures_repeated_in_one_answer_are_harmless():
    # TEXT_B1's vegetables 2014-15 (10593 / 306) is also in TABLE_A: same numbers, no ambiguity.
    blocks, rejects = P.parse_document(_pages(TEXT_B1, [TABLE_A]))
    assert rejects == [] and len(blocks) == 3


def test_different_figures_for_the_same_commodity_and_period_in_one_answer_reject_both_blocks():
    conflicting = TEXT_B2.replace("3. 2014-15 10593 306 2.9", "3. 2014-15 10593 999 9.4").replace(
        "TOTAL 25531 739 2.9", "TOTAL 25531 1432 5.6")
    blocks, rejects = P.parse_document(_pages(conflicting, [TABLE_A]))
    assert any(r.reason == "same_period_twice_in_one_answer" for r in rejects)
    assert not any(r["commodity"] == "vegetables" and r["period_label"] == "2014-15" for b in blocks for r in b.rows)


def test_relevance_gate():
    assert P.is_relevant(_pages("Monitoring of Pesticide Residues at National Level"))
    assert not P.is_relevant(_pages("Delhi Metro Rail Corporation"))


@pytest.mark.parametrize("above,analysed,printed,ok", [
    (98, 6336, "1.54", True), (98, 6336, "1.55", True), (98, 6336, "1.60", False),
    (863, 29410, "2.93", True), (212, 7347, "2.9", True), (100, 1000, None, True),
    (5, 0, "1.0", False), (100, 1000, "12", False),
])
def test_percent_consistency(above, analysed, printed, ok):
    assert P.pct_consistent(above, analysed, printed) is ok


# ---- database layer (fake connection) ---------------------------------------

class _Cur:
    def __init__(self, log, fetch=()):
        self.log, self._fetch = log, fetch

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split())[:60], params))

    def fetchall(self):
        return list(self._fetch)


class _Conn:
    def __init__(self, fetch=()):
        self.log, self.commits, self.rollbacks, self._fetch = [], 0, 0, fetch

    def cursor(self):
        return _Cur(self.log, self._fetch)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _question(no=1):
    return {"lokNo": "16", "quesNo": str(no), "date": "06.12.2016", "subjects": "Monitoring of Pesticide Residues",
            "ministry": "AGRICULTURE AND FARMERS WELFARE", "questionsFilePath": f"https://sansad.in/{no}.pdf"}


def test_ingest_replaces_a_questions_rows_in_one_transaction():
    blocks, _ = P.parse_document(_pages(TEXT_B1))
    conn = _Conn()
    n = P.ingest_blocks(conn, _question(), blocks)
    verbs = [e[0].split()[0] for e in conn.log]
    assert verbs[0] == "DELETE" and verbs.count("INSERT") == n == 12 and conn.commits == 1
    assert "pesticide_residue_annual" in conn.log[0][0]


def test_a_question_that_now_yields_nothing_still_clears_its_old_rows():
    conn = _Conn()
    assert P.ingest_blocks(conn, _question(), []) == 0
    assert [e[0].split()[0] for e in conn.log] == ["DELETE"] and conn.commits == 1


def _patch_run(monkeypatch, conn, questions, pages):
    monkeypatch.setattr(P, "pg_connect", lambda: conn)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    monkeypatch.setattr(P, "discover", lambda terms=None: questions)
    monkeypatch.setattr(P.LQ, "_download", lambda url: b"pdf")
    monkeypatch.setattr(P, "read_pdf", lambda pdf: pages)


def test_one_bad_question_does_not_abort_the_run(monkeypatch):
    conn = _Conn()
    _patch_run(monkeypatch, conn, [_question(1), _question(2), _question(3)], _pages(TEXT_B1 + "\nMPRNL"))
    real = P.ingest_blocks

    def flaky(c, q, blocks):
        if q["quesNo"] == "2":
            raise RuntimeError("database hiccup")
        return real(c, q, blocks)
    monkeypatch.setattr(P, "ingest_blocks", flaky)

    summary = P.run()

    assert summary["questions_processed"] == 2 and summary["fetch_errors"] == 1 and summary["inserted"] == 24
    assert conn.rollbacks == 1


def test_an_irrelevant_pdf_is_logged_as_no_table(monkeypatch):
    conn = _Conn()
    _patch_run(monkeypatch, conn, [_question(5)], _pages("Delhi Metro Rail Corporation"))
    summary = P.run()
    assert summary["inserted"] == 0 and summary["questions_processed"] == 1
    logged = [e for e in conn.log if "loksabha_question_log" in e[0]]
    assert logged and logged[0][1][3] == "no_sampling_table" and logged[0][1][2] == P.PARSER_VERSION


def test_a_question_with_no_url_is_logged_not_silently_skipped(monkeypatch):
    conn = _Conn()
    q = _question(9)
    q["questionsFilePath"] = ""
    monkeypatch.setattr(P, "pg_connect", lambda: conn)
    monkeypatch.setattr(P, "discover", lambda terms=None: [q])
    summary = P.run()
    assert summary["fetch_errors"] == 1 and any("loksabha_question_log" in e[0] for e in conn.log)


def test_an_already_processed_question_is_skipped_and_noted(monkeypatch):
    conn = _Conn(fetch=[(16, 1)])
    monkeypatch.setattr(P, "pg_connect", lambda: conn)
    monkeypatch.setattr(P, "discover", lambda terms=None: [_question(1)])
    summary = P.run()
    assert summary["questions_skipped_already_done"] == 1 and summary["inserted"] == 0
    assert "nothing new" in summary["note"] and P.PARSER_VERSION in summary["note"]


def test_discovery_keeps_only_relevant_ministries(monkeypatch):
    results = [
        {"lokNo": 16, "quesNo": 1, "ministry": "AGRICULTURE AND FARMERS WELFARE"},
        {"lokNo": 16, "quesNo": 2, "ministry": "JAL SHAKTI"},
        {"lokNo": 16, "quesNo": 3, "ministry": "Health and Family Welfare"},
        {"lokNo": 16, "quesNo": 4, "ministry": "HOUSING AND URBAN AFFAIRS"},
    ]
    monkeypatch.setattr(P.LQ, "_search", lambda kw, term, page_size=200: results)
    found = P.discover((16,))
    assert sorted(int(q["quesNo"]) for q in found) == [1, 3]


def test_discovery_raises_when_the_search_api_is_unreachable(monkeypatch):
    def dead(kw, term, page_size=200):
        raise OSError("timed out")
    monkeypatch.setattr(P.LQ, "_search", dead)
    with pytest.raises(P.LQ.SearchUnavailable):
        P.discover((18, 17, 16))
