# Backtest Report

_Generated 2026-07-07 by `models/backtest.py`._

## Scope

Evaluated against **real enforcement records only** (`etl_version != 'seed-demo'`) — never against the synthetic demo data that backs the India district/map/compare views today. Backtesting against synthetic data would produce a self-fulfilling metric with no evidentiary value.

## Data available

- **66** real records, spanning 2020-09-28 to 2026-04-23
- Source breakdown: {'usfda': 66}
- Pass/fail breakdown: {'fail': 66, 'pass': 0}
- 64 distinct commodities (max 2 records for any single commodity)

## Verdict

**NOT MEANINGFUL: every real record is a pass_fail=False recall event (0 passing samples). openFDA's enforcement/recall feed is a log of confirmed recalls, not a sampled pass/fail test set — there is no negative class to compute a Brier score or any other discrimination metric against. A real backtest needs a source with both outcomes, e.g. routine surveillance testing results, not a recall log.**

## Why this matters

The master build prompt requires evaluating the risk model against real, corroborated events with a temporal split, and publishing the result — including a null result. openFDA's food enforcement feed turns out to be a recall log (every record is a confirmed recall), not a sampled surveillance-testing dataset with both pass and fail outcomes. That structural mismatch, not a bug in the backtest code, is why no Brier score is reported here: computing one against a 100%-failure label set would be meaningless, and publishing a misleadingly precise-looking number would violate the platform's own model-honesty standard more than publishing nothing does.

## What would unblock a real backtest

A source with both outcomes for the same commodity/geography over time — e.g. routine FSSAI/state surveillance testing results (most samples pass), rather than an enforcement/recall log (which by definition only contains failures). See `docs/FSSAI_INGESTION.md` for why that data isn't reachable today.

This report is not regenerated automatically — re-run `python -m models.backtest` after real data volume changes meaningfully (e.g. a new real ingestion source comes online).

## Update 2026-09-19 — a source with both outcomes exists, and a backtest has been run on it

`state_sampling_annual` (`docs/LOKSABHA_SAMPLING.md`) holds real State/UT x fiscal-year
counts of samples analysed and found non-conforming from Lok Sabha answers, so a pass
side (`analysed - non-conforming`) exists for the first time (539 rows, 2013-14 to
2025-26, uneven coverage, two definitions that must not be pooled).

A pre-specified temporal backtest on it is in `docs/BACKTEST_SAMPLING.md`. In short:
last year's state rate predicts this year's far better than the national rate does
(MAE 0.048 vs 0.131; state ordering rank correlation 0.85; robust to thresholds and a
shuffled-label placebo), but **no model beat simple persistence**, and the persistence
may reflect enforcement and sampling practice rather than food risk. The verdict
above about the openFDA recall log is unchanged: that dataset still cannot support a
discrimination metric.
