-- ============================================================
-- FoodSafe India — Schema Additions (migration_025)
-- Run AFTER schema_migration_024.sql
--
-- Country context for the cross-country comparison ("how do places compare?"):
--   countries                 World Bank country list (ISO3/ISO2, region, income)
--   country_indicators        country x indicator x year values from WHO GHO
--                             (IHR food-safety capacity) and the World Bank
--                             (undernourishment, food insecurity, stunting,
--                             wasting, anaemia, safe water, sanitation ...)
--   foodborne_burden_global   WHO foodborne disease burden estimates by hazard,
--                             age group and year (illnesses, deaths, DALYs), 2000-2021.
--                             WHO publishes these at GLOBAL level only.
-- Loaded by pipeline/sources/country_indicators.py. Values are stored as published;
-- nothing is imputed or interpolated.
--
-- Idempotent: bootstrap_db re-applies every migration daily.
-- ============================================================

CREATE TABLE IF NOT EXISTS countries (
    iso3          TEXT PRIMARY KEY,
    iso2          TEXT,
    name          TEXT NOT NULL,
    region        TEXT,
    income_level  TEXT,
    is_aggregate  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_countries_iso2 ON countries (iso2);

CREATE TABLE IF NOT EXISTS country_indicators (
    id              BIGSERIAL PRIMARY KEY,
    iso3            TEXT NOT NULL,
    indicator_code  TEXT NOT NULL,
    indicator_name  TEXT NOT NULL,
    source          TEXT NOT NULL,              -- 'WHO GHO' | 'World Bank'
    year            INT NOT NULL,
    value           NUMERIC NOT NULL,
    unit            TEXT,
    source_url      TEXT NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (iso3, indicator_code, year)
);
CREATE INDEX IF NOT EXISTS idx_country_ind_code ON country_indicators (indicator_code, year);

CREATE TABLE IF NOT EXISTS foodborne_burden_global (
    indicator_code  TEXT NOT NULL,              -- FOODBORNE_ILL | FOODBORNE_DTH | FOODBORNE_DALY
    measure         TEXT NOT NULL,              -- illnesses | deaths | DALYs
    year            INT NOT NULL,
    age_group       TEXT NOT NULL,              -- all ages | under 5 | 5 and over
    hazard_group    TEXT NOT NULL,
    hazard          TEXT NOT NULL,
    value           NUMERIC NOT NULL,
    low             NUMERIC,
    high            NUMERIC,
    source_url      TEXT NOT NULL,
    PRIMARY KEY (indicator_code, year, age_group, hazard_group, hazard)
);

GRANT SELECT ON countries, country_indicators, foodborne_burden_global TO foodsafe_app;
