-- ============================================================
-- FoodSafe India — Schema Additions (migration_006)
-- Run AFTER schema_migration_005.sql
-- Adds: enforcement_records.is_retracted (H2.6 — disputes -> confidence
-- feedback loop). Distinct from is_duplicate (which means "this is a
-- re-scrape of a record we already have"), is_retracted means "a dispute
-- review concluded this record shouldn't count," so the two reasons for
-- excluding a row from aggregation stay independently auditable.
-- ============================================================

ALTER TABLE enforcement_records
    ADD COLUMN IF NOT EXISTS is_retracted BOOLEAN NOT NULL DEFAULT FALSE;
