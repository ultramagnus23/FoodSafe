-- ============================================================
-- FoodSafe India — Schema Additions (migration_011)
-- Run AFTER schema_migration_010.sql
-- Adds: state_commissioners — real State/UT Commissioner of Food Safety
-- contact directory, scraped from fssai.gov.in/business/commissioners-of-food-safety
-- (see pipeline/sources/fssai_commissioners.py). This is a real,
-- FSSAI-published directory, not synthetic/demo data — but it's contact
-- metadata, not enforcement/contamination data, so it does NOT feed
-- enforcement_records or the risk aggregation. It exists to answer "who do
-- we escalate a finding to in this state" — a real, previously-missing
-- capability, not a stand-in for actual district-level violation data.
-- ============================================================

CREATE TABLE IF NOT EXISTS state_commissioners (
    id                BIGSERIAL PRIMARY KEY,
    state             TEXT NOT NULL UNIQUE,
    commissioner_name TEXT,
    address           TEXT,
    contact           TEXT,
    email             TEXT,
    nodal_officer     TEXT,
    source_url        TEXT NOT NULL,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

GRANT SELECT ON state_commissioners TO foodsafe_app;
