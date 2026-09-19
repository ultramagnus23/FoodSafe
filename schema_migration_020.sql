-- ============================================================
-- FoodSafe India — Schema Additions (migration_020)
-- Run AFTER schema_migration_019.sql
-- Adds: pesticide_residue_annual — real national pesticide-residue monitoring
-- results (MPRNL: samples analysed vs samples above the FSSAI Maximum Residue
-- Limit) by commodity and period, from Lok Sabha written answers, via
-- pipeline/sources/loksabha_pesticide.py.
--
-- Grain: national x commodity x period. There is no state, district, brand or
-- product level in these answers.
--
-- The pass side is samples_analyzed - samples_above_mrl. "Above MRL" is a
-- regulatory-limit exceedance for a pesticide residue, not proof of harm.
--
-- period_kind:
--   'fiscal_year'     — one full April-March year ('2014-15'; fiscal_year set)
--   'partial_year'    — part of a year ('Apr 2016-Jul 2016'); NOT comparable to
--                       a full year
--   'multi_year_pool' — one figure pooled over several years ('2014-19'); the
--                       years are not separable
-- verification:
--   'total_row_sum'  — the printed Total/Grand Total equals the sum of the rows
--   'pct_consistent' — only a sentence in the answer; the printed percentage
--                      matches above/analysed (the weaker tier)
-- shape: 'table' | 'text_block' | 'sentence' (which extractor produced the row)
--
-- One row per (commodity, period, lok_sabha_no, source_question_no): the same
-- (commodity, period) is disclosed in several answers, sometimes at different
-- vintages (e.g. 2013-14 vegetables above MRL is 221 in a 2015 answer and 192
-- in a 2018 answer). All are kept, none merged; conflicts are computed at query
-- time (see /v1/meta/pesticide-residues).
--
-- Idempotent: bootstrap_db re-applies every migration daily. The question log
-- (loksabha_question_log, migration 019) is shared with loksabha_sampling; its
-- parser_version column keeps the two parsers apart.
-- ============================================================

CREATE TABLE IF NOT EXISTS pesticide_residue_annual (
    id                       BIGSERIAL PRIMARY KEY,
    commodity                TEXT NOT NULL,     -- stable key, e.g. 'vegetables', 'all_commodities'
    commodity_label          TEXT NOT NULL,     -- as printed
    period_label             TEXT NOT NULL,     -- '2014-15' | '2014-19' | 'Apr 2016-Jul 2016'
    fiscal_year              TEXT,              -- 'YYYY-YYYY' for period_kind = 'fiscal_year'
    period_kind              TEXT NOT NULL CHECK (period_kind IN ('fiscal_year', 'partial_year', 'multi_year_pool')),
    samples_analyzed         INTEGER NOT NULL CHECK (samples_analyzed >= 0),
    samples_above_mrl        INTEGER NOT NULL CHECK (samples_above_mrl >= 0),
    printed_pct              NUMERIC,           -- the percentage as printed, if any
    verification             TEXT NOT NULL CHECK (verification IN ('total_row_sum', 'pct_consistent')),
    shape                    TEXT NOT NULL CHECK (shape IN ('table', 'text_block', 'sentence')),
    lok_sabha_no             INTEGER NOT NULL,
    source_question_no       INTEGER NOT NULL,
    source_question_subject  TEXT,
    answered_date            DATE,
    source_url               TEXT NOT NULL,
    parser_version           TEXT NOT NULL,
    fetched_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (samples_above_mrl <= samples_analyzed),
    UNIQUE (commodity, period_label, lok_sabha_no, source_question_no)
);

CREATE INDEX IF NOT EXISTS idx_pesticide_residue_commodity ON pesticide_residue_annual (commodity);
CREATE INDEX IF NOT EXISTS idx_pesticide_residue_year      ON pesticide_residue_annual (fiscal_year);

GRANT SELECT ON pesticide_residue_annual TO foodsafe_app;
