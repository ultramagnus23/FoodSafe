"""
FoodSafe India — Contamination Trend Analysis

Detects whether contamination for a district x commodity (x contaminant) is
getting better or worse over time:

  - Trend significance: Kendall's tau correlation between the monthly time
    index and monthly mean PPB (scipy.stats.kendalltau). For a single,
    non-seasonal series this is mathematically equivalent to the standard
    Mann-Kendall trend test's S-statistic/p-value — the same approach used
    by most practical Mann-Kendall implementations.
  - Trend magnitude: Sen's slope estimator (median of all pairwise slopes),
    robust to outliers — the standard companion to Mann-Kendall, reported
    in PPB/month.

Only reports a trend when p < 0.05 AND there are >= 6 months of data;
otherwise returns 'insufficient_data'. Never asserts a trend direction it
can't statistically back up.

Run ad hoc:  python -m models.trend_analysis <district_id> <commodity_id> [contaminant_id]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
from scipy import stats

logger = logging.getLogger("foodsafe.models.trend_analysis")

MIN_MONTHS = 6
SIGNIFICANCE_P = 0.05


@dataclass
class MonthlyPoint:
    month: str
    mean_ppb: float
    max_ppb: float
    fail_rate_fssai: Optional[float]
    fail_rate_codex: Optional[float]
    n_records: int


@dataclass
class TrendResult:
    series: list[MonthlyPoint]
    trend: str  # 'improving' | 'worsening' | 'stable' | 'insufficient_data'
    trend_pvalue: Optional[float]
    trend_magnitude: Optional[float]  # Sen's slope, PPB per month


class TrendAnalyzer:
    def __init__(self, conn=None):
        self._conn = conn
        self._owns_conn = conn is None

    def _get_conn(self):
        if self._conn is None:
            from pipeline.config import pg_connect
            self._conn = pg_connect()
        return self._conn

    def _load_monthly_records(
        self,
        district_id: Optional[int] = None,
        commodity_id: Optional[int] = None,
        contaminant_id: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> list[dict]:
        import psycopg2.extras

        conn = self._get_conn()
        clauses = ["er.confidence_score >= 0.75", "er.is_duplicate = FALSE"]
        params: list = []
        if district_id is not None:
            clauses.append("er.district_id = %s")
            params.append(district_id)
        if commodity_id is not None:
            clauses.append("er.commodity_id = %s")
            params.append(commodity_id)
        if contaminant_id is not None:
            clauses.append("er.contaminant_id = %s")
            params.append(contaminant_id)
        if from_date is not None:
            clauses.append("er.test_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("er.test_date <= %s")
            params.append(to_date)
        where = " AND ".join(clauses)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT date_trunc('month', er.test_date)::date AS month,
                       er.raw_value_ppb, er.legal_limit_ppb, er.pass_fail,
                       cnt.legal_limit_ppb_codex
                FROM enforcement_records er
                JOIN contaminants cnt ON cnt.id = er.contaminant_id
                WHERE {where}
                ORDER BY month
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def analyze(
        self,
        district_id: Optional[int] = None,
        commodity_id: Optional[int] = None,
        contaminant_id: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> TrendResult:
        rows = self._load_monthly_records(district_id, commodity_id, contaminant_id, from_date, to_date)

        by_month: dict[str, list[dict]] = {}
        for r in rows:
            by_month.setdefault(r["month"].isoformat(), []).append(r)

        series: list[MonthlyPoint] = []
        for m in sorted(by_month.keys()):
            recs = by_month[m]
            values = [float(r["raw_value_ppb"]) for r in recs if r["raw_value_ppb"] is not None]
            if not values:
                continue
            fssai_fails = [r for r in recs if r["pass_fail"] is False]
            codex_fails = [
                r
                for r in recs
                if r["legal_limit_ppb_codex"] and r["raw_value_ppb"]
                and float(r["raw_value_ppb"]) > float(r["legal_limit_ppb_codex"])
            ]
            series.append(
                MonthlyPoint(
                    month=m,
                    mean_ppb=round(float(np.mean(values)), 4),
                    max_ppb=round(float(np.max(values)), 4),
                    fail_rate_fssai=round(len(fssai_fails) / len(recs), 4),
                    fail_rate_codex=round(len(codex_fails) / len(recs), 4),
                    n_records=len(recs),
                )
            )

        if len(series) < MIN_MONTHS:
            return TrendResult(series=series, trend="insufficient_data", trend_pvalue=None, trend_magnitude=None)

        time_idx = np.arange(len(series))
        values_arr = np.array([p.mean_ppb for p in series])

        tau, p_value = stats.kendalltau(time_idx, values_arr)
        slope = self._sens_slope(time_idx, values_arr)

        if p_value >= SIGNIFICANCE_P or np.isnan(p_value):
            trend = "stable"
        elif slope > 0:
            trend = "worsening"
        else:
            trend = "improving"

        return TrendResult(
            series=series,
            trend=trend,
            trend_pvalue=round(float(p_value), 4) if not np.isnan(p_value) else None,
            trend_magnitude=round(float(slope), 4),
        )

    @staticmethod
    def _sens_slope(x: np.ndarray, y: np.ndarray) -> float:
        """Median of all pairwise slopes — robust trend magnitude estimator,
        the standard companion to the Mann-Kendall test."""
        n = len(x)
        slopes = [
            (y[j] - y[i]) / (x[j] - x[i])
            for i in range(n)
            for j in range(i + 1, n)
            if x[j] != x[i]
        ]
        return float(np.median(slopes)) if slopes else 0.0

    def close(self):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None


def main():
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    district_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    commodity_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    contaminant_id = int(sys.argv[3]) if len(sys.argv) > 3 else None

    analyzer = TrendAnalyzer()
    try:
        result = analyzer.analyze(district_id, commodity_id, contaminant_id)
    finally:
        analyzer.close()

    print(f"trend={result.trend} p={result.trend_pvalue} slope={result.trend_magnitude} months={len(result.series)}")
    for p in result.series:
        print(f"  {p.month}: mean={p.mean_ppb} n={p.n_records}")


if __name__ == "__main__":
    main()
