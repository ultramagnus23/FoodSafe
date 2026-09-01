-- ============================================================
-- FoodSafe India — Schema Additions (migration_012)
-- Run AFTER schema_migration_011.sql
-- Extends `labs` (schema.sql) with provenance so real, scraped rows
-- (pipeline/sources/fssai_labs.py) can be told apart from the 5 synthetic
-- demo rows already in this table (pipeline/seed_enforcement.py,
-- 'QuickTest Pvt Labs' etc.) — those 5 are left in place because
-- enforcement_records rows already reference them via lab_id FK; deleting
-- them would either cascade-break or require re-pointing real
-- enforcement_records, out of scope here. source_url IS NULL is the
-- discriminator for "synthetic / unknown provenance".
-- ============================================================

ALTER TABLE labs ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE labs ADD COLUMN IF NOT EXISTS accreditation_ref TEXT;  -- e.g. NABL cert / registration number, distinct from the free-text `accreditation` column
ALTER TABLE labs ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;

-- Needed for idempotent upserts (ON CONFLICT (name) DO UPDATE) — safe to add
-- now since a quick check found no duplicate `name` values among the 5
-- existing rows.
ALTER TABLE labs ADD CONSTRAINT labs_name_key UNIQUE (name);
