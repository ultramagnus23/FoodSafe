-- ============================================================
-- FoodSafe India — Schema Additions (migration_024)
-- Run AFTER schema_migration_023.sql
--
-- health_outcome_profile: "what does the contamination recorded in food from
-- <origin> point to, health-wise?" One row per (scope, outcome): how many
-- notifications had at least one hazard known to cause that outcome, which
-- hazards, which products, which years, and the sources behind the link.
-- Computed by models/health_profile.py from rasff_notifications/rasff_hazards and
-- the hazard -> health knowledge base (migration 022).
--
-- How to read it: a count of contamination FINDINGS whose hazard can cause the
-- outcome, never a count of illnesses. level_counts separates findings linked
-- through a named hazard ('hazard') from those linked only through a hazard
-- class or category ('class').
--
-- Idempotent: bootstrap_db re-applies every migration daily.
-- ============================================================

CREATE TABLE IF NOT EXISTS health_outcome_profile (
    id                    BIGSERIAL PRIMARY KEY,
    scope_type            TEXT NOT NULL,            -- 'rasff_origin'
    scope_key             TEXT NOT NULL,            -- ISO-2 origin, or 'ALL'
    outcome_key           TEXT NOT NULL,
    outcome               TEXT NOT NULL,
    organ_system          TEXT NOT NULL,
    exposure              TEXT NOT NULL,
    notifications         INT NOT NULL,             -- distinct notifications with >= 1 hazard linked to the outcome
    share_of_classified   NUMERIC,                  -- of notifications with >= 1 classified hazard in this scope
    serious_notifications INT NOT NULL,
    level_counts          JSONB NOT NULL,           -- {"hazard": n, "class": m}
    top_hazards           JSONB NOT NULL,           -- [[hazard label, n], ...]
    top_products          JSONB NOT NULL,           -- [[product category, n], ...]
    by_year               JSONB NOT NULL,           -- {"2024": n, ...}
    sources               JSONB NOT NULL,           -- [{"title":..., "url":...}]
    vulnerable_groups     TEXT[] NOT NULL DEFAULT '{}',
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scope_type, scope_key, outcome_key)
);

CREATE INDEX IF NOT EXISTS idx_health_profile_scope ON health_outcome_profile (scope_type, scope_key);

GRANT SELECT ON health_outcome_profile TO foodsafe_app;
