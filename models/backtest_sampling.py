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
      national     p = national rate in t-1 (no state signal)
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


def make_pairs(panel: dict, min_n: int = MIN_N) -> list[Pair]:
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

def national_rate_prev(pairs_in_year: list[Pair]) -> float:
    """National rate in year t-1 over the states forecast in year t. Uses only
    year t-1 counts."""
    n = sum(p.n0 for p in pairs_in_year)
    return sum(p.k0 for p in pairs_in_year) / n


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

def evaluate(pairs: list[Pair]) -> dict:
    by_year = _by_year(pairs)
    years = list(by_year)
    national0 = {fy: national_rate_prev(ps) for fy, ps in by_year.items()}

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
        yr = {"fy": fy, "n_pairs": len(ps), "m_selected": m, "national_rate_prev": round(national0[fy], 4)}
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

    if not evaluated:
        return {"evaluated_pairs": 0, "per_year": [], "note": "no target year has an earlier target year to fit on"}

    names = ("national", "persistence", "shrink")
    total_n = sum(r["n1"] for r in evaluated)
    pooled = {f"logloss_{nm}": sum(r[f"dev_{nm}"] for r in evaluated) / total_n for nm in names}
    pooled.update({f"mae_{nm}": float(np.mean([r[f"abs_{nm}"] for r in evaluated])) for nm in names})

    # Bootstrap over states: paired differences in pooled log-loss.
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
    pairs = make_pairs(panel, min_n)
    res = evaluate(pairs)
    res["panel_cells"] = len(panel)
    res["conflicting_cells_dropped"] = len(conflicts)
    res["pairs_total"] = len(pairs)
    res["min_n"] = min_n
    return res


# ---------------------------------------------------------------- CLI

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
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()
    res = run(_load_rows())
    if args.json:
        print(json.dumps(res, indent=2, default=str))
        return
    print(f"panel cells: {res['panel_cells']}  pairs: {res['pairs_total']}  evaluated: {res['evaluated_pairs']}")
    for y in res.get("per_year", []):
        print(f"  {y['fy']}  pairs={y['n_pairs']:3d}  m={y['m_selected']}  logloss nat/pers/shrink = "
              f"{y['logloss_national']:.4f}/{y['logloss_persistence']:.4f}/{y['logloss_shrink']:.4f}")
    if res.get("pooled"):
        print("pooled:", {k: round(v, 4) for k, v in res["pooled"].items()})


if __name__ == "__main__":
    main()
