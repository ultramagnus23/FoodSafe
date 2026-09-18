"""
Tests for pipeline/sources/loksabha_sampling.py — the parser for State/UT-wise
"samples analysed vs found non-conforming" tables in Lok Sabha answers.

No PDFs, network or DB: parse_sampling_tables() is a pure function over
already-extracted table cells. Each rejection rule below exists because a real
Parliament PDF produced that exact failure; comments name it. The point of the
parser is what it REFUSES to accept, so most tests assert a rejection.
"""
from __future__ import annotations

import pytest

from pipeline.sources import loksabha_sampling as S
from pipeline.sources.loksabha_sampling import PageTable, parse_int_cell

HEADER = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", "No. of Cases Launched"]
TITLE = ["Annual Public Laboratory Testing Report for the year 2015-2016", "", "", "", ""]


def data(sno, state, analysed, found, cases="1"):
    return [str(sno) if sno != "" else "", state, str(analysed), str(found), cases]


def table(rows, page=1, above="", title=TITLE, header=HEADER):
    head = ([title] if title else []) + [header]
    return PageTable(page=page, rows=head + rows, above_text=above)


def total_row(analysed, found, label="Total"):
    return ["", label, str(analysed), str(found), ""]


FOUR = [data(1, "Assam", 100, 10), data(2, "Bihar", 200, 30), data(3, "Goa", 50, 5), data(4, "Kerala", 150, 20)]


def parse(*tables):
    return S.parse_sampling_tables(list(tables))


def reasons(rejects):
    return [r.reason for r in rejects]


# ---------------------------------------------------------------- number cells

@pytest.mark.parametrize("cell,expected", [
    ("1,708", (1708, "ok")), ("2,23,808", (223808, "ok")), ("1, 708", (1708, "ok")),
    ("09", (9, "ok")), ("Nil", (0, "ok")), ("-", (None, "na")), ("NA", (None, "na")), ("", (None, "empty")), (None, (None, "empty")),
])
def test_parse_int_cell_clean_values(cell, expected):
    assert parse_int_cell(cell) == expected


@pytest.mark.parametrize("cell", ["2837/1784", "99,353\n1228", "Rs. 2,71,000", "14/Rs.4,55,000", "12abc", "1.5"])
def test_parse_int_cell_refuses_multi_value_or_stray_text(cell):
    # LS17 Q4284: two states' figures fused into one cell.
    assert parse_int_cell(cell)[1] == "malformed"


# ---------------------------------------------------------------- fiscal years

def test_fiscal_year_forms_normalise():
    assert S.find_fiscal_years("for the year 2014-2015") == {"2014-2015"}
    assert S.find_fiscal_years("during 2019-20") == {"2019-2020"}
    assert S.find_fiscal_years("year2017-18 report") == {"2017-2018"}


def test_fiscal_year_rejects_non_consecutive_pair():
    assert S.find_fiscal_years("2018-2020") == set()


def test_two_fiscal_years_are_both_reported():
    assert S.find_fiscal_years("2019-20 and 2020-21") == {"2019-2020", "2020-2021"}


# ---------------------------------------------------------------- happy path

def test_clean_table_with_matching_total_is_accepted_and_verified():
    groups, rejects = parse(table(FOUR + [total_row(500, 65)]))
    assert rejects == []
    (g,) = groups
    assert (g.fiscal_year, g.fy_source, g.basis, g.verification) == ("2015-2016", "table_title", "non_conforming", "total_row_sum")
    assert {r["state"]: (r["analysed"], r["found"]) for r in g.rows} == {
        "Assam": (100, 10), "Bihar": (200, 30), "Goa": (50, 5), "Kerala": (150, 20)}


def test_total_label_in_serial_column_is_recognised():
    # LS18 Q3270: the word "Total" sits in the S.No column, not the name column.
    tot = ["Total", "", "500", "65", ""]
    groups, rejects = parse(table(FOUR + [tot]))
    assert rejects == [] and groups[0].verification == "total_row_sum"


def test_indian_digit_grouping_in_total_matches():
    rows = [data(1, "Assam", "1,00,000", 10), data(2, "Bihar", "1,23,808", 30)]
    groups, rejects = parse(table(rows + [total_row("2,23,808", 40)]))
    assert rejects == [] and groups[0].verification == "total_row_sum"


def test_year_from_text_above_is_marked_weaker():
    groups, _ = parse(table(FOUR + [total_row(500, 65)], title=None, above="Details for 2019-20 are below."))
    assert groups[0].fiscal_year == "2019-2020" and groups[0].fy_source == "text_above"


def test_older_adulterated_misbranded_definition_is_kept_distinct():
    hdr = list(HEADER); hdr[3] = "No. of Samples found adulterated and misbranded"
    groups, _ = parse(table(FOUR + [total_row(500, 65)], header=hdr))
    assert groups[0].basis == "adulterated_misbranded"


# ---------------------------------------------------------------- totals

def test_total_off_by_more_than_a_tenth_of_a_percent_rejects_the_table():
    # LS17 Q1058 p6: rows summed to 96,197 vs a printed 99,353 — a missing row.
    groups, rejects = parse(table(FOUR + [total_row(600, 65)]))
    assert groups == [] and reasons(rejects) == ["total_mismatch"]


def test_tiny_total_discrepancy_is_kept_but_flagged_close():
    # LS17 Q1058 p3: printed 75,282 vs summed 75,280 (a source typo, 0.003%).
    rows = [data(1, "Assam", 50_000, 1000), data(2, "Bihar", 25_280, 500)]
    groups, rejects = parse(table(rows + [total_row(75_282, 1500)]))
    assert rejects == [] and groups[0].verification == "total_row_close"


def test_no_total_but_serials_gives_row_invariants_tier():
    groups, _ = parse(table(FOUR))
    assert groups[0].verification == "row_invariants"


def test_no_total_and_no_serial_column_is_unverifiable():
    hdr = ["Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", "Cases"]
    rows = [["Assam", "100", "10", "1"], ["Bihar", "200", "30", "2"]]
    groups, rejects = parse(PageTable(1, [TITLE[:4], hdr] + rows))
    assert groups == [] and reasons(rejects) == ["unverifiable_no_total_no_serials"]


# ---------------------------------------------------------------- self-contradictory rows

def test_found_above_analysed_row_is_dropped_but_still_counted_in_the_total():
    # LS18 Q3270 p4: Mizoram found > analysed. Drop the row, keep the other 35,
    # and still reconcile against the printed total (which includes it).
    rows = [data(1, "Assam", 100, 10), data(2, "Mizoram", 5, 9), data(3, "Goa", 50, 5)]
    groups, rejects = parse(table(rows + [total_row(155, 24)]))
    (g,) = groups
    assert g.verification == "total_row_sum"
    assert [r["state"] for r in g.rows] == ["Assam", "Goa"]
    assert [r.reason for r in rejects] == ["row_dropped_found_exceeds_analysed"]


# ---------------------------------------------------------------- extractor artefacts

def test_two_states_fused_in_one_row_reject_the_table():
    # LS17 Q4284: 'Karnataka/Kerala' with '2837/1784' in one cell.
    rows = [data(1, "Assam", 100, 10), ["2", "Karnataka\nKerala", "2837\n1784", "341\n457", "26\n83"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and len(rejects) == 1


def test_fused_serials_reject_the_table():
    # LS17 Q4284: serial cell reading '10. 11.'
    rows = [data(1, "Assam", 100, 10), ["10. 11.", "Bihar", "200", "30", "1"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("malformed_serial")


def test_unrecognised_state_with_numbers_rejects_the_table():
    # LS17 Q4933: interleaved-character garbage such as 'MPraandiepsuhr'.
    rows = [data(1, "Assam", 100, 10), data(2, "MPraandiepsuhr", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("unrecognised_state")


def test_numbers_with_no_state_name_reject_the_table():
    rows = [data(1, "Assam", 100, 10), ["", "", "3881", "765", "147"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0] == "numbers_without_state_name" or reasons(rejects)[0].startswith("state_row")


def test_state_name_row_without_serial_is_a_misalignment_and_rejects():
    # LS17 Q2901 p5: 'Andhra Pradesh' sat on its own row with no serial, and its
    # numbers sat on the row labelled 'Arunachal Pradesh' — every value shifted.
    rows = [data(1, "Assam", 100, 10), ["", "Andhra Pradesh", "", "", ""], data(2, "Arunachal Pradesh", 4715, 692)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("state_row_without_serial")


def test_serial_gap_rejects_the_table():
    rows = [data(1, "Assam", 100, 10), data(3, "Bihar", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("serial_gap")


def test_duplicate_state_rejects_the_table():
    rows = [data(1, "Assam", 100, 10), data(2, "Assam", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("duplicate_state")


# ---------------------------------------------------------------- split names

def test_name_split_over_two_lines_with_numbers_on_first_line_is_joined():
    # LS17 Q4284: 'Arunachal' / 'Pradesh'.
    rows = [data(1, "Arunachal", 302, 10), ["", "Pradesh", "", "", ""], data(2, "Assam", 100, 5)]
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: r["analysed"] for r in groups[0].rows} == {"Arunachal Pradesh": 302, "Assam": 100}


def test_name_split_with_numbers_on_second_line_is_joined():
    # LS17 Q4284: 'Madhya' (stray value in the last column) / 'Pradesh' (the figures).
    rows = [["1", "Madhya", "", "", "252"], ["", "Pradesh", "5461", "609", ""], data(2, "Assam", 100, 5)]
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: (r["analysed"], r["found"]) for r in groups[0].rows}["Madhya Pradesh"] == (5461, 609)


def test_name_split_over_three_lines_is_joined():
    # LS17 Q4933: 'Dadra Nagar' / 'Haveli & Daman' / '& Diu'.
    rows = [data(1, "Assam", 100, 10), ["2", "Dadra Nagar", "58", "6", "0"], ["", "Haveli & Daman", "", "", ""], ["", "& Diu", "", "", ""]]
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert "Dadra and Nagar Haveli and Daman and Diu" in {r["state"] for r in groups[0].rows}


def test_split_name_where_both_lines_carry_the_same_cell_rejects():
    rows = [["1", "Arunachal", "302", "10", "1"], ["", "Pradesh", "999", "", ""], data(2, "Assam", 100, 5)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("split_row_conflict")


def test_first_state_with_a_split_name_is_not_swallowed_into_the_header():
    # The first state row here is 'Andaman &' / 'Nicobar Islands'; neither half is
    # a recognised State on its own, so header detection must use the row's shape.
    rows = [["1", "Andaman &", "850", "4", "1"], ["", "Nicobar Islands", "", "", ""], data(2, "Assam", 100, 5)]
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: r["analysed"] for r in groups[0].rows} == {"Andaman and Nicobar Islands": 850, "Assam": 100}


def test_column_number_row_is_not_mistaken_for_a_state_row():
    idx = ["1", "2", "3", "4", "5"]     # '(1) (2) (3)' index row under the header
    groups, rejects = parse(PageTable(1, [TITLE, HEADER, idx] + FOUR + [total_row(500, 65)]))
    assert rejects == [] and len(groups[0].rows) == 4


# ---------------------------------------------------------------- whole-table skips

def test_milk_only_table_is_skipped():
    # LS16/LS17 'Annual Public Laboratory Testing Report for Milk ...'
    title = ["Annual Public Laboratory Testing Report for Milk for the year 2016-17", "", "", "", ""]
    groups, rejects = parse(table(FOUR, title=title))
    assert groups == [] and reasons(rejects) == ["commodity_specific"]


def test_commodity_words_match_whole_words_only():
    # 'instead' contains 'tea', 'price' contains 'rice' — must not trigger.
    groups, rejects = parse(table(FOUR + [total_row(500, 65)], title=None,
                                  above="Instead of the old price list, figures for 2018-19 are given below."))
    assert rejects == [] and len(groups) == 1


def test_half_year_table_is_skipped():
    title = ["Half yearly Public Laboratory Testing Report for the year 2017-18", "", "", "", ""]
    groups, rejects = parse(table(FOUR, title=title))
    assert groups == [] and reasons(rejects) == ["partial_period"]


def test_no_fiscal_year_anywhere_rejects():
    groups, rejects = parse(table(FOUR + [total_row(500, 65)], title=None, above="No year is named here."))
    assert groups == [] and reasons(rejects) == ["fy_ambiguous"]


def test_two_fiscal_years_in_the_text_above_is_ambiguous():
    groups, rejects = parse(table(FOUR + [total_row(500, 65)], title=None, above="Compare 2018-19 with 2019-20 below."))
    assert groups == [] and reasons(rejects) == ["fy_ambiguous"]


def test_found_header_spanning_subcolumns_is_refused():
    # LS17 Q2236/Q4933 2021-22: 'No. of Samples found' over 'from samples lifted
    # this year' | 'from earlier years'. Reading one part gave 8,423 vs the true 32,935.
    hdr = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", ""]
    sub = ["", "", "", "From samples lifted during the year", "From samples lifted earlier"]
    rows = [data(1, "Assam", 100, 10, "3"), data(2, "Bihar", 200, 30, "4")]
    groups, rejects = parse(PageTable(1, [TITLE, hdr, sub] + rows))
    assert groups == [] and reasons(rejects) == ["column_split_across_subheaders"]


def test_unrelated_table_is_ignored_not_rejected():
    other = PageTable(1, [["S.No", "State", "Licences issued"], ["1", "Assam", "40"]])
    groups, rejects = parse(other)
    assert groups == [] and rejects == []


# ---------------------------------------------------------------- continuation across pages

def test_table_continued_on_next_page_is_joined_and_totalled():
    # LS17 Q2236: header on page 3, the last states + Total on page 4 (no header).
    first = table(FOUR[:2], page=3)
    rest = PageTable(4, [data(3, "Goa", 50, 5), data(4, "Kerala", 150, 20), total_row(500, 65)])
    groups, rejects = parse(first, rest)
    assert rejects == []
    assert len(groups[0].rows) == 4 and groups[0].verification == "total_row_sum"


def test_repeated_header_on_next_page_continues_the_group():
    # LS17 Q4284 p5: header repeated, no year of its own.
    first = table(FOUR[:2], page=3)
    rest = PageTable(4, [HEADER] + [data(3, "Goa", 50, 5), data(4, "Kerala", 150, 20), total_row(500, 65)])
    groups, rejects = parse(first, rest)
    assert rejects == [] and len(groups[0].rows) == 4 and groups[0].verification == "total_row_sum"


def test_continuation_with_a_serial_gap_is_not_joined():
    first = table(FOUR[:2], page=3)
    rest = PageTable(4, [data(9, "Goa", 50, 5), data(10, "Kerala", 150, 20)])
    groups, _ = parse(first, rest)
    assert len(groups[0].rows) == 2     # the unrelated page was not attached


def test_continuation_on_a_non_adjacent_page_is_not_joined():
    first = table(FOUR[:2], page=3)
    rest = PageTable(6, [data(3, "Goa", 50, 5), data(4, "Kerala", 150, 20)])
    groups, _ = parse(first, rest)
    assert len(groups[0].rows) == 2


def test_bare_total_tail_that_does_not_reconcile_is_ignored_not_fatal():
    first = table(FOUR, page=3)
    stray = PageTable(4, [total_row(99999, 88888)])
    groups, rejects = parse(first, stray)
    assert len(groups) == 1 and groups[0].verification == "row_invariants" and rejects == []


def test_failed_continuation_discards_the_whole_group():
    first = table(FOUR[:2], page=3)
    bad = PageTable(4, [data(3, "MPraandiepsuhr", 50, 5)])
    groups, rejects = parse(first, bad)
    assert groups == [] and reasons(rejects)[0].startswith("continuation_")


# ---------------------------------------------------------------- one question, two tables

def test_two_tables_for_the_same_year_and_basis_in_one_question_are_both_rejected():
    a = table(FOUR + [total_row(500, 65)], page=2)
    b = table(FOUR + [total_row(500, 65)], page=5)
    groups, rejects = parse(a, b)
    assert groups == [] and reasons(rejects) == ["duplicate_period_in_question"] * 2


def test_different_years_in_one_question_are_both_kept():
    t16 = ["Annual Public Laboratory Testing Report for the year 2016-2017", "", "", "", ""]
    groups, rejects = parse(table(FOUR + [total_row(500, 65)], page=2), table(FOUR + [total_row(500, 65)], page=5, title=t16))
    assert rejects == [] and sorted(g.fiscal_year for g in groups) == ["2015-2016", "2016-2017"]


# ---------------------------------------------------------------- state name aliases

@pytest.mark.parametrize("raw,canon", [
    ("Daman & Diu", "Daman and Diu"),
    ("Dadra & N.H", "Dadra and Nagar Haveli"),
    ("Dadara & Nagar Haveli", "Dadra and Nagar Haveli"),
    ("Andaman & Nicobar Islands", "Andaman and Nicobar Islands"),
    ("Jammu & Kashmir", "Jammu and Kashmir"),
    ("Pondicherry", "Puducherry"),
    ("Lakshdweep", "Lakshadweep"),
    ("D&N H D&D", "Dadra and Nagar Haveli and Daman and Diu"),
])
def test_historical_state_name_variants_resolve(raw, canon):
    from pipeline.sources import loksabha_qa as LQ
    assert LQ._canon_state(raw) == canon


def test_pre_2020_uts_are_not_collapsed_into_the_merged_ut():
    from pipeline.sources import loksabha_qa as LQ
    assert LQ._canon_state("Daman & Diu") != LQ._canon_state("Dadra & N.H")
