-- ============================================================
-- FoodSafe India — Schema Additions (migration_005)
-- Run AFTER schema_migration_004.sql
-- Adds: pipeline_runs (H1.3 — scraper health / ingest observability).
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id             BIGSERIAL PRIMARY KEY,
    source         TEXT NOT NULL,               -- 'openfda' | 'agmarknet' | 'fssai_recall'
    status         TEXT NOT NULL DEFAULT 'running',
        -- 'running' | 'success' | 'expected_failure' | 'failed'
        -- expected_failure = a known, accepted outcome (e.g. FoSCoS's
        -- documented 401/maintenance gate, or AGMARKNET's flaky public
        -- rate limit) — not something to page anyone about. See
        -- docs/FSSAI_INGESTION.md and pipeline/run_and_log.py.
    rows_ingested  INTEGER,
    error_detail   TEXT,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ,
    workflow_run_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source_started
    ON pipeline_runs (source, started_at DESC);
