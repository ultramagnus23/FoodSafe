"""
FoodSafe India — temporal backtest on real State/UT sampling outcomes

Question: does last fiscal year's non-conforming rate for a State/UT predict
this year's better than simply using the national rate? Data:
`state_sampling_annual` (docs/LOKSABHA_SAMPLING.md) — real counts of samples
analysed (n) and found non-conforming (k) from Lok Sabha answers.

The protocol is fixed in advance and does not depend on the results:

  * Only the `non_conforming` definition is used (the older
    `adulterated_misbranded` definition is a different quantity).
  * A (state, year) cell reported with conflicting figures in different answers
    is dropped and counted; identical repeats are one cell.
  * A forecasting pair is (state, year t-1) -> (state, year t) for CONSECUTIVE
    fiscal years only (2017-18 and 2019-20 are missing, so those never pair),
    with at least `MIN_N` samples in both years.
  * Models (all predict the year-t rate p from year t-1 data only):
      national     p = national rate in t-1 = every state cell of year t-1 with
                   at least MIN_N samples (no state signal; computed from the
                   panel, NOT from the forecast pairs, because the pair set is
                   filtered on year-t data and would leak it into the baseline)
      persistence  p = the state's own rate in t-1
      shrink       p = (k0 + m * national0) / (n0 + m)   [m = prior strength]
    m = 0 is persistence and m = infinity is national, so shrink spans both.
    m is chosen from a fixed grid using ONLY target years strictly earlier than
    the one being evaluated (expanding window) — no information from the year
    being predicted or later leaks into its forecast.
  * A target year with no earlier target year cannot be evaluated (nothing to
    choose m from); it is used only for fitting later years.
  * Primary metric: pooled binomial log-loss on the year-t outcome (k out of n).
    Secondary: unweighted MAE of the rate, and within-year Spearman rank
    correlation between predicted and realised state rates (does the state
    ORDERING persist, independent of national level shifts?).
  * Uncertainty: bootstrap over STATES (the dependent unit across years).

This measures predictability of a sampled-testing rate, not of food risk:
sampling is inspector-targeted, so persistence can reflect enforcement
behaviour as much as underlying contamination.

Run:  python -m models.backtest_sampling            # reads state_sampling_annual
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

MIN_N = 100
M_GRID = (0.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, math.inf)
EPS = 1e-3
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 20260919

_FY_RE = re.compile(r"^(\d{4})-(\d{4})$")


@dataclass(frozen=True)
class Pair:
    state: str
    fy: str          # target year t
    n0: int
    k0: int          # year t-1
    n1: int
    k1: int          # year t (the outcome)


# ---------------------------------------------------------------- panel

def prev_fy(fy: str) -> str:
    m = _FY_RE.match(fy)
    if not m:
        raise ValueError(f"bad fiscal year {fy!r}")
    a, b = int(m.group(1)), int(m.group(2))
    if b != a + 1:
        raise ValueError(f"not a consecutive fiscal year: {fy!r}")
    return f"{a - 1}-{b - 1}"


def build_panel(rows: Iterable[dict], basis: str = "non_conforming") -> tuple[dict, list]:
    """(state, fy) -> (n, k), plus the cells dropped for conflicting figures."""
    cells: dict[tuple[str, str], set] = defaultdict(set)
    for r in rows:
        if r["non_conforming_basis"] != basis:
            continue
        cells[(r["state"], r["fiscal_year"])].add((int(r["samples_analyzed"]), int(r["samples_non_conforming"])))
    panel, conflicts = {}, []
    for key, vals in cells.items():
        if len(vals) == 1:
            panel[key] = next(iter(vals))
        else:
            conflicts.append(key)
    return panel, sorted(conflicts)


def _check_min_n(min_n: int) -> None:
    if min_n < 1:
        raise ValueError("min_n must be at least 1 (a state with no samples has no rate)")


def make_pairs(panel: dict, min_n: int = MIN_N) -> list[Pair]:
    _check_min_n(min_n)
    out = []
    for (state, fy), (n1, k1) in panel.items():
        prev = panel.get((state, prev_fy(fy)))
        if prev is None:
            continue
        n0, k0 = prev
        if n0 >= min_n and n1 >= min_n:
            out.append(Pair(state, fy, n0, k0, n1, k1))
    return sorted(out, key=lambda p: (p.fy, p.state))


# ---------------------------------------------------------------- forecasts and losses

def national_rate_prev(panel: dict, target_fy: str, min_n: int = MIN_N) -> Optional[float]:
    """National rate in year t-1: every state cell of the PREVIOUS year with at
    least `min_n` samples. It is deliberately computed from the panel, not from
    the forecast pairs — the pair set is filtered on year-t data (does the state
    also have a year-t cell with enough samples?), so a rate summed over it would
    let the year being predicted change its own baseline. An independent review
    reproduced that leak (changing one state's year-t sample count moved the
    baseline); this version reads nothing from year t."""
    prev = prev_fy(target_fy)
    cells = [(n, k) for (_, fy), (n, k) in panel.items() if fy == prev and n >= min_n]
    total = sum(n for n, _ in cells)
    return sum(k for _, k in cells) / total if total else None


def forecast(pair: Pair, national0: float, m: float) -> float:
    if math.isinf(m):
        p = national0
    else:
        p = (pair.k0 + m * national0) / (pair.n0 + m)
    return min(max(p, EPS), 1.0 - EPS)


def deviance(k: int, n: int, p: float) -> float:
    """Total binomial negative log-likelihood of k out of n at probability p."""
    return -(k * math.log(p) + (n - k) * math.log(1.0 - p))


def _by_year(pairs: list[Pair]) -> dict[str, list[Pair]]:
    out: dict[str, list[Pair]] = defaultdict(list)
    for p in pairs:
        out[p.fy].append(p)
    return dict(sorted(out.items()))


def pooled_loss(pairs: list[Pair], national0_by_year: dict[str, float], m: float) -> float:
    tot_dev = sum(deviance(p.k1, p.n1, forecast(p, national0_by_year[p.fy], m)) for p in pairs)
    return tot_dev / sum(p.n1 for p in pairs)


def choose_m(train: list[Pair], national0_by_year: dict[str, float]) -> float:
    """Grid value minimising pooled log-loss on `train` (earlier targets only).
    Ties resolve to the LARGER m (the more conservative, less state-specific
    model)."""
    best_m, best = None, math.inf
    for m in M_GRID:
        loss = pooled_loss(train, national0_by_year, m)
        if loss < best - 1e-12 or (abs(loss - best) <= 1e-12 and (best_m is None or m > best_m)):
            best_m, best = m, loss
    return best_m


def _ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    sorted_x = x[order]
    while i < len(x):
        j = i
        while j + 1 < len(x) and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    ra, rb = _ranks(np.asarray(a)), _ranks(np.asarray(b))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


# ---------------------------------------------------------------- the backtest

def evaluate(panel: dict, min_n: int = MIN_N) -> dict:
    """Backtest a panel {(state, fy): (n, k)}. Takes the PANEL, not pre-built
    pairs, so the national baseline can be computed from year t-1 alone."""
    _check_min_n(min_n)
    pairs = make_pairs(panel, min_n)
    by_year = _by_year(pairs)
    years = list(by_year)
    national0 = {fy: national_rate_prev(panel, fy, min_n) for fy in years}

    evaluated: list[dict] = []           # one record per evaluated pair
    per_year: list[dict] = []
    for i, fy in enumerate(years):
        if i == 0:
            continue                      # nothing earlier to choose m from
        train = [p for y in years[:i] for p in by_year[y]]
        m = choose_m(train, national0)
        ps = by_year[fy]
        models = {"national": math.inf, "persistence": 0.0, "shrink": m}
        preds = {name: [forecast(p, national0[fy], mm) for p in ps] for name, mm in models.items()}
        actual = [p.k1 / p.n1 for p in ps]
        yr = {"fy": fy, "n_pairs": len(ps), "m_selected": m, "national_rate_prev": national0[fy]}
        for name in models:
            yr[f"logloss_{name}"] = sum(deviance(p.k1, p.n1, q) for p, q in zip(ps, preds[name])) / sum(p.n1 for p in ps)
            yr[f"mae_{name}"] = float(np.mean([abs(a - q) for a, q in zip(actual, preds[name])]))
        yr["spearman_persistence"] = spearman(preds["persistence"], actual)
        yr["spearman_shrink"] = spearman(preds["shrink"], actual)
        per_year.append(yr)
        for j, p in enumerate(ps):
            evaluated.append({"state": p.state, "fy": fy, "n1": p.n1, "k1": p.k1,
                              **{f"dev_{name}": deviance(p.k1, p.n1, preds[name][j]) for name in models},
                              **{f"abs_{name}": abs(actual[j] - preds[name][j]) for name in models}})

    base = {"panel_cells": len(panel), "pairs_total": len(pairs), "min_n": min_n}
    if not evaluated:
        return {**base, "evaluated_pairs": 0, "per_year": [],
                "note": "no target year has an earlier target year to fit on"}

    names = ("national", "persistence", "shrink")
    total_n = sum(r["n1"] for r in evaluated)
    pooled = {f"logloss_{nm}": sum(r[f"dev_{nm}"] for r in evaluated) / total_n for nm in names}
    pooled.update({f"mae_{nm}": float(np.mean([r[f"abs_{nm}"] for r in evaluated])) for nm in names})

    # Bootstrap over STATES: paired differences in pooled log-loss. The evaluated
    # years, the fitted m and the national baselines are held fixed, so this
    # interval reflects between-state variability only — not uncertainty about
    # other years (only a handful are evaluated).
    states = sorted({r["state"] for r in evaluated})
    idx = {s: i for i, s in enumerate(states)}
    dev = {nm: np.zeros(len(states)) for nm in names}
    ns = np.zeros(len(states))
    for r in evaluated:
        i = idx[r["state"]]
        ns[i] += r["n1"]
        for nm in names:
            dev[nm][i] += r[f"dev_{nm}"]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, len(states), size=(BOOTSTRAP_B, len(states)))
    boot_n = ns[draws].sum(axis=1)
    boot = {nm: dev[nm][draws].sum(axis=1) / boot_n for nm in names}

    def ci(a: np.ndarray) -> list[float]:
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]

    diffs = {
        "persistence_minus_national": (pooled["logloss_persistence"] - pooled["logloss_national"], ci(boot["persistence"] - boot["national"])),
        "shrink_minus_national": (pooled["logloss_shrink"] - pooled["logloss_national"], ci(boot["shrink"] - boot["national"])),
        "shrink_minus_persistence": (pooled["logloss_shrink"] - pooled["logloss_persistence"], ci(boot["shrink"] - boot["persistence"])),
    }
    sp_p = [y["spearman_persistence"] for y in per_year if y["spearman_persistence"] is not None]
    sp_s = [y["spearman_shrink"] for y in per_year if y["spearman_shrink"] is not None]
    return {
        **base,
        "evaluated_pairs": len(evaluated),
        "evaluated_target_years": [y["fy"] for y in per_year],
        "states_in_bootstrap": len(states),
        "pooled": pooled,
        "paired_logloss_differences_(negative=first_is_better)": {k: {"estimate": v[0], "ci95": v[1]} for k, v in diffs.items()},
        "mean_spearman_persistence": float(np.mean(sp_p)) if sp_p else None,
        "mean_spearman_shrink": float(np.mean(sp_s)) if sp_s else None,
        "per_year": per_year,
    }


def run(rows: Iterable[dict], min_n: int = MIN_N) -> dict:
    panel, conflicts = build_panel(rows)
    res = evaluate(panel, min_n)
    res["conflicting_cells_dropped"] = len(conflicts)
    return res


# ---------------------------------------------------------------- sensitivity and placebo

# States/UTs with small or irregular sample volumes (small UTs, the north-east,
# Goa, Sikkim ...). The "large states only" variant drops them.
SMALL_UNITS = frozenset({
    "Lakshadweep", "Dadra and Nagar Haveli", "Daman and Diu", "Dadra and Nagar Haveli and Daman and Diu",
    "Andaman and Nicobar Islands", "Sikkim", "Mizoram", "Chandigarh", "Puducherry", "Ladakh", "Nagaland",
    "Arunachal Pradesh", "Manipur", "Meghalaya", "Tripura", "Goa",
})


def placebo_panel(panel: dict, seed: int = BOOTSTRAP_SEED) -> dict:
    """Control: within each fiscal year, shuffle which state each (n, k) cell is
    attached to. State identity is destroyed while every year's cells and totals
    are kept, so if last year's state rate genuinely predicts this year's,
    persistence should LOSE its edge here."""
    rng = random.Random(seed)
    by_year: dict[str, list] = defaultdict(list)
    for (state, fy), cell in sorted(panel.items()):
        by_year[fy].append((state, cell))
    out = {}
    for fy, items in sorted(by_year.items()):
        states = [s for s, _ in items]
        rng.shuffle(states)
        for new_state, (_, cell) in zip(states, items):
            out[(new_state, fy)] = cell
    return out


def _summary(res: dict) -> dict:
    if not res.get("evaluated_pairs"):
        return {"evaluated_pairs": 0}
    d = res["paired_logloss_differences_(negative=first_is_better)"]["persistence_minus_national"]
    return {
        "evaluated_pairs": res["evaluated_pairs"],
        "evaluated_target_years": len(res["evaluated_target_years"]),
        "persistence_minus_national_logloss": d["estimate"],
        "ci95": d["ci95"],
        "mae_national": res["pooled"]["mae_national"],
        "mae_persistence": res["pooled"]["mae_persistence"],
        "mean_spearman_persistence": res["mean_spearman_persistence"],
    }


def sensitivity(rows: Iterable[dict]) -> dict:
    """The variants reported in docs/BACKTEST_SAMPLING.md. They are checks on
    the primary result, never used to choose anything."""
    panel, _ = build_panel(rows)
    variants = {
        "primary": evaluate(panel, MIN_N),
        "min_n_500": evaluate(panel, 500),
        "min_n_1000": evaluate(panel, 1000),
        "from_2020_21": evaluate({k: v for k, v in panel.items() if k[1] >= "2020-2021"}, MIN_N),
        "large_states_only": evaluate({k: v for k, v in panel.items() if k[0] not in SMALL_UNITS}, MIN_N),
        "placebo_shuffled_state_labels": evaluate(placebo_panel(panel), MIN_N),
    }
    return {name: _summary(res) for name, res in variants.items()}


# ---------------------------------------------------------------- CLI

def _json_safe(obj):
    """m = infinity is a legitimate result (the national-only model won) but is
    not valid JSON; emit the string "inf" so the output parses everywhere."""
    if isinstance(obj, float):
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        if math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _load_rows() -> list[dict]:
    import psycopg2.extras
    from pipeline.config import pg_connect

    conn = pg_connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT state, fiscal_year, samples_analyzed, samples_non_conforming, non_conforming_basis "
                "FROM state_sampling_annual"
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the full result as valid JSON")
    ap.add_argument("--sensitivity", action="store_true",
                    help="run the documented sensitivity variants and the shuffled-label placebo")
    args = ap.parse_args()
    rows = _load_rows()
    res = sensitivity(rows) if args.sensitivity else run(rows)
    if args.json:
        print(json.dumps(_json_safe(res), indent=2, allow_nan=False))
        return
    if args.sensitivity:
        for name, s in res.items():
            if not s.get("evaluated_pairs"):
                print(f"  {name:32s} nothing evaluable")
                continue
            lo, hi = s["ci95"]
            print(f"  {name:32s} pairs={s['evaluated_pairs']:3d} pers-nat={s['persistence_minus_national_logloss']:+.4f} "
                  f"[{lo:+.4f},{hi:+.4f}]  MAE nat/pers={s['mae_national']:.3f}/{s['mae_persistence']:.3f}  "
                  f"rho={s['mean_spearman_persistence']:.2f}")
        return
    print(f"panel cells: {res['panel_cells']}  pairs: {res['pairs_total']}  evaluated: {res['evaluated_pairs']}")
    for y in res.get("per_year", []):
        print(f"  {y['fy']}  pairs={y['n_pairs']:3d}  m={y['m_selected']}  logloss nat/pers/shrink = "
              f"{y['logloss_national']:.4f}/{y['logloss_persistence']:.4f}/{y['logloss_shrink']:.4f}")
    if res.get("pooled"):
        print("pooled:", {k: round(v, 4) for k, v in res["pooled"].items()})


if __name__ == "__main__":
    main()
