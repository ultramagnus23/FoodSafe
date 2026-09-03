-- ============================================================
-- FoodSafe India — Schema Additions (migration_014)
-- Run AFTER schema_migration_013.sql
-- Adds: national_enforcement_annual — real, national-level FSSAI
-- enforcement metrics (samples analysed, non-conforming breakdown, civil
-- and criminal case outcomes with penalty amounts), one row per fiscal
-- year, sourced from each year's FSSAI Annual Report PDF's own
-- "Progress on enforcement metrics" table via
-- pipeline/sources/fssai_annual_report.py.
--
-- This table is deliberately NOT state-wise (that's
-- state_enforcement_annual, migration_013, from Lok Sabha answers) — it's
-- the single national total FSSAI itself publishes annually, and it's the
-- longest time series of real enforcement data in this project (Annual
-- Reports go back to FY2009-10, though only recent years with
-- small-enough files have been ingested so far — see that module's
-- YEAR_MANIFEST for which years were skipped and why, e.g. some years'
-- PDFs run 300-600MB).
-- ============================================================

CREATE TABLE IF NOT EXISTS national_enforcement_annual (
    id                         BIGSERIAL PRIMARY KEY,
    fiscal_year                TEXT NOT NULL UNIQUE,  -- e.g. '2021-2022'
    samples_analyzed           BIGINT,
    samples_non_conforming     BIGINT,
    non_conforming_unsafe      BIGINT,
    non_conforming_substandard BIGINT,
    non_conforming_labelling   BIGINT,
    civil_cases_launched       BIGINT,
    civil_cases_convictions    BIGINT,   -- only reported some years — see civil_cases_decided
    civil_cases_decided        BIGINT,   -- "decided" != "convicted" (may include non-conviction outcomes); kept distinct, not merged
    civil_penalty_amount       BIGINT,   -- rupees
    criminal_cases_launched    BIGINT,
    criminal_cases_convictions BIGINT,
    criminal_cases_decided     BIGINT,
    criminal_penalty_amount    BIGINT,   -- rupees
    criminal_acquittals        BIGINT,
    total_penalty_amount       BIGINT,   -- some years report civil+criminal penalty as one combined figure instead of split
    source_url                 TEXT NOT NULL,
    fetched_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

GRANT SELECT ON national_enforcement_annual TO foodsafe_app;
