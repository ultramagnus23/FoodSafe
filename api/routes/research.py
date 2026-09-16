"""
FoodSafe India — Scientific Evidence Routes
GET /v1/research               list, optionally filtered by contaminant_id
GET /v1/research/{id}          single record with full abstract

Public reference content (no auth), same as the other read-only lookup
endpoints in api/other_routes.py's meta_router. Backed by
pipeline/sources/research_evidence.py — real OpenAlex works, never
AI-generated. See docs/RESEARCH_EVIDENCE_INGESTION.md for the evidence-level
rule (only 'B'/'C' are ever stored — see schema_migration_015.sql).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool

research_router = APIRouter()

RESEARCH_DISCLAIMER = (
    "These are peer-reviewed scientific sources associating a contaminant "
    "with a disease or health outcome in general literature — not a claim "
    "that the contaminant was found in any specific Indian sample or "
    "product. Evidence level reflects source type only (B = review, "
    "C = individual study), not the strength of any causal link."
)


class ResearchListItem(BaseModel):
    id: int
    contaminant_id: int
    contaminant_name: str
    title: str
    authors: list[str]
    journal: Optional[str]
    publication_year: Optional[int]
    doi: Optional[str]
    landing_page_url: str
    evidence_level: str
    matched_health_terms: list[str]
    is_oa: Optional[bool]


class ResearchDetail(ResearchListItem):
    abstract: str
    pmid: Optional[str]
    oa_status: Optional[str]
    work_type: Optional[str]


class ResearchListResponse(BaseModel):
    results: list[ResearchListItem]
    total: int
    disclaimer: str


_JOIN_CLAUSE = """
    FROM contaminant_research_links crl
    JOIN research_sources rs ON rs.id = crl.research_source_id
    JOIN contaminants c ON c.id = crl.contaminant_id
"""

_LIST_SELECT = f"""
    SELECT rs.id, crl.contaminant_id, c.name_canonical AS contaminant_name,
           rs.title, rs.authors, rs.journal, rs.publication_year, rs.doi,
           rs.landing_page_url, crl.evidence_level, crl.matched_health_terms,
           rs.is_oa
    {_JOIN_CLAUSE}
"""

_DETAIL_SELECT = f"""
    SELECT rs.id, crl.contaminant_id, c.name_canonical AS contaminant_name,
           rs.title, rs.authors, rs.journal, rs.publication_year, rs.doi,
           rs.landing_page_url, crl.evidence_level, crl.matched_health_terms,
           rs.is_oa, rs.abstract, rs.pmid, rs.oa_status, rs.work_type
    {_JOIN_CLAUSE}
"""


@research_router.get("", response_model=ResearchListResponse)
async def list_research(
    contaminant_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM contaminant_research_links WHERE ($1::int IS NULL OR contaminant_id = $1)",
            contaminant_id,
        )
        rows = await conn.fetch(
            _LIST_SELECT + """
            WHERE ($1::int IS NULL OR crl.contaminant_id = $1)
            ORDER BY rs.publication_year DESC NULLS LAST, rs.id
            LIMIT $2 OFFSET $3
            """,
            contaminant_id, limit, offset,
        )

    return ResearchListResponse(
        results=[
            ResearchListItem(
                id=r["id"], contaminant_id=r["contaminant_id"], contaminant_name=r["contaminant_name"],
                title=r["title"], authors=list(r["authors"]), journal=r["journal"],
                publication_year=r["publication_year"], doi=r["doi"],
                landing_page_url=r["landing_page_url"], evidence_level=r["evidence_level"],
                matched_health_terms=list(r["matched_health_terms"]), is_oa=r["is_oa"],
            )
            for r in rows
        ],
        total=total or 0,
        disclaimer=RESEARCH_DISCLAIMER,
    )


@research_router.get("/{source_id}", response_model=ResearchDetail)
async def get_research(source_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _DETAIL_SELECT + " WHERE rs.id = $1 LIMIT 1",
            source_id,
        )
    if not row:
        raise HTTPException(404, "Research source not found")

    return ResearchDetail(
        id=row["id"], contaminant_id=row["contaminant_id"], contaminant_name=row["contaminant_name"],
        title=row["title"], authors=list(row["authors"]), journal=row["journal"],
        publication_year=row["publication_year"], doi=row["doi"],
        landing_page_url=row["landing_page_url"], evidence_level=row["evidence_level"],
        matched_health_terms=list(row["matched_health_terms"]), is_oa=row["is_oa"],
        abstract=row["abstract"], pmid=row["pmid"], oa_status=row["oa_status"],
        work_type=row["work_type"],
    )
