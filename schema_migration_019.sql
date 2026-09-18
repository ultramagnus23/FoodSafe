-- ============================================================
-- FoodSafe India — Schema Additions (migration_019)
-- Run AFTER schema_migration_018.sql
-- Adds: state_sampling_annual, loksabha_question_log — real State/UT x fiscal
-- year counts of food samples analysed vs found non-conforming, from Lok
-- Sabha written answers, via pipeline/sources/loksabha_sampling.py.
--
-- Why this matters: docs/BACKTEST_REPORT.md found no source in this project
-- with BOTH outcomes (every openFDA record is a recall, i.e. a failure). These
-- are sampled-testing counts with a pass side (analysed - non-conforming).
--
-- Two definitions are kept apart and never merged (non_conforming_basis):
--   'non_conforming'         — "found non-conforming" (recent answers)
--   'adulterated_misbranded' — "found adulterated and misbranded" (older
--                              answers). A non-conforming sample is not
--                              necessarily unsafe.
--
-- verification records what supports a row:
--   'total_row_sum'   — the table's printed Total equals the column sums
--   'total_row_close' — within 0.1% of the printed Total (a source typo)
--   'row_invariants'  — no printed Total; contiguous serial numbers and
--                       row-level checks only. Cross-answer agreement is
--                       computed at query time (see /v1/meta/state-sampling).
-- fy_source records where the fiscal year came from: the table's own title,
-- or the text directly above it (weaker).
--
-- One row per (state, fiscal_year, basis, lok_sabha_no, question_no): the
-- same (state, year) can be disclosed in several answers, sometimes at
-- different vintages; all are kept, none merged, so conflicts stay visible.
--
-- loksabha_question_log records every question examined and why a table was
-- accepted or rejected, so daily runs skip finished questions and rejections
-- are auditable. Both statements are IF NOT EXISTS so bootstrap_db can re-run
-- this file every day.
-- ============================================================

CREATE TABLE IF NOT EXISTS state_sampling_annual (
    id                       BIGSERIAL PRIMARY KEY,
    state                    TEXT NOT NULL,
    fiscal_year              TEXT NOT NULL,   -- 'YYYY-YYYY'
    samples_analyzed         INTEGER NOT NULL CHECK (samples_analyzed >= 0),
    samples_non_conforming   INTEGER NOT NULL CHECK (samples_non_conforming >= 0),
    non_conforming_basis     TEXT NOT NULL CHECK (non_conforming_basis IN ('non_conforming', 'adulterated_misbranded')),
    verification             TEXT NOT NULL CHECK (verification IN ('total_row_sum', 'total_row_close', 'row_invariants')),
    fy_source                TEXT NOT NULL CHECK (fy_source IN ('table_title', 'text_above')),
    lok_sabha_no             INTEGER NOT NULL,
    source_question_no       INTEGER NOT NULL,
    source_question_subject  TEXT,
    answered_date            DATE,
    source_url               TEXT NOT NULL,
    source_page              INTEGER,
    parser_version           TEXT NOT NULL,
    fetched_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (samples_non_conforming <= samples_analyzed),
    UNIQUE (state, fiscal_year, non_conforming_basis, lok_sabha_no, source_question_no)
);

CREATE INDEX IF NOT EXISTS idx_state_sampling_annual_state ON state_sampling_annual (state);
CREATE INDEX IF NOT EXISTS idx_state_sampling_annual_year  ON state_sampling_annual (fiscal_year);

CREATE TABLE IF NOT EXISTS loksabha_question_log (
    lok_sabha_no        INTEGER NOT NULL,
    source_question_no  INTEGER NOT NULL,
    parser_version      TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('parsed', 'rejected_only', 'no_sampling_table', 'fetch_error')),
    groups_accepted     INTEGER NOT NULL DEFAULT 0,
    groups_rejected     INTEGER NOT NULL DEFAULT 0,
    reject_detail       JSONB,
    source_url          TEXT,
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (lok_sabha_no, source_question_no, parser_version)
);

GRANT SELECT ON state_sampling_annual, loksabha_question_log TO foodsafe_app;
