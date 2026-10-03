-- ============================================================
-- FoodSafe India — Schema Additions (migration_022)
-- Run AFTER schema_migration_021.sql
-- Adds the STANDARDS + HAZARD KNOWLEDGE layer:
--
--   food_standards          one legal limit for one hazard in one food, as one
--                           official rule-book prints it (India FSSAI, EU, Codex,
--                           US). Loaded by pipeline/sources/standards_*.py.
--   standards_snapshots     which document version each load came from (sha256),
--                           so every limit is traceable to the exact text parsed.
--   hazards                 one row per hazard (pesticide, metal, mycotoxin,
--                           pathogen ...): class, CAS, IARC group, EU approval
--                           status. Loaded by pipeline/sources/hazard_kb.py.
--   hazard_reference_values health-based guidance values (ADI, ARfD, TDI, TWI,
--                           PTMI ...) with the body that set them and the source.
--   hazard_health_effects   what a hazard does to people: the health outcome,
--                           organ system, acute vs chronic, who is most at risk,
--                           and the authoritative source for the statement.
--
-- Rules carried by the columns:
--   * food_standards keeps the printed cells (hazard_raw, food_raw, limit_raw);
--     limit_value is set only when the cell is one unambiguous number
--     (parse_status = 'exact' | 'compound_split'); limit_mg_per_kg only when the
--     unit is a mass fraction. A missing value is NULL, never a guess.
--   * hazard_key / food_keys are comparison keys computed from the printed names
--     (code-owned crosswalks); a row with no key is still stored, just not
--     compared.
--   * at_loq: the limit is set at the analytical limit of quantification ('*'
--     in EU and FSSAI tables) — i.e. effectively "no residue permitted".
--
-- Idempotent: bootstrap_db re-applies every migration daily, so only
-- IF NOT EXISTS / no-op statements here.
-- ============================================================

CREATE TABLE IF NOT EXISTS standards_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    jurisdiction      TEXT NOT NULL,
    standard_types    TEXT[] NOT NULL,
    document_title    TEXT NOT NULL,
    document_url      TEXT NOT NULL,
    document_version  TEXT,
    document_sha256   TEXT,
    parser_version    TEXT NOT NULL,
    rows_loaded       INT NOT NULL,
    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS food_standards (
    id               BIGSERIAL PRIMARY KEY,
    jurisdiction     TEXT NOT NULL CHECK (jurisdiction IN ('IN', 'EU', 'CODEX', 'US')),
    standard_type    TEXT NOT NULL CHECK (standard_type IN
                         ('pesticide_mrl', 'contaminant_ml', 'vet_drug_mrl', 'prohibited_substance')),
    hazard_raw       TEXT NOT NULL,
    hazard_key       TEXT,
    hazard_class     TEXT NOT NULL,
    food_raw         TEXT NOT NULL,
    food_code        TEXT,                      -- EU product code / Codex commodity code
    food_keys        TEXT[] NOT NULL DEFAULT '{}',
    food_match       TEXT CHECK (food_match IS NULL OR food_match IN ('specific', 'group', 'residual')),
    limit_raw        TEXT NOT NULL,
    limit_value      NUMERIC CHECK (limit_value IS NULL OR limit_value >= 0),
    limit_unit       TEXT,
    limit_mg_per_kg  NUMERIC CHECK (limit_mg_per_kg IS NULL OR limit_mg_per_kg >= 0),
    at_loq           BOOLEAN NOT NULL DEFAULT FALSE,
    limit_basis      TEXT,                      -- 'fat basis', 'dry matter basis' ...
    parse_status     TEXT NOT NULL CHECK (parse_status IN
                         ('exact', 'compound_split', 'compound', 'not_numeric', 'reference', 'prohibited')),
    note             TEXT,
    applicability    TEXT,
    legal_reference  TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    source_page      INT,
    snapshot_id      BIGINT REFERENCES standards_snapshots (id),
    extra            JSONB,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_food_standards_hazard  ON food_standards (hazard_key);
CREATE INDEX IF NOT EXISTS idx_food_standards_juris   ON food_standards (jurisdiction, standard_type);
CREATE INDEX IF NOT EXISTS idx_food_standards_foods   ON food_standards USING GIN (food_keys);

CREATE TABLE IF NOT EXISTS hazards (
    hazard_key        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    hazard_class      TEXT NOT NULL,
    cas_number        TEXT,
    aliases           TEXT[] NOT NULL DEFAULT '{}',
    iarc_group        TEXT,                     -- '1', '2A', '2B', '3'
    iarc_agent        TEXT,                     -- the IARC agent name the group belongs to
    eu_status         TEXT,                     -- EU approval status of a pesticide active substance
    eu_category       TEXT,                     -- e.g. 'IN - Insecticide'
    eu_clp            TEXT,                     -- harmonised CLP hazard classes
    summary           TEXT,
    sources           JSONB NOT NULL DEFAULT '[]',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hazard_reference_values (
    id            BIGSERIAL PRIMARY KEY,
    hazard_key    TEXT NOT NULL,
    body          TEXT NOT NULL,                -- EFSA | JMPR | JECFA | US-EPA ...
    value_type    TEXT NOT NULL,                -- ADI | ARfD | AOEL | TDI | TWI | PTWI | PTMI | BMDL ...
    value         NUMERIC,
    unit          TEXT,
    raw_text      TEXT NOT NULL,
    year          INT,
    source_ref    TEXT,
    source_url    TEXT NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hazard_key, body, value_type)
);

CREATE TABLE IF NOT EXISTS hazard_health_effects (
    id                 BIGSERIAL PRIMARY KEY,
    hazard_key         TEXT NOT NULL,
    outcome_key        TEXT NOT NULL,           -- stable id, e.g. 'liver_cancer'
    outcome            TEXT NOT NULL,           -- 'Liver cancer (hepatocellular carcinoma)'
    icd10              TEXT,
    organ_system       TEXT NOT NULL,           -- hepatic | renal | nervous | gastrointestinal ...
    exposure           TEXT NOT NULL CHECK (exposure IN ('acute', 'chronic', 'both')),
    onset              TEXT,                    -- 'hours', 'days', 'years' ...
    vulnerable_groups  TEXT[] NOT NULL DEFAULT '{}',
    evidence           TEXT NOT NULL,           -- e.g. 'IARC Group 1 (sufficient evidence in humans)'
    source_title       TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    UNIQUE (hazard_key, outcome_key)
);

CREATE INDEX IF NOT EXISTS idx_health_effects_outcome ON hazard_health_effects (outcome_key);

-- India vs EU / Codex / US, one row per (standard_type, hazard, food) India
-- regulates. Recomputed from food_standards by models/standards_compare.py.
-- *_basis says how each value was found: specific | group | eu_default (EU
-- general default 0.01 mg/kg, Reg. 396/2005 Art. 18(1)(b)) | none | not_loaded |
-- not_numeric. ratio_in_* = India / other, only when both are comparable numbers.
CREATE TABLE IF NOT EXISTS standards_comparison (
    id              BIGSERIAL PRIMARY KEY,
    standard_type   TEXT NOT NULL,
    hazard_key      TEXT NOT NULL,
    food_key        TEXT NOT NULL,
    hazard_name     TEXT NOT NULL,
    in_value        NUMERIC,
    eu_value        NUMERIC,
    eu_basis        TEXT NOT NULL,
    codex_value     NUMERIC,
    codex_basis     TEXT NOT NULL,
    us_value        NUMERIC,
    us_basis        TEXT NOT NULL,
    ratio_in_eu     NUMERIC,
    ratio_in_codex  NUMERIC,
    ratio_in_us     NUMERIC,
    flags           TEXT[] NOT NULL DEFAULT '{}',
    in_substance_key TEXT,                     -- India's printed substance, spelling-normalised only
    eu_status       TEXT,                      -- EU approval status of THAT substance (not its residue family)
    iarc_group      TEXT,
    detail          JSONB NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (standard_type, hazard_key, food_key)
);

CREATE INDEX IF NOT EXISTS idx_std_cmp_food   ON standards_comparison (food_key);
CREATE INDEX IF NOT EXISTS idx_std_cmp_hazard ON standards_comparison (hazard_key);

GRANT SELECT ON standards_snapshots, food_standards, hazards, hazard_reference_values, hazard_health_effects,
    standards_comparison TO foodsafe_app;
