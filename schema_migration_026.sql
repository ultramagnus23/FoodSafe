-- ============================================================
-- FoodSafe India — Schema Additions (migration_026)
-- Run AFTER schema_migration_025.sql
--
-- packaged_foods: packaged products sold in India, from Open Food Facts (open,
-- crowd-sourced label transcriptions; ODbL), with FoodSafe's nutrition
-- classification (models/nutrition.py: UK DHSC front-of-pack traffic lights for
-- fat, saturates, sugars and salt per 100 g / 100 ml). Nutri-Score and NOVA are
-- stored as Open Food Facts computes them, not recomputed.
-- Loaded by pipeline/sources/off_india.py. Label data, not lab analyses.
--
-- Idempotent: bootstrap_db re-applies every migration daily.
-- ============================================================

CREATE TABLE IF NOT EXISTS packaged_foods (
    code                TEXT PRIMARY KEY,          -- barcode (GTIN/EAN)
    product_name        TEXT,
    brands              TEXT,
    categories          TEXT[] NOT NULL DEFAULT '{}',
    countries           TEXT[] NOT NULL DEFAULT '{}',
    nutriscore_grade    TEXT CHECK (nutriscore_grade IS NULL OR nutriscore_grade IN ('a', 'b', 'c', 'd', 'e')),
    nutriscore_score    INT,
    nova_group          INT CHECK (nova_group IS NULL OR nova_group BETWEEN 1 AND 4),
    energy_kcal_100g    NUMERIC,
    fat_100g            NUMERIC,
    saturated_fat_100g  NUMERIC,
    sugars_100g         NUMERIC,
    salt_100g           NUMERIC,
    fiber_100g          NUMERIC,
    proteins_100g       NUMERIC,
    additives           TEXT[] NOT NULL DEFAULT '{}',
    allergens           TEXT[] NOT NULL DEFAULT '{}',
    ingredients_text    TEXT,
    quantity            TEXT,
    last_modified       TIMESTAMPTZ,
    nutrition           JSONB NOT NULL,            -- {basis, lights{fat,saturates,sugars,salt}, high_in[], complete}
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_packaged_foods_grade ON packaged_foods (nutriscore_grade);
CREATE INDEX IF NOT EXISTS idx_packaged_foods_cats  ON packaged_foods USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_packaged_foods_brand ON packaged_foods (lower(brands));

GRANT SELECT ON packaged_foods TO foodsafe_app;
