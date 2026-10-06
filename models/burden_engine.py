"""
Expected disease from dietary exposure: the risk-characterisation step of the disease engine.

For a genotoxic carcinogen with a published cancer potency (cases per 100,000 people per
year, per ng/kg body weight per day), expected cases follow from exposure, the share of the
population in each susceptibility group, and the population size:

    exposure (ng/kg bw/day)   = sum over foods of  concentration (µg/kg) x intake (g/day) / body weight (kg)
    incidence (per 100,000/yr) = exposure x sum over groups of  potency_g x share_g
    cases per year             = incidence x population / 100,000

This is the method of JECFA and of Liu & Wu (2010, Environ Health Perspect 118:818), used by
WHO's Foodborne Disease Burden Epidemiology Reference Group for aflatoxin. tests/test_burden_engine.py
checks it against Liu & Wu's published incidences for India.

For a threshold toxicant (pesticides), there is no case count: the hazard quotient
(exposure / acceptable daily intake) says whether intake exceeds the safe level. For a
genotoxic carcinogen, the margin of exposure (BMDL10 / exposure) is reported next to the case
estimate; EFSA treats an MOE below 10,000 as a health concern.

Every parameter here is published and cited. Inputs (concentrations, intakes, body weights,
susceptibility shares) must come from real measurements or surveys; this module invents
nothing and refuses negative or missing values.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

EFSA_2020 = "https://doi.org/10.2903/j.efsa.2020.6040"
LIU_WU_2010 = "https://doi.org/10.1289/ehp.0901388"


@dataclass(frozen=True)
class Potency:
    """Cancer potency by susceptibility group: cases per 100,000 per year per ng/kg bw/day."""

    hazard_key: str
    outcome: str
    icd10: str
    central: Mapping[str, float]
    upper: Mapping[str, float]
    source: str
    url: str


# JECFA 83rd meeting (2016), as reported in EFSA's 2020 opinion: means and 95% upper bounds.
AFLATOXIN_B1_JECFA_2016 = Potency(
    hazard_key="aflatoxin_b1",
    outcome="Hepatocellular carcinoma",
    icd10="C22.0",
    central={"hbsag_pos": 0.269, "hbsag_neg": 0.017},
    upper={"hbsag_pos": 0.562, "hbsag_neg": 0.049},
    source="JECFA 83rd meeting (2016), reported in EFSA CONTAM Panel (2020) Risk assessment of aflatoxins in food",
    url=EFSA_2020,
)

# JECFA 49th meeting (1998): the point values Liu & Wu (2010) used. Kept to reproduce their
# results; its uncertainty ranges are not carried here, so upper = central.
AFLATOXIN_B1_JECFA_1998 = Potency(
    hazard_key="aflatoxin_b1",
    outcome="Hepatocellular carcinoma",
    icd10="C22.0",
    central={"hbsag_pos": 0.3, "hbsag_neg": 0.01},
    upper={"hbsag_pos": 0.3, "hbsag_neg": 0.01},
    source="JECFA 49th meeting (1998), as used by Liu & Wu (2010)",
    url=LIU_WU_2010,
)

# Aflatoxin M1 (in milk) is counted at a tenth of B1's potency (EFSA 2020 potency factor).
RELATIVE_POTENCY = {"aflatoxin_b1": 1.0, "aflatoxin_m1": 0.1}

# BMDL10 for hepatocellular carcinoma from aflatoxin B1 in male rats, ng/kg bw/day (EFSA 2020).
AFLATOXIN_BMDL10_NG = 400.0
MOE_CONCERN = 10_000.0


@dataclass(frozen=True)
class FoodIntake:
    """One food's contribution: concentration in µg/kg (= ng/g) and intake in g/day."""

    food: str
    hazard_key: str
    concentration_ug_per_kg: float
    intake_g_per_day: float


def _check(name: str, v: Optional[float], positive: bool = False) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        raise ValueError(f"{name} is missing: every input must come from a measurement or survey")
    if v < 0 or (positive and v == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'non-negative'}, got {v}")
    return float(v)


def exposure_ng_per_kg_bw_day(foods: Sequence[FoodIntake], body_weight_kg: float) -> float:
    """B1-equivalent exposure: each food's hazard weighted by its potency relative to B1."""
    bw = _check("body_weight_kg", body_weight_kg, positive=True)
    total = 0.0
    for f in foods:
        if f.hazard_key not in RELATIVE_POTENCY:
            raise ValueError(f"no relative potency for {f.hazard_key!r}")
        c = _check(f"{f.food} concentration", f.concentration_ug_per_kg)
        g = _check(f"{f.food} intake", f.intake_g_per_day)
        total += RELATIVE_POTENCY[f.hazard_key] * c * g          # µg/kg x g/day = ng/day
    return total / bw


def incidence_per_100k(exposure_ng: float, potency: Mapping[str, float], shares: Mapping[str, float]) -> float:
    """Expected cases per 100,000 people per year. Shares must cover the population (sum to 1)."""
    e = _check("exposure", exposure_ng)
    if set(shares) != set(potency):
        raise ValueError(f"susceptibility groups {sorted(shares)} do not match potency groups {sorted(potency)}")
    for g, s in shares.items():
        _check(f"share {g}", s)
    if abs(sum(shares.values()) - 1.0) > 1e-9:
        raise ValueError(f"susceptibility shares must sum to 1, got {sum(shares.values())}")
    return e * sum(potency[g] * shares[g] for g in potency)


def hbv_shares(hbsag_prevalence: float) -> dict[str, float]:
    p = _check("hbsag_prevalence", hbsag_prevalence)
    if p > 1:
        raise ValueError("hbsag_prevalence is a proportion (0-1)")
    return {"hbsag_pos": p, "hbsag_neg": 1.0 - p}


def cases_per_year(incidence: float, population: float) -> float:
    return _check("incidence", incidence) * _check("population", population) / 100_000


def margin_of_exposure(exposure_ng: float, bmdl_ng: float = AFLATOXIN_BMDL10_NG) -> Optional[float]:
    e = _check("exposure", exposure_ng)
    return None if e == 0 else bmdl_ng / e


def hazard_quotient(exposure_mg_per_kg_bw_day: float, adi_mg_per_kg_bw_day: float) -> float:
    """Threshold toxicants: above 1 means intake exceeds the acceptable daily intake."""
    return _check("exposure", exposure_mg_per_kg_bw_day) / _check("ADI", adi_mg_per_kg_bw_day, positive=True)


# ---- uncertainty: Monte Carlo over input distributions supplied by the study

@dataclass(frozen=True)
class Dist:
    """An input distribution. kind: 'fixed' (a), 'uniform' (a..b), 'lognormal' (median a, GSD b),
    'triangular' (low a, mode m, high b). Parameters must come from the data, not be assumed."""

    kind: str
    a: float
    b: float = 0.0
    m: float = 0.0

    def draw(self, rng: random.Random) -> float:
        if self.kind == "fixed":
            return self.a
        if self.kind == "uniform":
            return rng.uniform(self.a, self.b)
        if self.kind == "lognormal":
            return rng.lognormvariate(math.log(self.a), math.log(self.b))
        if self.kind == "triangular":
            return rng.triangular(self.a, self.b, self.m)
        raise ValueError(f"unknown distribution {self.kind!r}")


@dataclass
class BurdenInputs:
    foods: Sequence[tuple[str, str, Dist, Dist]]       # (food, hazard_key, concentration µg/kg, intake g/day)
    body_weight_kg: Dist
    hbsag_prevalence: Dist
    population: float
    potency: Potency = AFLATOXIN_B1_JECFA_2016
    potency_draw: str = "between"                        # 'central' | 'between' (uniform central..upper)


@dataclass
class BurdenSummary:
    cases_median: float
    cases_p2_5: float
    cases_p97_5: float
    incidence_median_per_100k: float
    exposure_median_ng: float
    moe_median: Optional[float]
    draws: int
    potency_source: str = field(default="")


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def simulate(inputs: BurdenInputs, draws: int = 10_000, seed: int = 20261006) -> BurdenSummary:
    rng = random.Random(seed)
    cases, incid, expo = [], [], []
    for _ in range(draws):
        foods = [FoodIntake(f, h, c.draw(rng), g.draw(rng)) for f, h, c, g in inputs.foods]
        e = exposure_ng_per_kg_bw_day(foods, inputs.body_weight_kg.draw(rng))
        if inputs.potency_draw == "central":
            pot = dict(inputs.potency.central)
        else:
            pot = {k: rng.uniform(v, inputs.potency.upper[k]) for k, v in inputs.potency.central.items()}
        i = incidence_per_100k(e, pot, hbv_shares(min(1.0, max(0.0, inputs.hbsag_prevalence.draw(rng)))))
        expo.append(e)
        incid.append(i)
        cases.append(cases_per_year(i, inputs.population))
    e_med = _quantile(expo, 0.5)
    return BurdenSummary(
        cases_median=_quantile(cases, 0.5),
        cases_p2_5=_quantile(cases, 0.025),
        cases_p97_5=_quantile(cases, 0.975),
        incidence_median_per_100k=_quantile(incid, 0.5),
        exposure_median_ng=e_med,
        moe_median=margin_of_exposure(e_med),
        draws=draws,
        potency_source=inputs.potency.source,
    )
