-- ============================================================
-- FoodSafe India — Schema Additions (migration_013)
-- Run AFTER schema_migration_012.sql
-- Adds: state_enforcement_annual — real State/UT x fiscal-year FSSAI
-- enforcement counts, sourced from Lok Sabha (Parliament) written answers
-- via pipeline/sources/loksabha_qa.py.
--
-- This is the first REAL state-level enforcement data this project has
-- ever had. FSSAI/FoSCoS publish nothing structured (confirmed via direct
-- API probing, see docs/FSSAI_INGESTION.md) and the RTI filed 2026-07-11
-- (reg. FSSAI/R/E/26/00836) came back unable to provide it directly — but
-- the same numbers are disclosed via Parliament's own public accountability
-- record (Lok Sabha unstarred questions to the Ministry of Health & Family
-- Welfare), answered in writing and published as PDFs at sansad.in with no
-- auth/encryption barrier. This is a real finding for the paper: the
-- access barrier is FSSAI's own channels specifically, not a fundamental
-- absence of the data within government.
--
-- One row per (state, fiscal_year, source_question_no) — not deduplicated
-- across questions, since two different MPs' questions asking overlapping
-- year ranges are two independent citable disclosures, and any numeric
-- discrepancy between them (e.g. later revisions) is itself worth being
-- able to see, not silently overwritten.
-- ============================================================

CREATE TABLE IF NOT EXISTS state_enforcement_annual (
    id                          BIGSERIAL PRIMARY KEY,
    state                       TEXT NOT NULL,
    fiscal_year                 TEXT NOT NULL,   -- e.g. '2024-2025', as printed in the source table
    samples_analyzed            INTEGER,
    civil_cases_decided_penalty INTEGER,
    criminal_cases_convictions  INTEGER,
    licenses_cancelled          INTEGER,
    source_question_no          INTEGER NOT NULL,
    source_ministry             TEXT,
    source_question_subject     TEXT,
    answered_date               DATE,
    source_url                  TEXT NOT NULL,
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (state, fiscal_year, source_question_no)
);

CREATE INDEX IF NOT EXISTS idx_state_enforcement_annual_state ON state_enforcement_annual (state);
CREATE INDEX IF NOT EXISTS idx_state_enforcement_annual_year ON state_enforcement_annual (fiscal_year);

GRANT SELECT ON state_enforcement_annual TO foodsafe_app;
