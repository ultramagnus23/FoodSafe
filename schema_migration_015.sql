-- ============================================================
-- FoodSafe India — Schema Additions (migration_015)
-- Run AFTER schema_migration_014.sql
-- Adds: research_sources, contaminant_research_links — real, peer-reviewed
-- scientific literature (OpenAlex API, https://openalex.org) linking a
-- contaminant already in `contaminants` to disease/health-outcome
-- literature, via pipeline/sources/research_evidence.py.
--
-- This is a citation layer, not a local measurement: it never claims a
-- contaminant was found in an Indian sample, only that peer-reviewed
-- literature associates that contaminant with a health outcome somewhere.
-- evidence_level is restricted to 'B' (OpenAlex type == 'review') and 'C'
-- (any other peer-reviewed work with a DOI and abstract) — never 'A'
-- (would require this project's own direct measurement) or 'D'
-- (mechanistic/toxicology — would need full text, not just an abstract,
-- to classify honestly). See docs/RESEARCH_EVIDENCE_INGESTION.md.
-- ============================================================

CREATE TABLE IF NOT EXISTS research_sources (
    id                BIGSERIAL PRIMARY KEY,
    title             TEXT NOT NULL,
    authors           TEXT[] NOT NULL DEFAULT '{}',
    journal           TEXT,
    publication_year  INT,
    doi               TEXT UNIQUE,
    openalex_id       TEXT UNIQUE,
    pmid              TEXT,
    abstract          TEXT NOT NULL,
    work_type         TEXT,            -- OpenAlex 'type': article, review, ...
    oa_status         TEXT,            -- gold/green/hybrid/closed/bronze
    is_oa             BOOLEAN,
    landing_page_url  TEXT NOT NULL,
    fetched_query     TEXT NOT NULL,   -- the contaminant search term that found it
    retrieved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contaminant_research_links (
    id                    BIGSERIAL PRIMARY KEY,
    contaminant_id        INT NOT NULL REFERENCES contaminants(id),
    research_source_id    BIGINT NOT NULL REFERENCES research_sources(id),
    evidence_level        TEXT NOT NULL CHECK (evidence_level IN ('B','C')),
    matched_health_terms  TEXT[] NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contaminant_id, research_source_id)
);

CREATE INDEX IF NOT EXISTS idx_contaminant_research_links_contaminant
    ON contaminant_research_links (contaminant_id);

GRANT SELECT ON research_sources TO foodsafe_app;
GRANT SELECT ON contaminant_research_links TO foodsafe_app;
