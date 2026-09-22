-- ============================================================
-- FoodSafe India — Schema Additions (migration_021)
-- Run AFTER schema_migration_020.sql
-- Adds: rasff_notifications, rasff_hazards — real EU RASFF notifications about
-- food of Indian origin, with measured hazard values against legal limits, via
-- pipeline/sources/rasff.py (EU Commission public RASFF Window API).
--
-- Grain: one notification (rasff_notifications) x its hazards (rasff_hazards).
-- These are consignments checked at the EU border or on the EU market by
-- risk-based targeting: a record of what EU authorities found in Indian
-- exports, NOT a sample of food eaten in India and not a prevalence estimate.
--
-- has_detail: some notifications have no public detail page (HTTP 401/404); they
-- keep their list-level fields (subject, category, risk decision) and have no
-- hazard rows. Absence of hazards on such a row means "detail not public", not
-- "no hazard". detail_checked_at is NULL until a detail fetch was attempted, so
-- the first backfill (a few hundred detail fetches per daily run) resumes where
-- it stopped.
--
-- rasff_hazards keeps the notifier's text (result_raw) next to the parsed
-- number. result_value is filled only when the text is one unambiguous number
-- ('0.26', '5,0', '42+-13' -> 42; '1,000' is refused: thousand or decimal?).
-- result_qualifier is '=', '<' or '>'. exceedance_ratio / exceeds_limit are
-- computed only when result and limit share the same comparable unit.
-- Detail pages carry a named contact person at the notifying authority; that
-- personal data is never read or stored.
--
-- Idempotent: bootstrap_db re-applies every migration daily.
-- ============================================================

CREATE TABLE IF NOT EXISTS rasff_notifications (
    notif_id           BIGINT PRIMARY KEY,          -- RASFF's own numeric id
    reference          TEXT,                        -- e.g. '2026.8210'
    validation_date    DATE NOT NULL,
    subject            TEXT,
    notifying_country  TEXT,                        -- ISO-2
    origin_countries   TEXT[] NOT NULL DEFAULT '{}',
    classification     TEXT,                        -- alert / border rejection / information ...
    risk_decision      TEXT,                        -- serious / potentially serious / not serious ...
    product_category   TEXT,
    product_type       TEXT,                        -- food / feed / food contact material
    basis              TEXT,                        -- e.g. 'border control - consignment detained'
    product_name       TEXT,
    actions_taken      TEXT[] NOT NULL DEFAULT '{}',
    distribution       TEXT,
    has_detail         BOOLEAN NOT NULL DEFAULT FALSE,
    detail_checked_at  TIMESTAMPTZ,                 -- NULL = detail never attempted (backfill queue)
    source_url         TEXT NOT NULL,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ('IN' = ANY (origin_countries))
);

CREATE INDEX IF NOT EXISTS idx_rasff_notif_date     ON rasff_notifications (validation_date);
CREATE INDEX IF NOT EXISTS idx_rasff_notif_category ON rasff_notifications (product_category);

CREATE TABLE IF NOT EXISTS rasff_hazards (
    id                BIGSERIAL PRIMARY KEY,
    notif_id          BIGINT NOT NULL REFERENCES rasff_notifications (notif_id) ON DELETE CASCADE,
    hazard            TEXT NOT NULL,                -- e.g. 'Aflatoxin B1'
    hazard_category   TEXT,                         -- pesticide residues / mycotoxins / heavy metals / ...
    result_raw        TEXT,
    result_value      NUMERIC CHECK (result_value IS NULL OR result_value >= 0),
    result_qualifier  TEXT CHECK (result_qualifier IS NULL OR result_qualifier IN ('=', '<', '>')),
    result_unit       TEXT,
    limit_value       NUMERIC CHECK (limit_value IS NULL OR limit_value >= 0),   -- 0 = not permitted at all
    limit_unit        TEXT,
    exceedance_ratio  NUMERIC,                      -- result / limit, exact results in the same unit only
    exceeds_limit     BOOLEAN,
    sampling_date     DATE
);

CREATE INDEX IF NOT EXISTS idx_rasff_hazard_notif    ON rasff_hazards (notif_id);
CREATE INDEX IF NOT EXISTS idx_rasff_hazard_category ON rasff_hazards (hazard_category);

GRANT SELECT ON rasff_notifications, rasff_hazards TO foodsafe_app;
