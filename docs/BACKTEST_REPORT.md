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
