"""
Tests for pipeline/sources/loksabha_sampling.py — the parser for State/UT-wise
"samples analysed vs found non-conforming" tables in Lok Sabha answers.

No PDFs, network or DB: parse_sampling_tables() is a pure function over
already-extracted table cells. Each rejection rule exists because a real
Parliament PDF (or an independent review of this parser) produced that exact
failure; comments name it. The point of the parser is what it REFUSES to
accept, so most tests assert a rejection.
"""
from __future__ import annotations

import re

import pytest

from pipeline.sources import loksabha_sampling as S
from pipeline.sources.loksabha_sampling import PageTable, parse_int_cell

HEADER = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", "No. of Cases Launched"]
TITLE = ["Annual Public Laboratory Testing Report for the year 2015-2016", "", "", "", ""]

NAMES = ["Assam", "Bihar", "Goa", "Kerala", "Gujarat", "Haryana", "Punjab", "Sikkim", "Tripura", "Manipur",
         "Odisha", "Rajasthan", "Mizoram", "Nagaland"]


def data(sno, state, analysed, found, cases="1"):
    return [str(sno) if sno != "" else "", state, str(analysed), str(found), cases]


def rows_for(names=NAMES[:12], start=1):
    return [data(start + i, n, 100 * (start + i), 10 * (start + i)) for i, n in enumerate(names)]


def cell_int(c):
    return int(re.sub(r"[\s,]", "", c))


def sums(rows):
    return sum(cell_int(r[2]) for r in rows), sum(cell_int(r[3]) for r in rows)


def total_row(analysed, found, label="Total"):
    return ["", label, str(analysed), str(found), ""]


def with_total(rows, label="Total"):
    return rows + [total_row(*sums(rows), label=label)]


def table(rows, page=1, above="", title=TITLE, header=HEADER):
    head = ([title] if title else []) + [header]
    return PageTable(page=page, rows=head + rows, above_text=above)


ROWS = rows_for()


def parse(*tables, subject=""):
    return S.parse_sampling_tables(list(tables), subject=subject)


def reasons(rejects):
    return [r.reason for r in rejects]


def indian(n):
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


# ---------------------------------------------------------------- number cells

@pytest.mark.parametrize("cell,expected", [
    ("1,708", (1708, "ok")), ("2,23,808", (223808, "ok")), ("1, 708", (1708, "ok")), ("1,06, 459", (106459, "ok")),
    ("2,23,\n808", (223808, "ok")), ("09", (9, "ok")), ("Nil", (0, "ok")), ("-", (None, "na")), ("NA", (None, "na")),
    ("", (None, "empty")), (None, (None, "empty")),
])
def test_parse_int_cell_clean_values(cell, expected):
    assert parse_int_cell(cell) == expected


@pytest.mark.parametrize("cell", [
    "2837/1784", "99,353\n1228", "Rs. 2,71,000", "14/Rs.4,55,000", "12abc", "1.5",
    "5461 609",              # two figures split by a space must NOT become 5,461,609
    "12 34", "1,7 08", "99999999999999",   # a count can never exceed MAX_COUNT (and would overflow INTEGER)
])
def test_parse_int_cell_refuses_multi_value_stray_text_or_absurd_size(cell):
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
    groups, rejects = parse(table(with_total(ROWS)))
    assert rejects == []
    (g,) = groups
    assert (g.fiscal_year, g.fy_source, g.basis, g.verification) == ("2015-2016", "table_title", "non_conforming", "total_row_sum")
    assert {r["state"]: (r["analysed"], r["found"]) for r in g.rows} == {r[1]: (cell_int(r[2]), cell_int(r[3])) for r in ROWS}


def test_total_label_in_serial_column_is_recognised():
    # LS18 Q3270: the word "Total" sits in the S.No column, not the name column.
    tot = ["Total", "", *map(str, sums(ROWS)), ""]
    groups, rejects = parse(table(ROWS + [tot]))
    assert rejects == [] and groups[0].verification == "total_row_sum"


def test_indian_digit_grouping_in_total_matches():
    rows = rows_for()
    rows[0][2] = "1,00,000"
    rows[1][2] = "1,23,808"
    a, f = sums(rows)
    groups, rejects = parse(table(rows + [total_row(indian(a), indian(f))]))
    assert rejects == [] and groups[0].verification == "total_row_sum"


def test_year_from_text_above_is_marked_weaker():
    groups, _ = parse(table(with_total(ROWS), title=None, above="Details for 2019-20 are below."))
    assert groups[0].fiscal_year == "2019-2020" and groups[0].fy_source == "text_above"


def test_older_adulterated_misbranded_definition_is_kept_distinct():
    hdr = list(HEADER); hdr[3] = "No. of Samples found adulterated and misbranded"
    groups, _ = parse(table(with_total(ROWS), header=hdr))
    assert groups[0].basis == "adulterated_misbranded"


def test_one_cell_title_naming_analysed_and_found_does_not_create_a_phantom_column():
    # A title such as '... samples analysed and found non-conforming ... 2018-19' is
    # not a column; it used to match in column 0 and make the table 'ambiguous'.
    title = ["Details of samples analysed and found non-conforming during 2018-19", "", "", "", ""]
    groups, rejects = parse(table(with_total(ROWS), title=title))
    assert rejects == [] and groups[0].fiscal_year == "2018-2019"


# ---------------------------------------------------------------- column resolution

def test_found_to_be_non_conforming_is_recognised_and_a_second_matching_column_rejects():
    # Reviewer finding: the pattern had a literal space in squashed text, so
    # 'found to be non-conforming' never matched and the parser silently read
    # 'cases launched for samples found non-conforming' (100, 3) as the finding.
    hdr = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "Samples found to be non-conforming",
           "Cases launched for samples found non-conforming"]
    groups, rejects = parse(table(with_total(ROWS), header=hdr))
    assert groups == [] and reasons(rejects) == ["ambiguous_columns"]


def test_found_to_be_non_conforming_alone_is_accepted():
    hdr = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "Samples found to be non-conforming", "Cases"]
    groups, rejects = parse(table(with_total(ROWS), header=hdr))
    assert rejects == [] and groups[0].basis == "non_conforming"


def test_one_header_cell_naming_both_counts_rejects():
    # Reviewer finding: found == analysed for every state.
    hdr = ["S. No.", "Name of State/UT", "Samples analysed and found non-conforming", "x", "y"]
    groups, rejects = parse(table(with_total(ROWS), header=hdr))
    assert groups == [] and reasons(rejects) == ["ambiguous_columns"]


def test_adulterated_beside_a_separate_misbranded_column_rejects():
    # Reviewer finding: the total is the sum of two columns and only one was read.
    hdr = ["S. No.", "Name of State/UT", "Samples analysed", "Samples found adulterated", "Samples found misbranded"]
    groups, rejects = parse(table(with_total(ROWS), header=hdr))
    assert groups == [] and reasons(rejects) == ["ambiguous_columns"]


def test_found_header_spanning_subcolumns_is_refused():
    # LS17 Q2236/Q4933 2021-22: 'No. of Samples found' over 'from samples lifted
    # this year' | 'from earlier years'. Reading one part gave 8,423 vs the true 32,935.
    hdr = ["S. No.", "Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", ""]
    sub = ["", "", "", "From samples lifted during the year", "From samples lifted earlier"]
    groups, rejects = parse(PageTable(1, [TITLE, hdr, sub] + ROWS))
    assert groups == [] and reasons(rejects) == ["column_split_across_subheaders"]


def test_unrelated_table_is_ignored_not_rejected():
    other = PageTable(1, [["S.No", "State", "Licences issued"], ["1", "Assam", "40"]])
    groups, rejects = parse(other)
    assert groups == [] and rejects == []


# ---------------------------------------------------------------- totals

def test_total_off_by_more_than_a_tenth_of_a_percent_rejects_the_table():
    # LS17 Q1058 p6: rows summed to 96,197 vs a printed 99,353 — a missing row.
    a, f = sums(ROWS)
    groups, rejects = parse(table(ROWS + [total_row(a + 4000, f)]))
    assert groups == [] and reasons(rejects) == ["total_mismatch"]


def test_tiny_total_discrepancy_is_kept_but_flagged_close():
    # LS17 Q1058 p3: printed 75,282 vs summed 75,280 (a source typo, 0.003%).
    rows = rows_for()
    rows[0][2] = "50000"
    a, f = sums(rows)
    groups, rejects = parse(table(rows + [total_row(a + 2, f)]))
    assert rejects == [] and groups[0].verification == "total_row_close"


def test_close_tolerance_is_capped_in_absolute_terms_so_a_missing_small_unit_cannot_hide():
    # Reviewer finding: 0.1% alone (~170 samples nationally) can hide a whole
    # dropped small UT. Within 0.1% but more than 10 samples out must reject.
    rows = rows_for()
    rows[0][2] = "500000"
    a, f = sums(rows)
    groups, rejects = parse(table(rows + [total_row(a + 100, f)]))      # 0.02% but 100 samples
    assert groups == [] and reasons(rejects) == ["total_mismatch"]


def test_an_unreadable_total_row_rejects_instead_of_passing_as_row_checked():
    # Reviewer finding: a Total with an empty 'found' was silently ignored.
    groups, rejects = parse(table(ROWS + [["", "Total", "999999", "", ""]]))
    assert groups == [] and reasons(rejects) == ["total_unusable"]


def test_no_total_but_serials_gives_row_invariants_tier():
    groups, _ = parse(table(ROWS))
    assert groups[0].verification == "row_invariants"


def test_no_total_and_no_serial_column_is_unverifiable():
    hdr = ["Name of State/UT", "No. of Samples Analysed", "No. of Samples found non-conforming", "Cases"]
    rows = [[r[1], r[2], r[3], r[4]] for r in ROWS]
    groups, rejects = parse(PageTable(1, [TITLE[:4], hdr] + rows))
    assert groups == [] and reasons(rejects) == ["unverifiable_no_total_no_serials"]


def test_too_few_states_is_a_fragment_not_a_table():
    groups, rejects = parse(table(with_total(ROWS[:4])))
    assert groups == [] and reasons(rejects) == ["too_few_states"]


def test_first_serial_must_be_one():
    # Reviewer finding: serials 15, 16, ... (the first 14 rows lost) passed.
    groups, rejects = parse(table(rows_for(NAMES[:12], start=15)))
    assert groups == [] and reasons(rejects)[0] == "serial_start"


# ---------------------------------------------------------------- self-contradictory rows

def test_found_above_analysed_row_is_dropped_but_still_counted_in_the_total():
    # LS18 Q3270 p4: Mizoram found > analysed. Drop the row, keep the rest, and
    # still reconcile against the printed total (which includes it).
    rows = rows_for()
    rows[4][3] = str(cell_int(rows[4][2]) + 9)
    groups, rejects = parse(table(with_total(rows)))
    (g,) = groups
    assert g.verification == "total_row_sum"
    assert rows[4][1] not in [r["state"] for r in g.rows] and len(g.rows) == 11
    assert [r.reason for r in rejects] == ["row_dropped_found_exceeds_analysed"]


# ---------------------------------------------------------------- extractor artefacts

def test_two_states_fused_in_one_row_reject_the_table():
    # LS17 Q4284: 'Karnataka/Kerala' with '2837/1784' in one cell.
    rows = rows_for(NAMES[:11]) + [["12", "Karnataka\nKerala", "2837\n1784", "341\n457", "26\n83"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and len(rejects) == 1


def test_fused_serials_reject_the_table():
    # LS17 Q4284: serial cell reading '10. 11.'
    rows = rows_for(NAMES[:9]) + [["10. 11.", "Bihar", "200", "30", "1"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("malformed_serial")


def test_unrecognised_state_with_numbers_rejects_the_table():
    # LS17 Q4933: interleaved-character garbage such as 'MPraandiepsuhr'.
    rows = rows_for(NAMES[:5]) + [data(6, "MPraandiepsuhr", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("unrecognised_state")


def test_numbers_with_no_state_name_reject_the_table():
    rows = rows_for(NAMES[:5]) + [["", "", "3881", "765", "147"]]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0] == "numbers_without_state_name"


def test_state_name_row_without_serial_is_a_misalignment_and_rejects():
    # LS17 Q2901 p5: 'Andhra Pradesh' sat on its own row with no serial, and its
    # numbers sat on the row labelled 'Arunachal Pradesh' — every value shifted.
    rows = rows_for(NAMES[:5]) + [["", "Punjab", "", "", ""], data(6, "Haryana", 4715, 692)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("state_row_without_serial")


def test_orphan_text_line_after_a_state_row_rejects():
    # Reviewer finding: leftover text after a State row is probably the rest of its
    # name (or a detached name row); the row above may carry the wrong State.
    rows = rows_for(NAMES[:6]) + [["", "Some leftover words", "", "", ""]] + rows_for(NAMES[6:12], start=7)
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("orphan_text_line")


def test_section_headings_between_rows_are_allowed():
    rows = rows_for(NAMES[:6]) + [["", "Union Territories", "", "", ""]] + rows_for(NAMES[6:12], start=7)
    groups, rejects = parse(table(with_total(rows[:6] + rows[7:])[:6] + [rows[6]] + rows[7:] + [total_row(*sums(rows[:6] + rows[7:]))]))
    assert rejects == [] and len(groups[0].rows) == 12


def test_serial_gap_rejects_the_table():
    rows = rows_for(NAMES[:5]) + [data(7, "Sikkim", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("serial_gap")


def test_duplicate_state_rejects_the_table():
    rows = rows_for(NAMES[:5]) + [data(6, "Assam", 200, 30)]
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("duplicate_state")


# ---------------------------------------------------------------- split names

def test_name_split_over_two_lines_with_numbers_on_first_line_is_joined():
    # LS17 Q4284: 'Arunachal' / 'Pradesh'.
    rows = [data(1, "Arunachal", 302, 10), ["", "Pradesh", "", "", ""]] + rows_for(NAMES[:10], start=2)
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: r["analysed"] for r in groups[0].rows}["Arunachal Pradesh"] == 302


def test_name_split_with_numbers_on_second_line_is_joined():
    # LS17 Q4284: 'Madhya' (stray value in the last column) / 'Pradesh' (the figures).
    rows = [["1", "Madhya", "", "", "252"], ["", "Pradesh", "5461", "609", ""]] + rows_for(NAMES[:10], start=2)
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: (r["analysed"], r["found"]) for r in groups[0].rows}["Madhya Pradesh"] == (5461, 609)


def test_name_split_over_three_lines_is_joined():
    # LS17 Q4933: 'Dadra Nagar' / 'Haveli & Daman' / '& Diu'.
    rows = rows_for(NAMES[:10]) + [["11", "Dadra Nagar", "58", "6", "0"], ["", "Haveli & Daman", "", "", ""], ["", "& Diu", "", "", ""]]
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert "Dadra and Nagar Haveli and Daman and Diu" in {r["state"] for r in groups[0].rows}


def test_recognised_name_extended_by_an_and_line_is_the_merged_ut():
    # Reviewer finding: 'Dadra & Nagar Haveli' + 'and Daman & Diu' was stored as the
    # pre-2020 UT, dropping the orphan line.
    rows = rows_for(NAMES[:10]) + [["11", "Dadra & Nagar Haveli", "58", "6", "0"], ["", "and Daman & Diu", "", "", ""]]
    groups, rejects = parse(table(rows))
    assert rejects == []
    states = {r["state"] for r in groups[0].rows}
    assert "Dadra and Nagar Haveli and Daman and Diu" in states and "Dadra and Nagar Haveli" not in states


def test_first_state_with_a_split_name_is_not_swallowed_into_the_header():
    rows = [["1", "Andaman &", "850", "4", "1"], ["", "Nicobar Islands", "", "", ""]] + rows_for(NAMES[:10], start=2)
    groups, rejects = parse(table(rows))
    assert rejects == []
    assert {r["state"]: r["analysed"] for r in groups[0].rows}["Andaman and Nicobar Islands"] == 850


def test_split_name_where_both_lines_carry_the_same_cell_rejects():
    rows = [["1", "Arunachal", "302", "10", "1"], ["", "Pradesh", "999", "", ""]] + rows_for(NAMES[:10], start=2)
    groups, rejects = parse(table(rows))
    assert groups == [] and reasons(rejects)[0].startswith("split_row_conflict")


def test_column_number_row_is_not_mistaken_for_a_state_row():
    idx = ["1", "2", "3", "4", "5"]     # '(1) (2) (3)' index row under the header
    groups, rejects = parse(PageTable(1, [TITLE, HEADER, idx] + with_total(ROWS)))
    assert rejects == [] and len(groups[0].rows) == 12


# ---------------------------------------------------------------- whole-table skips

def test_milk_only_table_is_skipped():
    title = ["Annual Public Laboratory Testing Report for Milk for the year 2016-17", "", "", "", ""]
    groups, rejects = parse(table(ROWS, title=title))
    assert groups == [] and reasons(rejects) == ["commodity_specific"]


def test_scope_stated_only_in_the_question_subject_is_honoured():
    # LS17 Q3076: packaged drinking water — the table itself says nothing.
    groups, rejects = parse(table(with_total(ROWS)), subject="FSSAI Licence to Packaged Drinking Water")
    assert groups == [] and reasons(rejects) == ["commodity_specific"]


@pytest.mark.parametrize("word", ["khoya", "chilli powder", "ice cream", "sugar", "bakery"])
def test_more_commodity_words_are_recognised(word):
    groups, rejects = parse(table(with_total(ROWS), above=f"Samples of {word} for 2018-19 are below."))
    assert groups == [] and reasons(rejects) == ["commodity_specific"]


def test_commodity_words_match_whole_words_only():
    # 'instead' contains 'tea', 'price' contains 'rice' — must not trigger.
    groups, rejects = parse(table(with_total(ROWS), title=None,
                                  above="Instead of the old price list, figures for 2018-19 are given below."))
    assert rejects == [] and len(groups) == 1


@pytest.mark.parametrize("marker", [
    "(upto November 2024)", "(up to 30.11.2024)", "(April to September 2023)", "(Apr - Sep)", "(till 31.10.2019)",
    "(Provisional)", "(first six months)", "Half yearly report", "uptoNovember2024",
])
def test_part_year_and_provisional_tables_are_skipped(marker):
    # Reviewer finding: only 'upto Sep' / 'upto Dec' were caught; the rest were
    # stored as full fiscal years.
    groups, rejects = parse(table(with_total(ROWS), title=None, above=f"Figures for 2024-25 {marker} are below."))
    assert groups == [] and reasons(rejects) == ["partial_period"]


def test_partial_period_marker_in_the_title_is_caught():
    title = ["Half yearly Public Laboratory Testing Report for the year 2017-18", "", "", "", ""]
    groups, rejects = parse(table(ROWS, title=title))
    assert groups == [] and reasons(rejects) == ["partial_period"]


def test_no_fiscal_year_anywhere_rejects():
    groups, rejects = parse(table(with_total(ROWS), title=None, above="No year is named here."))
    assert groups == [] and reasons(rejects) == ["fy_ambiguous"]


def test_two_fiscal_years_in_the_text_above_is_ambiguous():
    groups, rejects = parse(table(with_total(ROWS), title=None, above="Compare 2018-19 with 2019-20 below."))
    assert groups == [] and reasons(rejects) == ["fy_ambiguous"]


# ---------------------------------------------------------------- continuation across pages

def test_table_continued_on_next_page_is_joined_and_totalled():
    # LS17 Q2236: header on page 3, the last states + Total on page 4 (no header).
    first = table(ROWS[:6], page=3)
    rest = PageTable(4, ROWS[6:] + [total_row(*sums(ROWS))])
    groups, rejects = parse(first, rest)
    assert rejects == [] and len(groups[0].rows) == 12 and groups[0].verification == "total_row_sum"


def test_repeated_header_on_next_page_continues_the_group():
    # LS17 Q4284 p5: header repeated, no year of its own.
    first = table(ROWS[:6], page=3)
    rest = PageTable(4, [HEADER] + ROWS[6:] + [total_row(*sums(ROWS))])
    groups, rejects = parse(first, rest)
    assert rejects == [] and len(groups[0].rows) == 12 and groups[0].verification == "total_row_sum"


def test_continuation_with_a_serial_gap_is_not_joined():
    first = table(ROWS[:10], page=3)
    rest = PageTable(4, [data(19, "Mizoram", 50, 5), data(20, "Nagaland", 150, 20)])
    groups, _ = parse(first, rest)
    assert len(groups[0].rows) == 10


def test_continuation_on_a_non_adjacent_page_is_not_joined():
    first = table(ROWS[:10], page=3)
    rest = PageTable(6, [data(11, "Mizoram", 50, 5), data(12, "Nagaland", 150, 20)])
    groups, _ = parse(first, rest)
    assert len(groups[0].rows) == 10


def test_bare_total_tail_that_does_not_reconcile_rejects_the_group():
    # Reviewer finding: it used to be ignored, so a group missing its tail rows
    # passed as merely row-checked. A closing Total that fails to reconcile means
    # rows are missing.
    first = table(ROWS, page=3)
    stray = PageTable(4, [total_row(99999, 88888)])
    groups, rejects = parse(first, stray)
    assert groups == [] and reasons(rejects) == ["total_mismatch"]


def test_bare_total_tail_that_reconciles_is_attached():
    first = table(ROWS, page=3)
    tail = PageTable(4, [total_row(*sums(ROWS))])
    groups, rejects = parse(first, tail)
    assert rejects == [] and groups[0].verification == "total_row_sum"


def test_bare_total_tail_with_unreadable_figures_rejects_the_group():
    first = table(ROWS, page=3)
    groups, rejects = parse(first, PageTable(4, [["", "Total", "12345", "-", ""]]))
    assert groups == [] and reasons(rejects) == ["total_unusable"]


def test_unresolvable_header_on_the_continuing_page_rejects_the_group():
    # Reviewer finding: an abbreviated repeated header (columns possibly swapped)
    # was joined using the previous table's column positions.
    first = table(ROWS[:6], page=3)
    abbreviated = ["No.", "State", "Analysed", "Found", "Cases"]
    rest = PageTable(4, [abbreviated] + ROWS[6:])
    groups, rejects = parse(first, rest)
    assert groups == [] and reasons(rejects) == ["continuation_header_unresolved"]


def test_failed_continuation_discards_the_whole_group():
    first = table(ROWS[:10], page=3)
    bad = PageTable(4, [data(11, "MPraandiepsuhr", 50, 5)])
    groups, rejects = parse(first, bad)
    assert groups == [] and reasons(rejects)[0].startswith("continuation_")


# ---------------------------------------------------------------- one question, two tables

def test_two_tables_for_the_same_year_and_basis_in_one_question_are_both_rejected():
    a = table(with_total(ROWS), page=2)
    b = table(with_total(ROWS), page=5)
    groups, rejects = parse(a, b)
    assert groups == [] and reasons(rejects) == ["duplicate_period_in_question"] * 2


def test_different_years_in_one_question_are_both_kept():
    t16 = ["Annual Public Laboratory Testing Report for the year 2016-2017", "", "", "", ""]
    groups, rejects = parse(table(with_total(ROWS), page=2), table(with_total(ROWS), page=5, title=t16))
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
    ("Dadra & Nagar Haveli and Daman & Diu", "Dadra and Nagar Haveli and Daman and Diu"),
])
def test_historical_state_name_variants_resolve(raw, canon):
    from pipeline.sources import loksabha_qa as LQ
    assert LQ._canon_state(raw) == canon


def test_pre_2020_uts_are_not_collapsed_into_the_merged_ut():
    from pipeline.sources import loksabha_qa as LQ
    assert LQ._canon_state("Daman & Diu") != LQ._canon_state("Dadra & N.H")


def test_impossible_answer_dates_become_null_instead_of_failing_the_insert():
    from pipeline.sources import loksabha_qa as LQ
    assert LQ._parse_date("13.03.2026") == "2026-03-13"
    assert LQ._parse_date("31.02.2026") is None
    assert LQ._parse_date("garbage") is None and LQ._parse_date(None) is None


# ---------------------------------------------------------------- database layer (fake connection)

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
    return {"lokNo": "17", "quesNo": str(no), "date": "13.03.2026", "subjects": "Food adulteration",
            "questionsFilePath": f"https://sansad.in/{no}.pdf"}


def test_ingest_replaces_a_questions_rows_in_one_transaction():
    groups, _ = parse(table(with_total(ROWS)))
    conn = _Conn()
    n = S.ingest_groups(conn, _question(), groups)
    verbs = [entry[0].split()[0] for entry in conn.log]
    assert verbs[0] == "DELETE" and verbs.count("INSERT") == n == 12 and conn.commits == 1


def test_a_question_that_now_yields_nothing_still_clears_its_old_rows():
    # A stricter parser version must not leave its predecessor's mistakes behind.
    conn = _Conn()
    assert S.ingest_groups(conn, _question(), []) == 0
    assert conn.log[0][0].startswith("DELETE FROM state_sampling_annual") and conn.commits == 1


def test_processed_keys_is_a_single_query():
    conn = _Conn(fetch=[(17, 1), (17, 2)])
    assert S.processed_keys(conn) == {(17, 1), (17, 2)} and len(conn.log) == 1


def test_one_bad_question_does_not_abort_the_run(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(S, "pg_connect", lambda: conn)
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    monkeypatch.setattr(S.LQ, "discover_questions", lambda terms=None: [_question(1), _question(2), _question(3)])
    monkeypatch.setattr(S.LQ, "_download", lambda url: b"pdf")
    monkeypatch.setattr(S, "extract_tables", lambda pdf: [table(with_total(ROWS))])
    real_ingest = S.ingest_groups

    def flaky(c, q, groups):
        if q["quesNo"] == "2":
            raise RuntimeError("database hiccup")
        return real_ingest(c, q, groups)
    monkeypatch.setattr(S, "ingest_groups", flaky)

    summary = S.run()

    assert summary["questions_processed"] == 2 and summary["fetch_errors"] == 1 and summary["inserted"] == 24
    assert conn.rollbacks == 1


def test_a_question_with_no_url_is_logged_not_silently_skipped(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(S, "pg_connect", lambda: conn)
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    q = _question(9); q["questionsFilePath"] = ""
    monkeypatch.setattr(S.LQ, "discover_questions", lambda terms=None: [q])

    summary = S.run()

    assert summary["fetch_errors"] == 1 and any("loksabha_question_log" in e[0] for e in conn.log)


def test_an_already_processed_question_is_skipped_and_noted(monkeypatch):
    conn = _Conn(fetch=[(17, 1)])
    monkeypatch.setattr(S, "pg_connect", lambda: conn)
    monkeypatch.setattr(S.LQ, "discover_questions", lambda terms=None: [_question(1)])

    summary = S.run()

    assert summary["questions_skipped_already_done"] == 1 and summary["inserted"] == 0
    assert "nothing new" in summary["note"]
