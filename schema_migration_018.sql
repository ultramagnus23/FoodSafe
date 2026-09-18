-- ============================================================
-- FoodSafe India — Schema Additions (migration_018)
-- Run AFTER schema_migration_017.sql
-- Adds: state_enforcement_annual.lok_sabha_no, and makes it part of the
-- uniqueness key.
--
-- Why: migration_013 keyed rows on (state, fiscal_year, source_question_no).
-- Parliamentary question numbers restart every Lok Sabha, so Q1234 in the
-- 17th Lok Sabha and Q1234 in the 16th are unrelated questions. Extending
-- pipeline/sources/loksabha_qa.py beyond the 18th Lok Sabha with the old key
-- would let ON CONFLICT DO UPDATE silently overwrite one term's disclosure
-- with another's. Every row ingested before this migration came from the
-- 18th (the connector hard-coded it), hence the backfill below.
--
-- Must be re-runnable with no error: scripts/bootstrap_db.py applies each
-- file as ONE transaction on every CI run and treats a duplicate-object
-- error as "already applied", which would roll the whole file back and skip
-- the later statements. So: IF NOT EXISTS / no-op UPDATE / drop-then-add.
-- ============================================================

ALTER TABLE state_enforcement_annual ADD COLUMN IF NOT EXISTS lok_sabha_no INTEGER;

UPDATE state_enforcement_annual SET lok_sabha_no = 18 WHERE lok_sabha_no IS NULL;

ALTER TABLE state_enforcement_annual ALTER COLUMN lok_sabha_no SET NOT NULL;

-- Drop the old (state, fiscal_year, source_question_no) unique constraint
-- without depending on its auto-generated name (Postgres truncates long
-- generated names unpredictably).
DO $$
DECLARE c text;
BEGIN
    FOR c IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'state_enforcement_annual'::regclass
          AND contype = 'u'
          AND conname <> 'state_enforcement_annual_term_key'
    LOOP
        EXECUTE format('ALTER TABLE state_enforcement_annual DROP CONSTRAINT %I', c);
    END LOOP;
END $$;

ALTER TABLE state_enforcement_annual DROP CONSTRAINT IF EXISTS state_enforcement_annual_term_key;
ALTER TABLE state_enforcement_annual ADD CONSTRAINT state_enforcement_annual_term_key
    UNIQUE (state, fiscal_year, lok_sabha_no, source_question_no);
