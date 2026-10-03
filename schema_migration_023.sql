-- ============================================================
-- FoodSafe India — Schema Additions (migration_023)
-- Run AFTER schema_migration_022.sql
--
-- RASFF beyond India. rasff_notifications was created India-only (a CHECK that
-- 'IN' is an origin country). The same EU feed covers every origin country —
-- ~32,800 notifications 2020 -> today — which is what lets FoodSafe compare
-- countries ("what does the EU find in food from India vs Thailand vs Turkey?")
-- and gives the hazard classifier its labelled training text.
--
--   * the India-only CHECK is dropped (idempotent: IF EXISTS). Every API route
--     that served "India's RASFF record" now filters 'IN' = ANY(origin_countries)
--     explicitly; that filter shipped before any non-India row was written.
--   * GIN index for origin-country filtering.
--   * rasff_hazards gains the classification FoodSafe adds to each hazard:
--       hazard_key    the standards/KB comparison key of the printed hazard
--                     (pipeline/sources/standards_common.hazard_key), when the
--                     hazard is a named substance or organism
--       hazard_class  class from the knowledge base or, failing that, from the
--                     notifier's own RASFF hazard category
--       classified_by 'kb_name' | 'pesticide_class' | 'rasff_category' | 'model'
--     A NULL class means "not classified", never "no hazard".
--
-- Idempotent: bootstrap_db re-applies every migration daily.
-- ============================================================

ALTER TABLE rasff_notifications DROP CONSTRAINT IF EXISTS rasff_notifications_origin_countries_check;

CREATE INDEX IF NOT EXISTS idx_rasff_notif_origins ON rasff_notifications USING GIN (origin_countries);

ALTER TABLE rasff_hazards
    ADD COLUMN IF NOT EXISTS hazard_key    TEXT,
    ADD COLUMN IF NOT EXISTS hazard_class  TEXT,
    ADD COLUMN IF NOT EXISTS classified_by TEXT;

CREATE INDEX IF NOT EXISTS idx_rasff_hazard_key ON rasff_hazards (hazard_key);
