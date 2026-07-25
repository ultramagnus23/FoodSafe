-- ============================================================
-- FoodSafe India — Schema Additions (migration_007)
-- Run AFTER schema_migration_006.sql
-- Adds: consumer_reports (H2.4 — report-an-issue intake).
--
-- Deliberately a separate table from enforcement_records, not another
-- source_type on it: enforcement_records' schema assumes a lab-measured
-- contaminant_id + raw_value_ppb against a legal limit, which a consumer
-- complaint usually doesn't have. Consumer reports are a distinct,
-- low-credibility, high-volume signal — never auto-published, never
-- surfaced with the same visual weight as a lab-verified record.
-- ============================================================

CREATE TABLE IF NOT EXISTS consumer_reports (
    id                    BIGSERIAL PRIMARY KEY,
    submitted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reporter_email        TEXT,                    -- optional, follow-up only, never shown publicly
    commodity_id          INTEGER REFERENCES commodities(id),
    district_id           INTEGER REFERENCES districts(id),
    brand_id              INTEGER REFERENCES brands(id),
    description           TEXT NOT NULL,
    contaminant_suspected TEXT,                     -- free text; not a validated contaminant_id
    review_status         TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'published', 'rejected')),
    reviewed_by           UUID REFERENCES users(id),
    reviewed_at           TIMESTAMPTZ,
    reviewer_notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_consumer_reports_status
    ON consumer_reports (review_status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_consumer_reports_district
    ON consumer_reports (district_id) WHERE review_status = 'published';
