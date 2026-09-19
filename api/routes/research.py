"""
FoodSafe India — Scientific Evidence Routes
GET /v1/research               list, filterable by contaminant_id and title search (q), paginated
GET /v1/research/summary       distinct-paper count + breakdown by contaminant/study design/source
GET /v1/research/{id}          single record with full abstract

Public reference content (no auth), same as the other read-only lookup
endpoints in api/other_routes.py's meta_router. Backed by two real,
cross-deduped connectors — pipeline/sources/research_evidence.py (OpenAlex)
and pipeline/sources/europepmc_evidence.py (Europe PMC) — never
AI-generated. See docs/RESEARCH_EVIDENCE_INGESTION.md for the evidence-level
rule (only 'B'/'C' are ever stored — see schema_migration_015/016.sql) and
what study_design values mean.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from api.db import get_pool

research_router = APIRouter()

# Postgres INTEGER ceiling. A larger id would make asyncpg raise (-> HTTP 500)
# instead of matching nothing, so it is rejected at the boundary with a 422.
_INT4_MAX = 2_147_483_647
_MAX_OFFSET = 1_000_000

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
    study_design: Optional[str]
    source_apis: list[str]


class ResearchDetail(ResearchListItem):
    abstract: str
    pmid: Optional[str]
    pmcid: Optional[str]
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
           rs.is_oa, rs.study_design, rs.source_apis
    {_JOIN_CLAUSE}
"""

_DETAIL_SELECT = f"""
    SELECT rs.id, crl.contaminant_id, c.name_canonical AS contaminant_name,
           rs.title, rs.authors, rs.journal, rs.publication_year, rs.doi,
           rs.landing_page_url, crl.evidence_level, crl.matched_health_terms,
           rs.is_oa, rs.study_design, rs.source_apis,
           rs.abstract, rs.pmid, rs.pmcid, rs.oa_status, rs.work_type
    {_JOIN_CLAUSE}
"""


class ContaminantPaperCount(BaseModel):
    contaminant_id: int
    contaminant_name: str
    papers: int


class ResearchSummary(BaseModel):
    total_papers: int
    total_links: int
    by_contaminant: list[ContaminantPaperCount]
    by_study_design: dict[str, int]
    by_source: dict[str, int]


@research_router.get("/summary", response_model=ResearchSummary)
async def research_summary():
    """Declared before /{source_id} so 'summary' isn't parsed as an int id.

    total_papers counts distinct research_sources rows; total_links counts
    (contaminant, paper) pairs, which is larger because one paper can be
    linked to several contaminants (e.g. aflatoxin B1 and total aflatoxin).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        total_papers = await conn.fetchval("SELECT COUNT(*) FROM research_sources")
        total_links = await conn.fetchval("SELECT COUNT(*) FROM contaminant_research_links")
        by_contaminant = await conn.fetch(
            """
            SELECT c.id AS contaminant_id, c.name_canonical AS contaminant_name, COUNT(*) AS papers
            FROM contaminant_research_links crl
            JOIN contaminants c ON c.id = crl.contaminant_id
            GROUP BY c.id, c.name_canonical
            ORDER BY c.id
            """
        )
        by_design = await conn.fetch(
            "SELECT COALESCE(study_design, 'unclassified') AS k, COUNT(*) AS n FROM research_sources GROUP BY 1 ORDER BY 2 DESC"
        )
        by_source = await conn.fetch(
            "SELECT s AS k, COUNT(*) AS n FROM research_sources, unnest(source_apis) AS s GROUP BY s ORDER BY 2 DESC"
        )

    return ResearchSummary(
        total_papers=total_papers or 0,
        total_links=total_links or 0,
        by_contaminant=[ContaminantPaperCount(**dict(r)) for r in by_contaminant],
        by_study_design={r["k"]: r["n"] for r in by_design},
        by_source={r["k"]: r["n"] for r in by_source},
    )


@research_router.get("", response_model=ResearchListResponse)
async def list_research(
    contaminant_id: Optional[int] = Query(None, ge=1, le=_INT4_MAX),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=_MAX_OFFSET),
):
    # $2 is a bound parameter, never interpolated into the SQL text. Escape
    # LIKE wildcards so a user typing '%' or '_' searches for the literal.
    # NUL is stripped first: Postgres text cannot hold it and asyncpg raises.
    pattern = None
    term = (q or "").replace("\x00", "").strip()
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"

    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM contaminant_research_links crl
            JOIN research_sources rs ON rs.id = crl.research_source_id
            WHERE ($1::int IS NULL OR crl.contaminant_id = $1)
              AND ($2::text IS NULL OR rs.title ILIKE $2)
            """,
            contaminant_id, pattern,
        )
        rows = await conn.fetch(
            _LIST_SELECT + """
            WHERE ($1::int IS NULL OR crl.contaminant_id = $1)
              AND ($2::text IS NULL OR rs.title ILIKE $2)
            ORDER BY rs.publication_year DESC NULLS LAST, rs.id, crl.contaminant_id
            LIMIT $3 OFFSET $4
            """,
            contaminant_id, pattern, limit, offset,
        )

    return ResearchListResponse(
        results=[
            ResearchListItem(
                id=r["id"], contaminant_id=r["contaminant_id"], contaminant_name=r["contaminant_name"],
                title=r["title"], authors=list(r["authors"]), journal=r["journal"],
                publication_year=r["publication_year"], doi=r["doi"],
                landing_page_url=r["landing_page_url"], evidence_level=r["evidence_level"],
                matched_health_terms=list(r["matched_health_terms"]), is_oa=r["is_oa"],
                study_design=r["study_design"], source_apis=list(r["source_apis"]),
            )
            for r in rows
        ],
        total=total or 0,
        disclaimer=RESEARCH_DISCLAIMER,
    )


@research_router.get("/{source_id}", response_model=ResearchDetail)
async def get_research(
    source_id: int = Path(..., ge=1, le=_INT4_MAX),
    contaminant_id: Optional[int] = Query(None, ge=1, le=_INT4_MAX),
):
    """A paper can be linked to several contaminants, so the row is one
    (paper, contaminant) pair. Pass contaminant_id (the list endpoint returns
    it per row) to get that pair; without it the lowest contaminant_id is
    returned, so the answer is at least deterministic."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _DETAIL_SELECT + """
            WHERE rs.id = $1 AND ($2::int IS NULL OR crl.contaminant_id = $2)
            ORDER BY crl.contaminant_id
            LIMIT 1
            """,
            source_id, contaminant_id,
        )
    if not row:
        raise HTTPException(404, "Research source not found")

    return ResearchDetail(
        id=row["id"], contaminant_id=row["contaminant_id"], contaminant_name=row["contaminant_name"],
        title=row["title"], authors=list(row["authors"]), journal=row["journal"],
        publication_year=row["publication_year"], doi=row["doi"],
        landing_page_url=row["landing_page_url"], evidence_level=row["evidence_level"],
        matched_health_terms=list(row["matched_health_terms"]), is_oa=row["is_oa"],
        study_design=row["study_design"], source_apis=list(row["source_apis"]),
        abstract=row["abstract"], pmid=row["pmid"], pmcid=row["pmcid"],
        oa_status=row["oa_status"], work_type=row["work_type"],
    )
