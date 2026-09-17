-- ============================================================
-- FoodSafe India — Schema Additions (migration_016)
-- Run AFTER schema_migration_015.sql
-- Adds a second real evidence source, Europe PMC
-- (pipeline/sources/europepmc_evidence.py), cross-deduped against the
-- existing OpenAlex-sourced rows from migration_015 by DOI/PMID rather
-- than inserted as duplicates.
--
-- Europe PMC's `pubTypeList` gives real per-work publication types
-- (Systematic Review, Meta-Analysis, Randomized Controlled Trial,
-- Cohort Studies, Case Reports, ...) that OpenAlex's single `type` field
-- (article/review) can't distinguish. `study_design` stores that richer,
-- source-reported classification. It is deliberately free TEXT, not a
-- CHECK-constrained enum: Europe PMC's vocabulary is broad and this
-- project should be able to record a new pubType value without a schema
-- migration every time. `evidence_level` (schema_migration_015.sql)
-- keeps its own strict 'B'/'C' CHECK — study_design can only ever
-- *upgrade* an existing link from C to B (systematic_review/
-- meta_analysis), never invent an A or D tier. See
-- docs/RESEARCH_EVIDENCE_INGESTION.md.
-- ============================================================

ALTER TABLE research_sources ADD COLUMN IF NOT EXISTS study_design TEXT;
ALTER TABLE research_sources ADD COLUMN IF NOT EXISTS pmcid TEXT;
-- Which connector(s) have confirmed this row — an audit trail, not a
-- functional dedup key (doi/openalex_id already are).
ALTER TABLE research_sources ADD COLUMN IF NOT EXISTS source_apis TEXT[] NOT NULL DEFAULT '{}';

-- Backfill: every row that exists before this migration was necessarily
-- inserted by research_evidence.py (OpenAlex) — migration_015 shipped
-- before this one, and europepmc_evidence.py doesn't exist until now.
UPDATE research_sources SET source_apis = ARRAY['openalex'] WHERE source_apis = '{}';
