"""
Tests for models/backtest_sampling.py. Synthetic worlds with known answers: if
the machinery is right, persistence must win where state effects are real and
lose where they are pure noise, and no forecast may depend on the year it is
predicting or on any later year.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from models import backtest_sampling as B

STATES = [f"S{i:02d}" for i in range(30)]
YEARS = ["2016-2017", "2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]


def row(state, fy, n, k, basis="non_conforming"):
    return {"state": state, "fiscal_year": fy, "samples_analyzed": n, "samples_non_conforming": k, "non_conforming_basis": basis}


def world(true_rate, n=2000, seed=1, years=YEARS):
    """rows where each state's count is Binomial(n, true_rate[state])."""
    rng = np.random.default_rng(seed)
    return [row(s, fy, n, int(rng.binomial(n, true_rate[s]))) for s in STATES for fy in years]


# ---------------------------------------------------------------- panel

def test_prev_fy():
    assert B.prev_fy("2020-2021") == "2019-2020"


def test_prev_fy_rejects_garbage():
    with pytest.raises(ValueError):
        B.prev_fy("2020-21")


def test_only_the_requested_definition_is_used():
    rows = [row("A", "2016-2017", 100, 10), row("A", "2015-2016", 100, 50, basis="adulterated_misbranded")]
    panel, _ = B.build_panel(rows)
    assert panel == {("A", "2016-2017"): (100, 10)}


def test_identical_repeats_collapse_and_conflicts_are_dropped():
    rows = [row("A", "2016-2017", 100, 10), row("A", "2016-2017", 100, 10),      # same figure twice -> one cell
            row("B", "2016-2017", 100, 10), row("B", "2016-2017", 100, 12)]      # conflicting -> dropped
    panel, conflicts = B.build_panel(rows)
    assert panel == {("A", "2016-2017"): (100, 10)} and conflicts == [("B", "2016-2017")]


def test_pairs_require_consecutive_years():
    panel = {("A", "2016-2017"): (500, 50), ("A", "2018-2019"): (500, 60)}       # 2017-18 missing
    assert B.make_pairs(panel) == []


def test_pairs_require_min_samples_in_both_years():
    panel = {("A", "2016-2017"): (50, 5), ("A", "2017-2018"): (500, 60),
             ("B", "2016-2017"): (500, 50), ("B", "2017-2018"): (99, 9),
             ("C", "2016-2017"): (500, 50), ("C", "2017-2018"): (500, 60)}
    assert [p.state for p in B.make_pairs(panel, min_n=100)] == ["C"]


# ---------------------------------------------------------------- forecasts

def test_forecast_endpoints():
    p = B.Pair("A", "2017-2018", n0=200, k0=50, n1=200, k1=60)
    assert B.forecast(p, 0.30, 0.0) == pytest.approx(0.25)                 # persistence
    assert B.forecast(p, 0.30, math.inf) == pytest.approx(0.30)            # national
    mid = B.forecast(p, 0.30, 200.0)
    assert 0.25 < mid < 0.30                                               # shrinks toward national


def test_forecast_is_clipped_away_from_certainty():
    p = B.Pair("A", "2017-2018", n0=100, k0=0, n1=100, k1=5)
    assert B.forecast(p, 0.2, 0.0) == pytest.approx(B.EPS)
    assert math.isfinite(B.deviance(5, 100, B.forecast(p, 0.2, 0.0)))


def test_choose_m_prefers_the_larger_value_on_a_tie():
    pairs = [B.Pair("A", "2017-2018", 100, 25, 100, 25), B.Pair("B", "2017-2018", 100, 25, 100, 25)]
    nat = {"2017-2018": 0.25}                       # every model predicts 0.25 -> all tie
    assert B.choose_m(pairs, nat) == math.inf


# ---------------------------------------------------------------- known-answer worlds

def test_persistence_wins_when_state_effects_are_real():
    rng = np.random.default_rng(7)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.10, 0.60, len(STATES)))}
    res = B.run(world(true, n=2000))
    d = res["paired_logloss_differences_(negative=first_is_better)"]
    assert res["pooled"]["logloss_persistence"] < res["pooled"]["logloss_national"]
    assert d["persistence_minus_national"]["ci95"][1] < 0            # significantly better
    assert res["mean_spearman_persistence"] > 0.8                    # the ordering persists


def test_national_beats_persistence_when_states_are_identical_noise():
    true = {s: 0.25 for s in STATES}
    res = B.run(world(true, n=300, seed=3))
    d = res["paired_logloss_differences_(negative=first_is_better)"]
    assert res["pooled"]["logloss_national"] < res["pooled"]["logloss_persistence"]
    assert d["persistence_minus_national"]["ci95"][0] > 0            # persistence is significantly worse
    # ...and the fitted shrinkage learns to ignore the state signal.
    assert all(y["m_selected"] >= 1000 for y in res["per_year"])


def test_shrink_is_never_much_worse_than_the_better_endpoint():
    rng = np.random.default_rng(11)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.15, 0.45, len(STATES)))}
    rows = world(true, n=150, seed=5)
    res = B.run(rows)
    p = res["pooled"]
    best_endpoint = min(p["logloss_national"], p["logloss_persistence"])
    assert p["logloss_shrink"] <= best_endpoint + 0.01


# ---------------------------------------------------------------- no leakage

def _pairs_for(rows):
    panel, _ = B.build_panel(rows)
    return B.make_pairs(panel)


def test_forecast_for_year_t_ignores_year_t_outcomes():
    rng = np.random.default_rng(2)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.1, 0.6, len(STATES)))}
    rows = world(true)
    base = B.evaluate(_pairs_for(rows))
    target = "2020-2021"
    tampered = [dict(r, samples_non_conforming=r["samples_analyzed"] // 2) if r["fiscal_year"] == target else r for r in rows]
    alt = B.evaluate(_pairs_for(tampered))
    b = {y["fy"]: y for y in base["per_year"]}
    a = {y["fy"]: y for y in alt["per_year"]}
    # The year-t outcomes changed, so its losses differ ...
    assert a[target]["logloss_persistence"] != b[target]["logloss_persistence"]
    # ... but the forecast inputs for year t (national rate from t-1, chosen m) do not.
    assert a[target]["m_selected"] == b[target]["m_selected"]
    assert a[target]["national_rate_prev"] == b[target]["national_rate_prev"]


def test_chosen_m_for_year_t_ignores_later_years():
    rng = np.random.default_rng(4)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.1, 0.6, len(STATES)))}
    rows = world(true)
    base = B.evaluate(_pairs_for(rows))
    target = "2020-2021"
    later = [dict(r, samples_non_conforming=r["samples_analyzed"] // 3) if r["fiscal_year"] > "2021-2022" else r for r in rows]
    alt = B.evaluate(_pairs_for(later))
    b = {y["fy"]: y for y in base["per_year"]}
    a = {y["fy"]: y for y in alt["per_year"]}
    assert a[target]["m_selected"] == b[target]["m_selected"]
    assert a[target]["logloss_shrink"] == b[target]["logloss_shrink"]


def test_first_target_year_is_used_for_fitting_only():
    rng = np.random.default_rng(6)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.1, 0.6, len(STATES)))}
    res = B.run(world(true))
    all_targets = sorted({p.fy for p in _pairs_for(world(true))})
    assert res["evaluated_target_years"] == all_targets[1:]


# ---------------------------------------------------------------- misc

def test_bootstrap_is_deterministic():
    rng = np.random.default_rng(9)
    true = {s: float(r) for s, r in zip(STATES, rng.uniform(0.1, 0.6, len(STATES)))}
    rows = world(true)
    assert B.run(rows) == B.run(rows)


def test_too_little_data_reports_nothing_evaluable_instead_of_inventing_a_result():
    rows = [row("A", "2016-2017", 500, 50), row("A", "2017-2018", 500, 60)]      # one target year only
    res = B.run(rows)
    assert res["evaluated_pairs"] == 0 and "note" in res


def test_spearman_handles_ties_and_constants():
    assert B.spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert B.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert B.spearman([1, 1, 1], [1, 2, 3]) is None
    assert B.spearman([1, 2], [1, 2]) is None
    assert B.spearman([1, 1, 2, 3], [1, 1, 2, 3]) == pytest.approx(1.0)
