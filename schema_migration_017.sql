-- ============================================================
-- FoodSafe India — Schema Additions (migration_017)
-- Run AFTER schema_migration_016.sql
-- Widens: enforcement_records.source_type to add a generic 'local_news'
-- value, alongside the existing city-specific 'local_news_mumbai'
-- (added in migration_009).
--
-- Why: pipeline/sources/local_news.py is being extended from Mumbai-only
-- to five metros (Mumbai, Delhi, Bengaluru, Chennai, Pune) — the same
-- five cities schema_reference_districts.sql / migrations 009-010
-- already seed real localities for. A per-city source_type value
-- ('local_news_delhi', 'local_news_bengaluru', ...) would mean a new
-- migration every time a city is added; the actual geographic
-- specificity already lives in district_id/locality_id on the same row,
-- so source_type only needs to say "this came from the local-news
-- ingester," not which city. New rows from every city now write
-- 'local_news'; existing 'local_news_mumbai' rows are left as-is, not
-- backfilled — both values remain valid.
-- ============================================================

ALTER TABLE enforcement_records DROP CONSTRAINT IF EXISTS enforcement_records_source_type_check;
ALTER TABLE enforcement_records ADD CONSTRAINT enforcement_records_source_type_check
    CHECK (source_type IN ('fssai','usfda','efsa','apeda','state_health','agmarknet','local_news_mumbai','local_news'));
