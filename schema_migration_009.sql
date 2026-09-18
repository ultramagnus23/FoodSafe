-- ============================================================
-- FoodSafe India — Schema Additions (migration_009)
-- Run AFTER schema_migration_008.sql
-- Adds: `localities` — sub-district geography (H3.1 — locality-level
-- granularity).
--
-- Context: districts (schema.sql:37) has always been the finest
-- geographic unit in this schema — one row, one centroid lat/long, per
-- district. "Mumbai" is a single districts row; there has never been a
-- way to represent Juhu, Vile Parle, and Churchgate as distinct places
-- anywhere in this database. That's a real architectural ceiling, not
-- just missing seed data — every downstream table (enforcement_records,
-- consumer_reports, agg_district_commodity_risk, the RF model, the map)
-- is keyed on district_id.
--
-- This migration adds the missing layer without breaking anything that
-- already works at district grain:
--   - `localities`: real, named, geocoded neighborhoods below district
--     level, linked to a parent district and to real India Post pincodes
--     (the practical proxy for "locality" almost everywhere in India).
--   - `locality_id` (nullable) added to `consumer_reports` and
--     `enforcement_records` — nullable and additive, so every existing
--     district-level row/query keeps working unchanged. A row without a
--     locality_id just means "we only know the district," which is
--     honestly the truth for all data ingested before this migration.
--
-- IMPORTANT — this is schema capacity, not new data. Seeding real
-- locality-level *enforcement* data for India doesn't exist anywhere in
-- the open (see docs/FSSAI_INGESTION.md) — this table exists so that when
-- real locality-level signal does show up (crowdsourced consumer_reports
-- with a geocoded address being the most realistic near-term source, see
-- api/routes/reports.py's pincode-resolution logic), it has somewhere
-- correct to land instead of collapsing into the parent district. The
-- seed below is real (India Post pincode boundaries, public data), not
-- synthetic — it's just a start (~20 well-known Mumbai neighborhoods),
-- not a full India-wide pincode load. See docs/LOCALITY_DATA.md for how
-- to extend it city by city.
-- ============================================================

CREATE TABLE IF NOT EXISTS localities (
    id                  SERIAL PRIMARY KEY,
    name_canonical      TEXT NOT NULL,
    parent_district_id  INT  NOT NULL REFERENCES districts(id),
    pincodes            TEXT[] NOT NULL DEFAULT '{}',   -- real India Post PIN codes, e.g. {'400049'}
    latitude             NUMERIC(9,6),
    longitude            NUMERIC(9,6),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name_canonical, parent_district_id)
);

CREATE INDEX IF NOT EXISTS idx_localities_district ON localities (parent_district_id);
CREATE INDEX IF NOT EXISTS idx_localities_pincodes ON localities USING GIN (pincodes);

ALTER TABLE consumer_reports
    ADD COLUMN IF NOT EXISTS locality_id INT REFERENCES localities(id);

ALTER TABLE enforcement_records
    ADD COLUMN IF NOT EXISTS locality_id INT REFERENCES localities(id);

-- Widen enforcement_records.source_type for the new local-news source
-- (pipeline/sources/local_news.py, source_type='local_news_mumbai') —
-- narrative/event-level like the existing 'fssai' recall rows, not a lab
-- ppb reading, but real text naming a real neighborhood, which is exactly
-- what locality_id above exists to carry. The original CHECK constraint
-- (schema.sql:87) didn't anticipate a news-derived source type.
--
-- Guarded, because scripts/bootstrap_db.py re-applies every migration on each
-- daily CI run. An unconditional DROP + ADD here re-validates the CHECK
-- against rows written by LATER sources, so once a row with a value this
-- (narrower) list doesn't know — e.g. 'local_news' from migration_017 — exists,
-- this file would fail on every run and take the whole ingest job down with
-- it. Only widen when the live constraint doesn't already have the value.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'enforcement_records_source_type_check'
          AND conrelid = 'enforcement_records'::regclass
          AND pg_get_constraintdef(oid) LIKE '%local_news_mumbai%'
    ) THEN
        ALTER TABLE enforcement_records DROP CONSTRAINT IF EXISTS enforcement_records_source_type_check;
        ALTER TABLE enforcement_records ADD CONSTRAINT enforcement_records_source_type_check
            CHECK (source_type IN ('fssai','usfda','efsa','apeda','state_health','agmarknet','local_news_mumbai'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_consumer_reports_locality
    ON consumer_reports (locality_id) WHERE review_status = 'published';

GRANT SELECT ON localities TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;

-- ============================================================
-- SEED: real Mumbai localities (India Post PIN codes, public data)
-- Seeded against whatever districts row is named 'Mumbai' in this DB —
-- works against both seed_demo.sql (id=1) and any future re-seed without
-- hardcoding an id.
-- ============================================================

INSERT INTO localities (name_canonical, parent_district_id, pincodes, latitude, longitude)
SELECT v.name, d.id, v.pincodes, v.lat, v.lng
FROM (VALUES
    ('Juhu',            ARRAY['400049'],           19.1075, 72.8263),
    ('Vile Parle West', ARRAY['400056'],           19.1003, 72.8425),
    ('Vile Parle East', ARRAY['400057'],           19.0970, 72.8494),
    ('Churchgate',      ARRAY['400020'],           18.9322, 72.8264),
    ('Fort',            ARRAY['400001','400023'],  18.9345, 72.8357),
    ('Colaba',          ARRAY['400005'],           18.9067, 72.8147),
    ('Andheri West',    ARRAY['400058'],           19.1364, 72.8296),
    ('Andheri East',    ARRAY['400069'],           19.1197, 72.8697),
    ('Bandra West',     ARRAY['400050'],           19.0596, 72.8295),
    ('Bandra East',     ARRAY['400051'],           19.0668, 72.8397),
    ('Dadar West',      ARRAY['400028'],           19.0186, 72.8420),
    ('Worli',           ARRAY['400018'],           19.0176, 72.8162),
    ('Powai',           ARRAY['400076'],           19.1176, 72.9060),
    ('Malad West',      ARRAY['400064'],           19.1863, 72.8493),
    ('Borivali West',   ARRAY['400092'],           19.2307, 72.8567),
    ('Santacruz West',  ARRAY['400054'],           19.0822, 72.8412),
    ('Kurla West',      ARRAY['400070'],           19.0728, 72.8794),
    ('Ghatkopar East',  ARRAY['400077'],           19.0864, 72.9081),
    ('Chembur',         ARRAY['400071'],           19.0522, 72.9006),
    ('Mulund West',     ARRAY['400080'],           19.1726, 72.9425)
) AS v(name, pincodes, lat, lng)
JOIN districts d ON d.name_canonical = 'Mumbai' AND d.state = 'Maharashtra'
ON CONFLICT (name_canonical, parent_district_id) DO NOTHING;
