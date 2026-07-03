"""
FoodSafe India — Contamination Trend Routes
GET /v1/trends/district/{district_id}
GET /v1/trends/national

Both wrap models/trend_analysis.py (Mann-Kendall + Sen's slope). The
underlying stats work happens over a sync psycopg2 connection (models/
trend_analysis.py mirrors the pattern already used by api/routes/disease.py's
benchmark endpoint and risk.py's supply-chain fallback), run in a worker
thread so it doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import get_current_user, CurrentUser
from api.db import get_pool

logger = logging.getLogger("foodsafe.routes.trends")

trends_router = APIRouter()


class MonthlyPointOut(BaseModel):
    month: str
    mean_ppb: float
    max_ppb: float
    fail_rate_fssai: Optional[float]
    fail_rate_codex: Optional[float]
    n_records: int


class TrendResponse(BaseModel):
    series: list[MonthlyPointOut]
    trend: str  # 'improving' | 'worsening' | 'stable' | 'insufficient_data'
    trend_pvalue: Optional[float]
    trend_magnitude: Optional[float]
    disclaimer: str


TREND_DISCLAIMER = (
    "Trend classification requires at least 6 months of data and a Mann-Kendall "
    "p-value below 0.05; otherwise reported as insufficient_data, not 'stable'. "
    "Statistical estimate based on public enforcement records — not a product "
    "test result or a verdict on any specific brand, manufacturer, or batch."
)


def _run_trend_analysis(
    district_id: Optional[int], commodity_id: Optional[int], contaminant_id: Optional[int],
    from_date: Optional[date], to_date: Optional[date],
):
    from models.trend_analysis import TrendAnalyzer

    analyzer = TrendAnalyzer()
    try:
        return analyzer.analyze(
            district_id=district_id, commodity_id=commodity_id, contaminant_id=contaminant_id,
            from_date=from_date, to_date=to_date,
        )
    finally:
        analyzer.close()


@trends_router.get("/district/{district_id}", response_model=TrendResponse)
async def district_trend(
    district_id: int,
    commodity_id: Optional[int] = None,
    contaminant_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        district = await conn.fetchrow("SELECT id FROM districts WHERE id = $1", district_id)
        if not district:
            raise HTTPException(404, "District not found")

    result = await asyncio.to_thread(
        _run_trend_analysis, district_id, commodity_id, contaminant_id, date_from, date_to
    )

    return TrendResponse(
        series=[MonthlyPointOut(**p.__dict__) for p in result.series],
        trend=result.trend,
        trend_pvalue=result.trend_pvalue,
        trend_magnitude=result.trend_magnitude,
        disclaimer=TREND_DISCLAIMER,
    )


@trends_router.get("/national", response_model=TrendResponse)
async def national_trend(
    commodity_id: Optional[int] = None,
    contaminant_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user: CurrentUser = Depends(get_current_user),
):
    result = await asyncio.to_thread(
        _run_trend_analysis, None, commodity_id, contaminant_id, date_from, date_to
    )

    return TrendResponse(
        series=[MonthlyPointOut(**p.__dict__) for p in result.series],
        trend=result.trend,
        trend_pvalue=result.trend_pvalue,
        trend_magnitude=result.trend_magnitude,
        disclaimer=TREND_DISCLAIMER,
    )
