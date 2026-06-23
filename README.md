# FoodSafe India — Data Pipeline + Risk API + Web App

Three layers: an ingestion **pipeline** (FSSAI/USFDA/AGMARKNET → PostgreSQL), a
risk-scoring **API** (FastAPI, 8 routers), and a single-file React **web app**
(`index.html`, served from any static host — CDN React, no build step).

## Project Structure

```
foodsafe/
├── schema.sql                   ← Run first. Full PostgreSQL schema + core seed.
├── schema_migration_002.sql     ← Run second. Lab reliability, fraud flags, disputes, ICMR.
├── seed_demo.sql                ← Optional. Demo districts/brands/labs + aggregation rows.
├── requirements.txt             ← API + pipeline dependencies.
├── index.html                   ← React SPA (CDN React 18, no bundler). Calls the API.
├── api/                         ← FastAPI backend (run: uvicorn api.main:app)
│   ├── main.py                  ← App + 8 routers (auth, risk, user, search, fmcg,
│   │                              insurance, disputes, admin)
│   ├── db.py                    ← asyncpg connection pool
│   ├── auth.py                  ← register / login / refresh / logout (bcrypt + JWT)
│   ├── auth_utils.py            ← JWT create/verify, tier enforcement, API-key auth
│   ├── other_routes.py          ← search_router, fmcg_router, insurance_router
│   └── routes/
│       ├── risk.py              ← district / brand / map (heatmap) / alerts
│       ├── user.py              ← location, profile
│       └── disputes.py          ← brand disputes + admin fraud (labs, records)
├── models/                      ← Analytics (standalone CLIs / Airflow-invoked)
│   ├── district_risk.py         ← Random Forest risk model, geographic-holdout CV
│   ├── supply_chain.py          ← Bayesian contaminant-propagation graph
│   └── fraud_detection.py       ← Benford's Law + lab reliability scoring
└── pipeline/
    ├── config.py                ← All constants, env vars, alias maps
    ├── ingest.py                ← Main entry point (CLI + Airflow callable)
    ├── stage1_extract.py        ← PDF OCR + NER → RawRecord
    ├── stage2_standardise.py    ← Canonicalise → StandardisedRecord
    ├── stage3_and_4.py          ← Dedup + confidence score → ScoredRecord
    ├── airflow_dags.py          ← 3 DAGs (FSSAI weekly, USFDA daily, AGMARKNET daily)
    └── sources/
        └── fssai.py             ← FSSAI scraper (link discovery + download)
```

## Setup

### 1. OS dependencies
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-hin poppler-utils
```

### 2. Python
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3. Database
```bash
createdb foodsafe
psql foodsafe < schema.sql
psql foodsafe < schema_migration_002.sql
# Optional: demo districts/brands/labs + pre-computed aggregation rows so the
# API returns non-empty results without running the full ingestion pipeline.
psql foodsafe < seed_demo.sql
```

> Note: `schema.sql` creates a restricted `foodsafe_app` role and enables
> row-level security on `users`. The API does not yet set the `app.user_id`
> RLS context, so for local development run the API as the database owner
> (e.g. `postgres`). See "What's Next" for the production hardening item.

#### Hosted database (Supabase)

The same `schema.sql` → `schema_migration_002.sql` → `seed_demo.sql` sequence
runs unchanged against a Supabase project. Two things to know:

- **Use the Session pooler connection string**, not the direct
  `db.<ref>.supabase.co` host. On IPv4-only networks the direct host is
  unreachable (it is IPv6-only); the pooler
  (`aws-1-<region>.pooler.supabase.com:5432`, user `postgres.<project-ref>`)
  is IPv4. `?sslmode=require` is mandatory — `asyncpg` honours it from the URL.
- Load it via `.env` (see below); the API picks it up automatically.

```bash
PGURL="postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
psql "$PGURL" -f schema.sql
psql "$PGURL" -f schema_migration_002.sql
psql "$PGURL" -f seed_demo.sql
```

### 4. Environment variables

Copy `.env.example` to `.env` (gitignored) and fill it in — the API loads it
automatically via `python-dotenv`:

```bash
cp .env.example .env
# .env:
#   DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres?sslmode=require
#   JWT_SECRET=change-me
```

For the pipeline, also export:
```bash
export AWS_REGION="ap-south-1"
export S3_BUCKET="foodsafe-raw"
```

### 5. Run pipeline (dev/test)
```bash
# Single run — FSSAI enforcement reports, 2 pages, no S3
python -m pipeline.ingest --source fssai --page-types enforcement_reports --max-pages 2

# Full run with S3
python -m pipeline.ingest --source fssai --use-s3 --max-pages 50
```

### 6. Airflow
```bash
export AIRFLOW_HOME=~/airflow
airflow db migrate
cp pipeline/airflow_dags.py $AIRFLOW_HOME/dags/
airflow standalone
```

### 7. API + Web app
```bash
# Backend reads DATABASE_URL + JWT_SECRET from .env (see step 4).
# Works the same whether DATABASE_URL points at local Postgres or Supabase.
uvicorn api.main:app --reload --port 8000

# Frontend — index.html is a static file; serve it from any static host:
python -m http.server 3000        # then open http://localhost:3000/index.html
```
The web app calls the API at `http://localhost:8000` (configurable via the
`API_BASE` constant at the top of `index.html`). All read endpoints require a
JWT, so the app has a built-in register/login flow.

### 8. Automated data ingestion (real data)

Most tables are demo-seeded (`seed_demo.sql`). For **real** records there is a
working ingester for the openFDA food-enforcement API (public, no key, no OCR):

```bash
python -m pipeline.sources.openfda --limit 50   # pulls real food-recall records
```

It maps US FDA food recalls (lead/aflatoxin/melamine/… recalls) into
`enforcement_records` as `source_type='usfda'`, idempotently (dedup on the FDA
recall number). These surface in the national `/risk/alerts` feed. Note: they
are US-geographic, so they do **not** populate the India district heatmap — that
still needs the FSSAI pipeline (PDF OCR, currently blocked on tooling + changed
gov URLs).

This runs automatically in the cloud via
[`.github/workflows/ingest.yml`](.github/workflows/ingest.yml) (daily cron +
manual trigger), using a `DATABASE_URL` repo secret — no laptop required.

## Data Flow

```
FSSAI PDFs            USFDA RSS           AGMARKNET JSON
     │                    │                     │
     ▼                    ▼                     ▼
Stage 1: Extract     (RawRecord)
     │
     ▼
Stage 2: Standardise (StandardisedRecord)
  - Contaminant → canonical name (fuzzy match)
  - Value → PPB
  - State/District → Census 2021 canonical
  - Date → ISO 8601
     │
     ▼
Stage 3: Deduplicate (DeduplicatedRecord)
  - Hash: date + lab + commodity + contaminant + value + district
  - Cross-source duplicates flagged, not deleted
     │
     ▼
Stage 4: Confidence Score (ScoredRecord)
  - Base: 0.70
  - +0.15 manually verified
  - +0.10 tier-1 lab (ICAR/NABL)
  - +0.05 value in typical range
  - -0.10 OCR confidence < 0.80
  - Only ≥ 0.75 used in downstream models
     │
     ▼
PostgreSQL enforcement_records
     │
     ▼ (nightly Airflow)
agg_district_commodity_risk
agg_brand_safety_profile
```

## Status

**Built and working:**
- **Pipeline** — Stages 1–4 (extract → standardise → dedup → confidence score),
  FSSAI scraper, 3 Airflow DAGs.
- **API** — FastAPI with 8 routers (auth, risk, user, search, fmcg, insurance,
  disputes, admin). JWT + API-key auth, tier enforcement, legal disclaimer
  baked into risk responses.
- **Models** — Random Forest district-risk model (`models/district_risk.py`),
  Bayesian supply-chain propagation graph (`models/supply_chain.py`), fraud
  detection via Benford's Law + lab reliability (`models/fraud_detection.py`).
- **Web app** — `index.html`, single-file React SPA wired to the live API
  (home/map, risk report, brands, FMCG market gaps, alerts ticker).

**Still stubbed / not yet wired:**
- The Random Forest and supply-chain models run as standalone CLIs and via
  Airflow, but their output is **not yet plumbed into the live API responses**:
  `risk.py` returns `top_factors: []` and `supply_chain: []` (see the
  `# populated by ... in production` comments). The aggregation tables they would
  populate are filled by the nightly DAG (or by `seed_demo.sql` for demos).
- **Production DB role** — the API currently connects as the DB owner; it does
  not set the `app.user_id` RLS context that the restricted `foodsafe_app` role
  needs. Wire `SET LOCAL app.user_id` per request before switching to that role.
- **Disputes → risk feedback loop** — dispute review flags records but does not
  recompute downstream risk scores.

**Not started:**
- NER model fine-tuning on annotated FSSAI PDFs.
- APEDA and state health department scrapers.
- Age-gating / DOB collection (pending legal review).
- Choropleth map rendering (the web app currently plots district risk as
  positioned dots, not GeoJSON district polygons).
