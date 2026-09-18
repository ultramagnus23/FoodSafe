# State-wise sampling outcomes (Lok Sabha) — method, validation, limits

**Module:** `pipeline/sources/loksabha_sampling.py`
**Table:** `state_sampling_annual` (+ audit log `loksabha_question_log`), `schema_migration_019.sql`
**API:** `GET /v1/meta/state-sampling` · **UI:** Directory → "Samples Tested & Found Non-Conforming"
**Run:** `python -m pipeline.run_and_log loksabha_sampling` (daily in `ingest.yml`)
**Tests:** `tests/test_loksabha_sampling.py` (65 cases; each rejection rule is pinned to the real PDF failure that motivated it)

## What this is, and why it matters

Real State/UT × fiscal-year counts of food samples **analysed** and how many were
**found non-conforming**, disclosed in Lok Sabha written answers (sansad.in),
2013-14 to 2025-26. It is the only source in this project with *both* outcomes:
`docs/BACKTEST_REPORT.md` found that every openFDA record is a recall (a
failure), so no discrimination metric could be computed. Here the pass side is
`analysed − non-conforming`.

`pipeline/sources/loksabha_qa.py` deliberately handles four *other* metrics and
matched only 3 of 135 answers across the 16th–18th Lok Sabha; this module
handles the table shape those parsers reject.

## What it is NOT

* Not a sample of India: it is what state labs tested, chosen by inspectors
  (typically suspicion-driven), so a high rate is **not** a prevalence estimate.
* A *non-conforming* sample is not necessarily *unsafe* — the category includes
  sub-standard and labelling findings.
* Two definitions are stored apart and must never be pooled:
  `non_conforming` ("found non-conforming", recent) and `adulterated_misbranded`
  (older answers, through ~2016-17). A rate series that crosses that change is
  not like-for-like.
* Not FSSAI's own channel. Access is through Parliament; FSSAI/FoSCoS remain
  closed (see `docs/FSSAI_INGESTION.md`, `docs/RTI_DRAFT.md`).

## Why the parser is strict

These PDFs extract badly. Observed in the real files: two states fused into one
row (`Karnataka/Kerala`, `2837/1784`), a Total fused into the last state row,
serial cells reading `10. 11.`, state names split over 2–3 lines with the
figures on either line, interleaved characters (`MPraandiepsuhr`), name rows
separated from their figures so every value shifts one state, and merged headers
whose "found" column is only one of several sub-columns. A lenient parser
produces plausible-looking wrong numbers, so a table is **accepted only if every
check passes and otherwise rejected whole, with a logged reason**:

| Check | Real failure it guards against |
|---|---|
| Exactly one *samples analysed* and one *found …* column, from header text | wrong column silently chosen |
| Merged "found" header over sub-columns → reject | LS17 Q2236/Q4933 2021-22: read 8,423, true 32,935 |
| Every numeric cell one clean integer | fused rows, `Rs.` amounts |
| Every numeric row has a recognised State/UT | interleaved-character garbage |
| Name row without a serial, or any serial gap → reject | LS17 Q2901: all 15 states shifted by one |
| found ≤ analysed (offending row dropped, still counted in the total) | LS18 Q3270 Mizoram |
| Printed Total must equal column sums (0.1% tolerance is flagged `total_row_close`) | missing/misread rows |
| No printed Total **and** no serials → reject | nothing supports the figures |
| Fiscal year from the table's own title (strong) or the text directly above (weaker, marked †); exactly one year or reject | wrong-year attribution |
| Milk/other commodity-specific and part-year tables skipped | mixing scopes |
| Multi-page tables joined only when serials continue exactly | attaching an unrelated table |
| Two tables for the same year+basis in one answer → both rejected | ambiguity |

`verification` on each row records what supports it: `total_row_sum`,
`total_row_close`, or `row_invariants` (serials + row checks only, no printed
total — the weakest tier, shown as such in the UI).

## Validation (2026-09-19, against the 124 unparsed answers)

* 16 tables accepted → **539 state-year rows**; 9 tables exactly match their
  printed Total, 2 within 0.1%, 5 by row checks only.
* **Cross-answer agreement: 105 of 105** (state, year) cells reported by two or
  more independent answers are identical. Before the alignment and split-header
  guards this was 97 of 141 — 44 conflicts, which is how the LS17 Q2901 shift and
  the sub-column problem were found. The row-level checks alone did **not** catch
  them; only the cross-answer comparison did.
* **State sums equal independently published national totals** for 2015-16
  (72,499 / 16,133), 2016-17 (78,340 / 18,325), 2020-21 (107,829 / 28,347),
  2022-23 (177,511 / 44,626) and 2023-24 (170,513 / 33,808) — national figures
  from *different* answers — and 2018-19 (106,459) matches the FSSAI Annual
  Report figure recorded in `pipeline/sources/fssai_annual_report.py`.
* Small source-side disagreements exist and are preserved, not smoothed:
  e.g. 2021-22 national non-conforming is 32,934 in three answers but the LS18
  Q3270 table totals 32,935; 2024-25 is 34,388 nationally vs 34,386 in the table.

## What was rejected (and why that is fine)

Across the 124 answers the parser looked at 73 tables whose headers matched a
samples-analysed/found layout: **16 accepted, 57 rejected** (and 1 single row
dropped for found > analysed). Rejections, exactly as counted in the run:

| Reason | Tables |
|---|---|
| no recognisable state column | 15 |
| unrecognised / garbled state name | 9 |
| commodity-specific (milk) | 9 |
| malformed number cell | 6 |
| malformed serial cell | 4 |
| found-column split across sub-headers | 3 |
| ambiguous column headers | 3 |
| split-name row conflict | 2 |
| printed total does not match | 2 |
| part-year, ambiguous year, no total *and* no serials, state row without serial | 1 each |

The 15 "no state column" tables were not individually audited; many appear to be
national year-by-year tables (a different grain, see below). Every rejection is
written to `loksabha_question_log.reject_detail` (JSONB) so it can be audited or
recovered by a later parser version.

## Known limits

* **Coverage is uneven.** Years present for a state depend on which answers
  passed; e.g. 2017-18 and 2019-20 state tables were all rejected. Absence of a
  state-year means "no accepted table", not "no testing".
* Some accepted tables list fewer than 36 states (a state that reported nothing
  usable is simply absent) — sums of such tables are not national totals.
* The same (state, year) can appear in several answers at different vintages
  (provisional vs revised). All are kept; the API marks each `single_source`,
  `corroborated` or `conflicting` rather than choosing one.
* 10 of the 16 accepted tables take their year from the text above the table
  (†). Five of those years are independently confirmed by national totals or by
  a second answer; treat the rest as slightly weaker.
* National year-by-year tables (LS18 Q737/Q2149, LS17 Q1385/Q2995/Q3357) carry
  the same two counts nationally back to 2013-14 and are **not yet ingested**
  (different grain; would also let state sums be checked automatically).
* The 15th Lok Sabha and earlier (Prevention of Food Adulteration Act era) were
  not examined. Only Health & Family Welfare questions are searched.
* Parser version is `sampling-1`. Bump `PARSER_VERSION` when rules change: the
  runner re-processes questions logged under an older version and skips the rest,
  so daily runs after the first insert nothing (`loksabha_sampling` is in
  `EXPECTED_EMPTY_SOURCES`).

## Relevance to the model and the paper

* **Backtest:** a real state-year backtest (predict next year's non-conforming
  rate from prior years) is now *possible in principle* — 12 fiscal years with
  uneven coverage and the definition change above. It has **not** been run;
  `docs/BACKTEST_REPORT.md` is unchanged in substance.
* **Paper B:** the barrier is FSSAI's own channels specifically; the same
  numbers are recoverable, painfully, from Parliament — and doing so required
  rejecting most of what the PDFs contain. That is a finding about the cost of
  the current access regime, not a data-availability success.
