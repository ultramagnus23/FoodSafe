# State-wise sampling outcomes (Lok Sabha) — method, validation, limits

**Module:** `pipeline/sources/loksabha_sampling.py`
**Table:** `state_sampling_annual` (+ audit log `loksabha_question_log`), `schema_migration_019.sql`
**API:** `GET /v1/meta/state-sampling` · **UI:** Directory → "Samples Tested & Found Non-Conforming"
**Run:** `python -m pipeline.run_and_log loksabha_sampling` (daily in `ingest.yml`)
**Tests:** `tests/test_loksabha_sampling.py` (109 cases; each rejection rule is pinned to the real PDF failure that motivated it)

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
| Printed Total must equal column sums (a near-match is flagged `total_row_close`, see below) | missing/misread rows |
| No printed Total **and** no serials → reject | nothing supports the figures |
| Fiscal year from the table's own title (strong) or the text directly above (weaker, marked †); exactly one year or reject | wrong-year attribution |
| Milk/other commodity-specific and part-year tables skipped | mixing scopes |
| Multi-page tables joined only when serials continue exactly | attaching an unrelated table |
| Two tables for the same year+basis in one answer → both rejected | ambiguity |
| *(sampling-2, from an independent code review; each reproduced before fixing)* | |
| "Found" column must be non-conforming **or** adulterated, never both; `analysed ≠ found`; "found to be" spelled with or without spaces | column mixups; `found == analysed` when one header matched twice |
| Number cells parsed with a strict grouped-integer grammar; `5461 609` is rejected, not read as 5,461,609 | two fused cells silently concatenated |
| An unusable printed Total (present but unparseable) rejects the table instead of being treated as absent | verification silently downgraded |
| `total_row_close` requires each column within 0.1% **and** within 10 samples (0.1% alone could hide a missing small state on a large national sum); ≥ 10 states required | a dropped state passing as "close" |
| Part-year ("April–September …") detected even when the PDF squashes the words | half-year table read as a full year |
| Serial column must start at 1 and continue exactly; a stray text line inside a table rejects it | orphan/misattached rows |
| Multi-page tables: a bare "Total" tail must agree with the joined rows; header-less continuation only when serials continue | continuation attached to the wrong table |
| One question failing (bad PDF, parser exception) rolls back only that question; rows are replaced (delete then insert, one commit) when a question is reprocessed under a new parser version | one bad answer aborting the run; stale rows after a rule change |

`verification` on each row records what supports it: `total_row_sum`,
`total_row_close`, or `row_invariants` (serials + row checks only, no printed
total — the weakest tier, shown as such in the UI).

## Validation (2026-09-19, against the 124 unparsed answers; re-run at `sampling-2`)

* 16 tables accepted → **539 state-year rows**; 9 tables exactly match their
  printed Total, 2 within 0.1%, 5 by row checks only. (Those tier counts are from the
  first, `sampling-1`, run; the `sampling-2` re-run accepts the same 16 tables and 539
  rows with **zero differing values** — the added rules rejected nothing that was
  previously good, and they are pinned by tests against constructed failures.)
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

The latest run (`sampling-2`, same 124 answers) accepted 16 tables and rejected
54, plus 1 single row dropped for found > analysed. Rejection reasons, exactly as
counted in that run:

| Reason | Tables |
|---|---|
| no recognisable state column | 15 |
| unrecognised / garbled state name | 8 |
| commodity-specific (milk etc.) | 7 |
| malformed number cell | 6 |
| ambiguous column headers | 4 |
| found-column split across sub-headers | 3 |
| malformed serial cell | 3 |
| split-name row conflict | 2 |
| part-year, printed total mismatch, no total *and* no serials, state row without serial, malformed continuation number, serial does not start at 1 | 1 each |

(The `sampling-1` write-up counted 57 rejections; the reason taxonomy was tightened
and more commodity words are now recognised, so per-reason counts are not directly
comparable — the accepted set is identical.)

The 15 "no state column" tables were not individually audited; many appear to be
national year-by-year tables (a different grain, see below). Every rejection is
written to `loksabha_question_log.reject_detail` (JSONB) so it can be audited or
recovered by a later parser version.

## First production run (2026-09-18)

`ingest.yml` step "Refresh Lok Sabha State-wise sampling outcomes": 135 questions
discovered, 127 processed, **16 tables accepted, 539 rows inserted** — identical
to the local dry run — and 58 tables rejected. 8 questions could not be fetched
(5 URLs returned something that is not a valid PDF; 3 had no URL) and are logged
as `fetch_error`, which the runner retries on every run instead of treating as
done. This step is `continue-on-error`, so its green check is not evidence on its
own; the row counts above come from reading the job log after the run finished.
The skip-already-processed path (every run after the first inserting 0) is unit-
and scratch-DB-tested but had not yet been observed in production at the time of
writing.

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
* National year-by-year tables (LS18 Q737/Q2149/Q1956/Q4604/Q985, LS17
  Q1385/Q2995/Q3357) carry the same two counts nationally back to 2014-15 and are
  **not yet ingested** (different grain; would also let state sums be checked
  automatically). A 2026-09-19 survey of 15 such tables found traps that make a
  generic parser riskier than it looks — record them before trying:
  * a serial-number column leaks into "the first two numbers" (`[1, 107829,
    28347]`), so columns must come from headers, not position;
  * **single-state tables look national** (LS18 Q2281/Q3418 are Maharashtra
    only; "for Maharashtra" was invisible to a word-boundary match because the
    PDF glued the words together);
  * **scope is often not in the table** — LS17 Q3076 (2,977 samples analysed in
    2013-14 against ~72,000 nationally) is packaged drinking water, which only
    the question *subject* reveals, so scope checks must include it;
  * **vintages disagree**: 2021-22 samples analysed is 165,381 in LS17 Q1385 but
    144,345 in four other answers, 2022-23 non-conforming is 44,421 vs 44,626,
    and 2018-19 is 85,172 in an early-2019 answer vs 106,459 (the FSSAI Annual
    Report figure) later — so every answer must be kept and marked, never merged.
* The 15th Lok Sabha and earlier (Prevention of Food Adulteration Act era) were
  not examined. Only Health & Family Welfare questions are searched.
* Parser version is `sampling-2`. Bump `PARSER_VERSION` when rules change: the
  runner re-processes questions logged under an older version and skips the rest,
  so daily runs after the first insert nothing (`loksabha_sampling` is in
  `EXPECTED_EMPTY_SOURCES`).

## Relevance to the model and the paper

* **Backtest:** run and written up in `docs/BACKTEST_SAMPLING.md` — state
  identity carries stable information about the non-conforming rate (persistence
  MAE 0.048 vs 0.131 for the national rate), but no model beat plain persistence
  and the persistence may reflect enforcement practice rather than food risk.
* **Paper B:** the barrier is FSSAI's own channels specifically; the same
  numbers are recoverable, painfully, from Parliament — and doing so required
  rejecting most of what the PDFs contain. That is a finding about the cost of
  the current access regime, not a data-availability success.
