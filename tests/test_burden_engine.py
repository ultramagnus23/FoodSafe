"""
models/burden_engine.py: the arithmetic, a reproduction of a published risk assessment, and
the refusals that keep invented inputs out.

The reproduction is the validation: given Liu & Wu's (2010, EHP 118:818, Table 3) exposure
range for India (4-100 ng/kg bw/day) and JECFA's 1998 potencies, the engine must return their
published incidences: 0.04-1.00 per 100,000 per year for people without hepatitis B, and
1.20-30.0 for carriers.
"""

from __future__ import annotations

import pytest

from models import burden_engine as B


def test_exposure_is_concentration_times_intake_over_body_weight():
    f = [B.FoodIntake("groundnut", "aflatoxin_b1", concentration_ug_per_kg=10, intake_g_per_day=100)]
    assert B.exposure_ng_per_kg_bw_day(f, body_weight_kg=50) == pytest.approx(20.0)     # 10 ng/g x 100 g / 50 kg


def test_exposure_sums_foods_and_weights_m1_at_a_tenth():
    foods = [
        B.FoodIntake("maize", "aflatoxin_b1", 5, 60),        # 300 ng/day
        B.FoodIntake("milk", "aflatoxin_m1", 0.5, 400),      # 200 ng/day x 0.1 = 20
    ]
    assert B.exposure_ng_per_kg_bw_day(foods, 64) == pytest.approx(320 / 64)


@pytest.mark.parametrize(
    "exposure, group, expected",
    [(4, "hbsag_neg", 0.04), (100, "hbsag_neg", 1.00), (4, "hbsag_pos", 1.20), (100, "hbsag_pos", 30.0)],
)
def test_reproduces_liu_and_wu_2010_india_incidence(exposure, group, expected):
    shares = {"hbsag_pos": 1.0 if group == "hbsag_pos" else 0.0, "hbsag_neg": 1.0 if group == "hbsag_neg" else 0.0}
    got = B.incidence_per_100k(exposure, B.AFLATOXIN_B1_JECFA_1998.central, shares)
    assert got == pytest.approx(expected)


def test_population_incidence_weights_groups_by_prevalence():
    i = B.incidence_per_100k(10, B.AFLATOXIN_B1_JECFA_1998.central, B.hbv_shares(0.03))
    assert i == pytest.approx(10 * (0.3 * 0.03 + 0.01 * 0.97))
    assert B.cases_per_year(i, 1_000_000) == pytest.approx(i * 10)


def test_2016_potency_is_the_published_jecfa_83rd_values():
    p = B.AFLATOXIN_B1_JECFA_2016
    assert p.central == {"hbsag_pos": 0.269, "hbsag_neg": 0.017}
    assert p.upper == {"hbsag_pos": 0.562, "hbsag_neg": 0.049}
    assert p.url.startswith("https://doi.org/")


def test_margin_of_exposure_and_hazard_quotient():
    assert B.margin_of_exposure(0.04) == pytest.approx(10_000)            # 400 ng / 0.04 ng
    assert B.margin_of_exposure(0) is None
    assert B.hazard_quotient(0.002, 0.001) == pytest.approx(2.0)


@pytest.mark.parametrize(
    "call",
    [
        lambda: B.exposure_ng_per_kg_bw_day([B.FoodIntake("rice", "aflatoxin_b1", -1, 100)], 60),
        lambda: B.exposure_ng_per_kg_bw_day([B.FoodIntake("rice", "aflatoxin_b1", None, 100)], 60),  # type: ignore[arg-type]
        lambda: B.exposure_ng_per_kg_bw_day([B.FoodIntake("rice", "aflatoxin_b1", 1, 100)], 0),
        lambda: B.exposure_ng_per_kg_bw_day([B.FoodIntake("rice", "ochratoxin_a", 1, 100)], 60),
        lambda: B.incidence_per_100k(5, B.AFLATOXIN_B1_JECFA_2016.central, {"hbsag_pos": 0.5, "hbsag_neg": 0.4}),
        lambda: B.incidence_per_100k(5, B.AFLATOXIN_B1_JECFA_2016.central, {"all": 1.0}),
        lambda: B.hbv_shares(3.7),
        lambda: B.hazard_quotient(1, 0),
    ],
)
def test_refuses_missing_negative_or_inconsistent_inputs(call):
    with pytest.raises(ValueError):
        call()


def _inputs(conc: B.Dist, potency_draw: str = "between") -> B.BurdenInputs:
    return B.BurdenInputs(
        foods=[("groundnut", "aflatoxin_b1", conc, B.Dist("fixed", 20))],
        body_weight_kg=B.Dist("fixed", 60),
        hbsag_prevalence=B.Dist("fixed", 0.03),
        population=1_000_000,
        potency=B.AFLATOXIN_B1_JECFA_2016,
        potency_draw=potency_draw,
    )


def test_simulation_with_fixed_inputs_equals_the_deterministic_answer():
    s = B.simulate(_inputs(B.Dist("fixed", 9), potency_draw="central"), draws=200)
    e = 9 * 20 / 60
    i = B.incidence_per_100k(e, B.AFLATOXIN_B1_JECFA_2016.central, B.hbv_shares(0.03))
    assert s.exposure_median_ng == pytest.approx(e)
    assert s.cases_median == pytest.approx(B.cases_per_year(i, 1_000_000))
    assert s.cases_p2_5 == pytest.approx(s.cases_p97_5)


def test_simulation_is_reproducible_and_brackets_its_median():
    a = B.simulate(_inputs(B.Dist("lognormal", 5, 2.5)), draws=2000, seed=7)
    b = B.simulate(_inputs(B.Dist("lognormal", 5, 2.5)), draws=2000, seed=7)
    assert a == b
    assert a.cases_p2_5 < a.cases_median < a.cases_p97_5
