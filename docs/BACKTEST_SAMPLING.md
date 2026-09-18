# Backtest on real state sampling outcomes

**Module:** `models/backtest_sampling.py` · **Tests:** `tests/test_backtest_sampling.py` (18 cases)
**Data:** `state_sampling_annual` (`docs/LOKSABHA_SAMPLING.md`) — real State/UT × fiscal-year
counts of samples analysed (n) and found non-conforming (k), from Lok Sabha answers.
**Re-run:** `python -m models.backtest_sampling` (`--json` for the full result). Not scheduled;
re-run when the panel changes.
**Results below:** computed 2026-09-19 on the 539 rows loaded by the first production run.

This is the first evaluation in the project on data with a pass side. It supersedes
the "not meaningful" verdict in `docs/BACKTEST_REPORT.md` *for this question only*; that
report's verdict on the openFDA recall log stands.

## Question

Does a State/UT's non-conforming rate in year *t−1* predict its rate in year *t* better
than just using the national rate? This is a question about **persistence of a sampled
testing rate**, not about food risk (see "What this does not show").

## Protocol (fixed before any result was seen)

* Only the `non_conforming` definition (the older `adulterated_misbranded` is a different
  quantity). A (state, year) cell with conflicting figures across answers would be dropped;
  none were (0 of 344).
* Forecasting pairs: (state, *t−1*) → (state, *t*) for **consecutive** fiscal years only,
  ≥ 100 samples in both. 2017-18 and 2019-20 are absent from the data, so nothing pairs
  across them. Result: 196 pairs, 7 target years.
* Models, each using year *t−1* data only:
  `national` (no state signal) · `persistence` (the state's own *t−1* rate) ·
  `shrink` `p = (k₀ + m·national₀)/(n₀ + m)` — m = 0 is persistence, m = ∞ is national.
* `m` is chosen from a fixed grid using **only earlier target years** (expanding window).
  The first target year is used for fitting only, so 173 pairs across 6 target years
  (2016-17, 2021-22 … 2025-26) are evaluated. A leakage test confirms altering the
  target year's outcomes, or any later year's, changes neither the fitted `m` nor the
  national rate used for that year.
* Primary metric: pooled binomial log-loss. Secondary: unweighted MAE of the rate, and
  within-year Spearman correlation of predicted vs realised state rates (does the
  *ordering* of states persist, independent of national level shifts?).
* Uncertainty: 2,000-draw bootstrap over **states** (the dependent unit), fixed seed.

## Results

| | national | persistence | shrink |
|---|---|---|---|
| pooled log-loss | 0.515 | **0.440** | **0.440** |
| MAE of the rate | 0.132 | **0.048** | 0.050 |

Paired pooled log-loss differences (negative = first model better), 95% CI:

| comparison | estimate | 95% CI |
|---|---|---|
| persistence − national | −0.075 | [−0.139, −0.024] |
| shrink − national | −0.076 | [−0.139, −0.024] |
| shrink − persistence | −0.0003 | [−0.0012, +0.0003] |

Mean within-year Spearman (persistence): **0.85** (range 0.69–0.95 across the six years).
Persistence beat national in every evaluated year. Fitted `m` was 30–300 (weak
shrinkage — state sample sizes are in the thousands, so their own history is informative).

Sensitivity (explicitly *not* used to choose anything):

| variant | persistence − national [95% CI] | MAE nat / pers |
|---|---|---|
| primary | −0.075 [−0.139, −0.024] | 0.132 / 0.048 |
| ≥ 500 samples | −0.076 [−0.141, −0.026] | 0.120 / 0.039 |
| ≥ 1,000 samples | −0.076 [−0.140, −0.025] | 0.118 / 0.039 |
| 2020-21 onward only | −0.077 [−0.146, −0.024] | 0.133 / 0.046 |
| large states only | −0.076 [−0.138, −0.025] | 0.121 / 0.049 |
| **placebo:** state labels shuffled within year | **+0.104** [−0.003, +0.260] | 0.126 / 0.129 |

The placebo is the control: with state identity destroyed, persistence loses its edge
(rank correlation −0.07), so the advantage is not an artefact of the machinery. The
same run on synthetic worlds with known answers (tests) behaves correctly —
persistence wins where state effects are real, loses where they are pure noise.

## What this shows

State identity carries **stable** information about the share of tested samples found
non-conforming. Last year's state rate predicts this year's to within ~5 percentage
points on average, versus ~13 for the national rate, and the state *ordering* is highly
persistent (measured, non-conforming definition, 2014-15 → 2025-26: Uttar Pradesh
42–61% in every year, Gujarat 6–11%, Maharashtra 12–27%, Kerala 11–26%).
Robust to the sample-size threshold, era, and state mix.

## What this does NOT show

* **Not food risk.** Samples are drawn by inspectors, often on suspicion, and the
  non-conforming category includes labelling and sub-standard findings. A persistent
  state rate can reflect *enforcement and sampling practice* as much as contamination,
  and this data cannot separate them. Do not present it as "unsafe food by state".
* **No model beat persistence.** Shrinkage ties it. There is no evidence here that a
  learned model adds anything over "use last year's rate", and with ~6 evaluable years ×
  ~30 states, a richer model could not be justified on this data alone.
* **The national level is not predicted.** It moved between ~18% and ~26% across the
  evaluated years; every model here just carries last year's national rate forward.
* Short and gappy: 2017-18 and 2019-20 are missing, the 2016-17 target rests on
  2015-16 and 2016-17 tables that come from a single answer (LS17 Q1058), and tables
  that failed parsing are missing **not at random**
  (`docs/LOKSABHA_SAMPLING.md` lists what was rejected).
* Pairs are filtered on sample size in both years (a sample-size, not outcome, filter).
* Small UTs and the 2020 UT merger break state identity for a few units; they mostly
  fall out of the pairs naturally.

## Possible next steps (not done)

Test whether observable state characteristics explain the persistent differences —
e.g. testing capacity from `labs`, or the State Food Safety Index components
(`docs/REACHABLE_TEXT_INVENTORY.md`, not yet ingested) — which would speak to
*why* states differ. Ingesting the national year-by-year tables would also let the
national level be modelled and state sums be checked automatically.
