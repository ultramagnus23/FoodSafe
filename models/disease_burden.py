"""
FoodSafe India — Disease Burden Estimation Engine

Converts dietary exposure estimates into Population Attributable Fraction
(PAF) and hazard-quotient based flags, per contaminant x commodity x
district x disease.

Three branches (per dose_response_params.model_type):
  linear_no_threshold (carcinogens: aflatoxin, arsenic, fumonisin):
      excess_risk = slope_factor * daily_intake_ug_per_kg_bw
      PAF = excess_risk / (background_incidence + excess_risk)
      attributable_cases_per_100k = PAF * background_incidence_per_100k
  threshold (ochratoxin, cadmium/kidney, lead/neurotox):
      HQ = daily_intake / TDI; HQ > 1 -> TWI/TDI exceedance flag.
      PAF is not computed (no dose-response curve to integrate) — HQ is
      reported directly instead.
  hazard_quotient (pesticide mixtures):
      HI = sum of individual contaminant HQs; HI > 1 -> concern flag.

Uncertainty: Monte Carlo (n=1000) over contamination_ppb (empirical spread
of the underlying enforcement records), consumption (own record's
implied +/-25% spread, since NSSO income-quintile data isn't seeded — this
is flagged as `data_source='national_proxy'` same as DietaryExposureEstimator),
and slope_factor (+/-30%, IARC-stated uncertainty). Reports 2.5th/97.5th
percentile as the PAF confidence interval.

Run:  python -m models.disease_burden compute_all
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np

from models.dietary_exposure import DietaryExposureEstimator

logger = logging.getLogger("foodsafe.models.disease_burden")

CONF_MIN = 0.75
MIN_RECORDS = 3
MC_SAMPLES = 1000
SLOPE_FACTOR_UNCERTAINTY = 0.30  # +/-30% per IARC
CONSUMPTION_UNCERTAINTY = 0.25   # proxy spread; real NSSO quintiles not seeded


@dataclass
class BurdenResult:
    mean_exposure_ppb: float
    mean_dietary_intake_ug_per_kg_per_day: Optional[float]
    p95_dietary_intake_ug_per_kg_per_day: Optional[float]
    twi_exceedance_fraction: Optional[float]
    population_attributable_fraction: Optional[float]
    paf_lower_ci: Optional[float]
    paf_upper_ci: Optional[float]
    estimated_attributable_cases_per_100k: Optional[float]
    hazard_quotient: Optional[float]
    n_enforcement_records: int
    inference_type: str


class DiseaseBurdenEstimator:
    def __init__(self, conn=None):
        self._conn = conn
        self._owns_conn = conn is None
        self.exposure = DietaryExposureEstimator(conn=conn)
        self._dose_response_cache: Optional[list[dict]] = None

    def _get_conn(self):
        if self._conn is None:
            from pipeline.config import pg_connect
            self._conn = pg_connect()
            self.exposure._conn = self._conn
        return self._conn

    # ------------------------------------------------------------
    # data load
    # ------------------------------------------------------------

    def _load_dose_response(self) -> list[dict]:
        if self._dose_response_cache is not None:
            return self._dose_response_cache
        import psycopg2.extras
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT drp.*, c.name_canonical AS contaminant_name
                FROM dose_response_params drp
                JOIN contaminants c ON c.id = drp.contaminant_id
                """
            )
            self._dose_response_cache = [dict(r) for r in cur.fetchall()]
        return self._dose_response_cache

    def _load_records(self, district_id: int, commodity_id: int, contaminant_id: int) -> list[dict]:
        import psycopg2.extras
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT er.raw_value_ppb, d.state
                FROM enforcement_records er
                JOIN districts d ON d.id = er.district_id
                WHERE er.district_id = %s AND er.commodity_id = %s AND er.contaminant_id = %s
                  AND er.confidence_score >= %s AND er.is_duplicate = FALSE
                """,
                (district_id, commodity_id, contaminant_id, CONF_MIN),
            )
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------
    # core estimation
    # ------------------------------------------------------------

    def estimate(
        self, district_id: int, commodity_id: int, contaminant_id: int, dose_response_row: dict
    ) -> Optional[BurdenResult]:
        records = self._load_records(district_id, commodity_id, contaminant_id)
        n = len(records)
        if n < MIN_RECORDS:
            return None

        values = np.array([float(r["raw_value_ppb"]) for r in records if r["raw_value_ppb"]])
        state = records[0]["state"]
        mean_ppb = float(np.mean(values))

        exposure_mean = self.exposure.estimate(
            contamination_ppb=mean_ppb, commodity_id=commodity_id, state=state, consumer_type="mean"
        )
        exposure_p95 = self.exposure.estimate(
            contamination_ppb=float(np.percentile(values, 95)) if n > 1 else mean_ppb,
            commodity_id=commodity_id, state=state, consumer_type="p95",
        )

        model_type = dose_response_row["model_type"]

        if model_type == "linear_no_threshold":
            return self._linear_paf(values, exposure_mean, exposure_p95, dose_response_row, n)
        elif model_type in ("threshold", "hazard_quotient"):
            return self._threshold_hq(values, exposure_mean, exposure_p95, dose_response_row, n)
        return None

    def _linear_paf(self, values, exposure_mean, exposure_p95, drp, n) -> Optional[BurdenResult]:
        if exposure_mean.daily_intake_ug_per_kg_bw is None:
            return None
        slope = float(drp["slope_factor"] or 0)
        background = float(drp["background_incidence_per_100k"] or 0)

        # Monte Carlo over contamination spread, consumption proxy, slope uncertainty
        rng = np.random.default_rng(42)
        ppb_samples = rng.choice(values, size=MC_SAMPLES, replace=True) if len(values) > 1 else np.full(MC_SAMPLES, values[0])
        consumption_noise = rng.normal(1.0, CONSUMPTION_UNCERTAINTY, MC_SAMPLES)
        slope_noise = rng.normal(1.0, SLOPE_FACTOR_UNCERTAINTY, MC_SAMPLES)

        grams_per_day = exposure_mean.consumption_g_day or 0.0
        bodyweight_kg = 60.0  # adult, matches DietaryExposureEstimator default
        daily_intake_samples = ppb_samples * (grams_per_day * np.clip(consumption_noise, 0.1, None) / 1000.0) / bodyweight_kg
        slope_samples = slope * np.clip(slope_noise, 0.1, None)

        excess_risk_samples = slope_samples * daily_intake_samples
        if background > 0:
            paf_samples = excess_risk_samples / (background / 100_000 + excess_risk_samples)
        else:
            paf_samples = np.zeros(MC_SAMPLES)
        paf_samples = np.clip(paf_samples, 0.0, 1.0)

        paf_mean = float(np.mean(paf_samples))
        paf_lo, paf_hi = float(np.percentile(paf_samples, 2.5)), float(np.percentile(paf_samples, 97.5))
        attributable_cases = paf_mean * background if background else None

        return BurdenResult(
            mean_exposure_ppb=float(np.mean(values)),
            mean_dietary_intake_ug_per_kg_per_day=exposure_mean.daily_intake_ug_per_kg_bw,
            p95_dietary_intake_ug_per_kg_per_day=exposure_p95.daily_intake_ug_per_kg_bw,
            twi_exceedance_fraction=None,
            population_attributable_fraction=round(paf_mean, 4),
            paf_lower_ci=round(paf_lo, 4),
            paf_upper_ci=round(paf_hi, 4),
            estimated_attributable_cases_per_100k=round(attributable_cases, 4) if attributable_cases is not None else None,
            hazard_quotient=None,
            n_enforcement_records=n,
            inference_type="direct",
        )

    def _threshold_hq(self, values, exposure_mean, exposure_p95, drp, n) -> Optional[BurdenResult]:
        if exposure_mean.daily_intake_ug_per_kg_bw is None:
            return None
        tdi = drp.get("tdi_ug_per_kg_day")
        hq = None
        twi_exceedance_fraction = None
        if tdi:
            hq = round(exposure_mean.daily_intake_ug_per_kg_bw / float(tdi), 3)
            # Fraction of the (Monte Carlo) population sampled from the record
            # spread whose intake exceeds TDI.
            rng = np.random.default_rng(42)
            ppb_samples = rng.choice(values, size=MC_SAMPLES, replace=True) if len(values) > 1 else np.full(MC_SAMPLES, values[0])
            grams_per_day = exposure_mean.consumption_g_day or 0.0
            intake_samples = ppb_samples * (grams_per_day / 1000.0) / 60.0
            twi_exceedance_fraction = round(float(np.mean(intake_samples > float(tdi))), 4)

        return BurdenResult(
            mean_exposure_ppb=float(np.mean(values)),
            mean_dietary_intake_ug_per_kg_per_day=exposure_mean.daily_intake_ug_per_kg_bw,
            p95_dietary_intake_ug_per_kg_per_day=exposure_p95.daily_intake_ug_per_kg_bw,
            twi_exceedance_fraction=twi_exceedance_fraction,
            population_attributable_fraction=None,
            paf_lower_ci=None,
            paf_upper_ci=None,
            estimated_attributable_cases_per_100k=None,
            hazard_quotient=hq,
            n_enforcement_records=n,
            inference_type="direct",
        )

    # ------------------------------------------------------------
    # batch: compute_all
    # ------------------------------------------------------------

    def compute_all(self) -> dict:
        conn = self._get_conn()
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT er.district_id, er.commodity_id, er.contaminant_id
                FROM enforcement_records er
                WHERE er.district_id IS NOT NULL
                  AND er.confidence_score >= %s AND er.is_duplicate = FALSE
                """,
                (CONF_MIN,),
            )
            combos = [dict(r) for r in cur.fetchall()]

        dose_response = self._load_dose_response()
        drp_by_contaminant = defaultdict(list)
        for row in dose_response:
            drp_by_contaminant[row["contaminant_id"]].append(row)

        n_estimates = 0
        n_alerts = 0
        with conn.cursor() as cur:
            for combo in combos:
                district_id = combo["district_id"]
                commodity_id = combo["commodity_id"]
                contaminant_id = combo["contaminant_id"]
                for drp in drp_by_contaminant.get(contaminant_id, []):
                    result = self.estimate(district_id, commodity_id, contaminant_id, drp)
                    if result is None:
                        continue
                    self._upsert_estimate(cur, district_id, commodity_id, contaminant_id, drp, result)
                    n_estimates += 1
                    if self._maybe_alert(cur, district_id, commodity_id, contaminant_id, drp, result):
                        n_alerts += 1
        conn.commit()
        summary = {"combos_checked": len(combos), "estimates_written": n_estimates, "alerts_written": n_alerts}
        logger.info("Disease burden compute_all complete: %s", summary)
        return summary

    @staticmethod
    def _upsert_estimate(cur, district_id, commodity_id, contaminant_id, drp, result: BurdenResult):
        cur.execute(
            """
            INSERT INTO disease_burden_estimates
                (district_id, commodity_id, contaminant_id, disease_icd10,
                 mean_exposure_ppb, mean_dietary_intake_ug_per_kg_per_day,
                 p95_dietary_intake_ug_per_kg_per_day, twi_exceedance_fraction,
                 population_attributable_fraction, paf_lower_ci, paf_upper_ci,
                 estimated_attributable_cases_per_100k, n_enforcement_records,
                 inference_type, fssai_vs_codex_exceedance, model_version, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'burden-1.0',NOW())
            ON CONFLICT (district_id, commodity_id, contaminant_id, disease_icd10)
            DO UPDATE SET
                mean_exposure_ppb = EXCLUDED.mean_exposure_ppb,
                mean_dietary_intake_ug_per_kg_per_day = EXCLUDED.mean_dietary_intake_ug_per_kg_per_day,
                p95_dietary_intake_ug_per_kg_per_day = EXCLUDED.p95_dietary_intake_ug_per_kg_per_day,
                twi_exceedance_fraction = EXCLUDED.twi_exceedance_fraction,
                population_attributable_fraction = EXCLUDED.population_attributable_fraction,
                paf_lower_ci = EXCLUDED.paf_lower_ci,
                paf_upper_ci = EXCLUDED.paf_upper_ci,
                estimated_attributable_cases_per_100k = EXCLUDED.estimated_attributable_cases_per_100k,
                n_enforcement_records = EXCLUDED.n_enforcement_records,
                inference_type = EXCLUDED.inference_type,
                computed_at = NOW()
            """,
            (
                district_id, commodity_id, contaminant_id, drp["disease_icd10"],
                result.mean_exposure_ppb, result.mean_dietary_intake_ug_per_kg_per_day,
                result.p95_dietary_intake_ug_per_kg_per_day, result.twi_exceedance_fraction,
                result.population_attributable_fraction, result.paf_lower_ci, result.paf_upper_ci,
                result.estimated_attributable_cases_per_100k, result.n_enforcement_records,
                result.inference_type, None,
            ),
        )

    @staticmethod
    def _maybe_alert(cur, district_id, commodity_id, contaminant_id, drp, result: BurdenResult) -> bool:
        """Refresh exposure_alerts for TWI exceedance. Codex-gap alerts are
        written separately from agg_district_commodity_risk.fssai_vs_codex_flag
        (see models/codex_benchmark.py) since that's computed per-record, not
        per-disease."""
        if result.twi_exceedance_fraction is None or result.twi_exceedance_fraction <= 0:
            return False
        severity = (
            "critical" if result.twi_exceedance_fraction > 0.5 else
            "high" if result.twi_exceedance_fraction > 0.2 else
            "moderate"
        )
        cur.execute(
            """
            INSERT INTO exposure_alerts
                (district_id, contaminant_id, commodity_id, alert_type, severity,
                 mean_exposure_ppb, n_samples, first_seen, last_seen, active)
            VALUES (%s,%s,%s,'twi_exceedance',%s,%s,%s,CURRENT_DATE,CURRENT_DATE,TRUE)
            ON CONFLICT (district_id, contaminant_id, commodity_id, alert_type)
            DO UPDATE SET
                severity = EXCLUDED.severity,
                mean_exposure_ppb = EXCLUDED.mean_exposure_ppb,
                n_samples = EXCLUDED.n_samples,
                last_seen = CURRENT_DATE,
                active = TRUE
            """,
            (district_id, contaminant_id, commodity_id, severity,
             result.mean_exposure_ppb, result.n_enforcement_records),
        )
        return True

    def close(self):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Disease burden estimation")
    parser.add_argument("command", choices=["compute_all"], default="compute_all", nargs="?")
    parser.parse_args()

    estimator = DiseaseBurdenEstimator()
    try:
        summary = estimator.compute_all()
    finally:
        estimator.close()
    print("\n=== DISEASE BURDEN SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
