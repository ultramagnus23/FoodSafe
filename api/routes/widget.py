"""
FoodSafe India — Embeddable Widget Data (H2.5)
GET /v1/widget/district/{district_id}/commodity/{commodity_id}

Public, unauthenticated, read-only — the data backing the embeddable
district-risk widget (frontend/app/embed/district/[id]) that journalists
and local news sites can iframe. Deliberately a separate, narrower endpoint
from /v1/risk/district/... rather than making that one public: this one
returns only what a widget needs to render responsibly (score, provenance,
disclaimer), not the full enforcement-event list or brand data.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_pool
from api.provenance import ProvenanceSummary, fetch_provenance
from api.routes.risk import build_disclaimer

widget_router = APIRouter()


class WidgetData(BaseModel):
    district_id: int
    district_name: str
    state: str
    commodity_id: int
    commodity_name: str
    risk_score: Optional[float]
    n_tests: int
    provenance: ProvenanceSummary
    disclaimer: str
    last_updated: Optional[str]


@widget_router.get("/district/{district_id}/commodity/{commodity_id}", response_model=WidgetData)
async def widget_district_risk(district_id: int, commodity_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        district = await conn.fetchrow(
            "SELECT id, name_canonical, state FROM districts WHERE id = $1", district_id
        )
        if not district:
            raise HTTPException(404, "District not found")

        commodity = await conn.fetchrow(
            "SELECT id, name_canonical FROM commodities WHERE id = $1", commodity_id
        )
        if not commodity:
            raise HTTPException(404, "Commodity not found")

        agg = await conn.fetchrow(
            """
            SELECT risk_score, n_tests, last_updated
            FROM agg_district_commodity_risk
            WHERE district_id = $1 AND commodity_id = $2
            ORDER BY quarter DESC LIMIT 1
            """,
            district_id, commodity_id,
        )

        provenance = await fetch_provenance(
            conn, "district_id = $1 AND commodity_id = $2", district_id, commodity_id,
        )

    return WidgetData(
        district_id=district_id,
        district_name=district["name_canonical"],
        state=district["state"],
        commodity_id=commodity_id,
        commodity_name=commodity["name_canonical"],
        risk_score=float(agg["risk_score"]) if agg and agg["risk_score"] is not None else None,
        n_tests=(agg["n_tests"] if agg else 0) or 0,
        provenance=provenance,
        disclaimer=build_disclaimer(commodity["name_canonical"], district["name_canonical"]),
        last_updated=str(agg["last_updated"]) if agg else None,
    )
