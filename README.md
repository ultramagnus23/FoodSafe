# FoodSafe India — Data Pipeline + Risk API + Web App

Four layers: an ingestion **pipeline** (real openFDA/AGMARKNET feeds + an
FSSAI OCR path, PostgreSQL/Supabase), a risk-scoring **API** (FastAPI, 12+
routers), a **Next.js** web app (`frontend/`), and a legacy single-file React
app (`index.html`) kept as a CDN-only fallback.

## Project Structure

```
foodsafe/
├── schema.sql                    ← Run first. Full PostgreSQL schema + core seed.
├── schema_migration_002.sql      ← Lab reliability, fraud flags, disputes, ICMR.
├── schema_migration_003.sql      ← Dietary exposure / disease burden / Codex benchmark tables.
├── schema_migration_004.sql      ← Trend analysis, alert subscriptions, API keys, admin.
├── seed_demo.sql                 ← Reference data only (districts/brands/labs) — no fake risk scores.
├── requirements.txt              ← Full pipeline stack (OCR, Airflow, boto3) — optional for v1.
├── requirements-api.txt          ← Minimal deps for running just the API + live ingesters.
├── index.html                    ← Legacy single-file React SPA (CDN React, no build step).
├── tests/                        ← pytest — stage2 standardisation + stage3 dedup/scoring.
├── render.yaml                   ← Render.com deploy config for the API (Supabase via DATABASE_URL).
├── vercel.json                   ← Vercel deploy config for frontend/.
│
├── api/                          ← FastAPI backend (run: uvicorn api.main:app)
│   ├── main.py                   ← App, CORS, tiered rate limiting, router wiring.
│   ├── db.py                     ← asyncpg connection pool.
│   ├── auth.py                   ← register / login / refresh / logout (bcrypt + JWT).
│   ├── auth_utils.py             ← JWT create/verify, tier enforcement, API-key auth.
│   ├── other_routes.py           ← search, autocomplete, fmcg market-gaps, insurance, /v1/meta/*.
│   └── routes/
│       ├── risk.py               ← district / brand / map (heatmap) / alerts.
│       ├── user.py               ← location, profile.
│       ├── disputes.py           ← public dispute submission + admin fraud review.
│       ├── disease.py            ← disease-burden (PAF) estimates, exposure alerts.
│       ├── trends.py             ← Mann-Kendall trend + Sen's slope, per district/national.
│       ├── compare.py            ← district-vs-district and FSSAI-vs-Codex/EU comparisons.
│       ├── admin_panel.py        ← platform stats, record review, manual aggregate/burden recompute.
│       ├── api_keys.py           ← B2B API key issuance/revocation/usage (fmcg/insurance tiers).
│       └── subscriptions.py      ← per-user alert subscriptions (email via models/notifications.py).
│
├── models/                       ← Analytics (standalone CLIs, also invoked by API routes/cron)
│   ├── aggregate.py              ← Computes agg_district_commodity_risk / agg_brand_safety_profile.
│   ├── district_risk.py          ← Random Forest risk model, geographic-holdout CV.
│   ├── supply_chain.py           ← Bayesian contaminant-propagation graph.
│   ├── fraud_detection.py        ← Benford's Law + lab reliability scoring.
│   ├── dietary_exposure.py       ← PPB → daily intake (EFSA methodology).
│   ├── disease_burden.py         ← Intake → Population Attributable Fraction / hazard quotient.
│   ├── codex_benchmark.py        ← FSSAI limit vs Codex/EU/WHO-JECFA comparison.
│   ├── trend_analysis.py         ← Mann-Kendall + Sen's slope trend detection.
│   └── notifications.py          ← Email alerts for active subscriptions (Resend).
│
├── pipeline/
│   ├── config.py                 ← All constants, env vars, alias maps (contaminants/units/states).
│   ├── ingest.py                 ← FSSAI OCR batch entry point (CLI + Airflow callable).
│   ├── seed_enforcement.py       ← Generates demo enforcement_records for the India heatmap.
│   ├── stage1_extract.py         ← PDF OCR + NER → RawRecord.
│   ├── stage2_standardise.py     ← Canonicalise → StandardisedRecord.
│   ├── stage3_and_4.py           ← Dedup + confidence score → ScoredRecord.
│   ├── airflow_dags.py           ← Optional — only needed if running the full Airflow stack.
│   └── sources/
│       ├── openfda.py            ← Real US FDA food-recall API (no key, no OCR). Live in prod.
│       ├── agmarknet.py          ← Real Indian district/commodity data from data.gov.in. Live in prod.
│       ├── fssai_recall.py       ← FoSCoS food-recall scraper (headless browser, Playwright).
│       └── fssai.py              ← FSSAI enforcement-report scraper (link discovery + download).
│
└── frontend/                     ← Next.js 14 app (App Router, TypeScript, Tailwind)
    ├── app/                      ← Pages: home, /search, /map, /district/[id], /compare,
    │                                /alerts, /account, /admin, /methodology.
    ├── components/                 UI (RiskBadge, EvidenceGradeBadge, PAFDisplay, LeafletMap, ...).
    └── lib/api/                    Typed fetch clients, one per router (search, risk, trends, ...).
```

## Setup

### 1. Python (API + live ingesters — no OCR tooling needed)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-api.txt
```

### 2. OS + Python deps for the full OCR pipeline (optional, v1 doesn't need this)
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-hin poppler-utils
pip install -r requirements.txt          # adds boto3, apache-airflow, playwright, spaCy, etc.
python -m spacy download en_core_web_sm
```
S3 and Airflow are **not required** — `pipeline.ingest` runs locally without
`--use-s3`, and the live ingesters (`openfda`, `agmarknet`) need neither.

### 3. Database
```bash
createdb foodsafe
psql foodsafe < schema.sql
psql foodsafe < schema_migration_002.sql
psql foodsafe < schema_migration_003.sql
psql foodsafe < schema_migration_004.sql
psql foodsafe < seed_demo.sql            # districts, brands, labs — reference data only

# Populate enforcement_records + computed risk scores (set DATABASE_URL first, see step 4):
python -m pipeline.seed_enforcement      # one-shot demo dataset (~1900 realistic records)
python -m pipeline.sources.openfda       # real US FDA recalls (optional)
python -m pipeline.sources.agmarknet     # real Indian districts/commodities (optional)
python -m models.aggregate               # compute district + brand risk scores
```

> Note: `schema.sql` creates a restricted `foodsafe_app` role and enables
> row-level security on `users`. The API does not yet set the `app.user_id`
> RLS context, so for local development run the API as the database owner
> (e.g. `postgres`). See "Honest limitations" below.

#### Hosted database (Supabase)

The same migration sequence runs unchanged against a Supabase project:

- **Use the Session pooler connection string**, not the direct
  `db.<ref>.supabase.co` host — the direct host is IPv6-only and unreachable
  on IPv4-only networks. The pooler
  (`aws-1-<region>.pooler.supabase.com:5432`, user `postgres.<project-ref>`)
  is IPv4. `?sslmode=require` is mandatory.
- Load it via `.env` (see below); the API and pipeline both pick it up
  automatically via `DATABASE_URL`.

```bash
PGURL="postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
for f in schema.sql schema_migration_002.sql schema_migration_003.sql schema_migration_004.sql seed_demo.sql; do
  psql "$PGURL" -f "$f"
done
```

### 4. Environment variables

Copy `.env.example` to `.env` (gitignored):
```bash
cp .env.example .env
# DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres?sslmode=require
# JWT_SECRET=change-me
```

### 5. One-shot demo ingest

To go from an empty Supabase DB to a searchable API without touching OCR or
Airflow:
```bash
psql "$DATABASE_URL" -f schema.sql -f schema_migration_002.sql \
  -f schema_migration_003.sql -f schema_migration_004.sql -f seed_demo.sql
python -m pipeline.seed_enforcement
python -m models.aggregate
```

### 6. API + web app
```bash
uvicorn api.main:app --reload --port 8000

# Next.js frontend
cd frontend && npm install && npm run dev     # http://localhost:3000

# or the legacy static app:
python -m http.server 3000 --directory .      # then open http://localhost:3000/index.html
```
Search, `/v1/meta/*`, district risk, and disputes are **public read-only
endpoints** — no login required. JWT auth is only needed for
account-specific features (subscriptions, API keys, admin).

### 7. Automated data ingestion (real data, runs in the cloud)

`.github/workflows/ingest.yml` runs daily (+ manual trigger) against a
`DATABASE_URL` repo secret — no laptop required:
```bash
gh secret set DATABASE_URL --body "postgresql://postgres.<ref>:<pwd>@aws-1-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```
It chains: openFDA (real US recalls) → AGMARKNET (real Indian
districts/commodities) → FoSCoS scrape (real Indian recalls, best-effort) →
`models.aggregate` → `models.disease_burden` → `models.notifications`.

### 8. Tests
```bash
pip install pytest rapidfuzz
python -m pytest tests/ -v
```
`.github/workflows/tests.yml` runs the same suite on every push/PR. Coverage
is `pipeline/stage2_standardise.py` (contaminant/unit/date/geo
standardisation) and `pipeline/stage3_and_4.py` (dedup hashing + confidence
scoring) — both testable without a live database.

### 9. Deploying
- **API** → Render, via [`render.yaml`](render.yaml) (`requirements-api.txt`
  only, `DATABASE_URL`/`JWT_SECRET`/`FRONTEND_URL` as env vars).
- **Frontend** → Vercel, via [`vercel.json`](vercel.json).
- Optional heavier pipeline components (Airflow, S3, Tesseract) are **not**
  part of the deploy path — they only matter if you're running the FSSAI OCR
  batch pipeline yourself.

## Data Flow

```
FSSAI PDFs (OCR)      openFDA RSS          AGMARKNET JSON       FoSCoS (headless browser)
     │                    │                     │                     │
     ▼                    ▼                     ▼                     ▼
Stage 1: Extract → RawRecord         (openFDA/AGMARKNET/FoSCoS write enforcement_records directly)
     │
     ▼
Stage 2: Standardise → StandardisedRecord
  - Contaminant → canonical name (fuzzy match)
  - Value → PPB
  - State/District → Census 2021 canonical
  - Date → ISO 8601 (ambiguous MM/DD vs DD/MM flagged)
     │
     ▼
Stage 3: Deduplicate → DeduplicatedRecord
  - Hash: date + lab + commodity + contaminant + value + district
  - Cross-source duplicates flagged, not deleted
     │
     ▼
Stage 4: Confidence Score → ScoredRecord
  - Base 0.70, +0.15 manually verified, +0.10 tier-1 lab, +0.05 typical range, -0.10 low OCR
  - Only ≥ 0.75 used in downstream models
     │
     ▼
PostgreSQL enforcement_records
     │
     ▼  (nightly via GitHub Actions, or run manually)
models.aggregate        → agg_district_commodity_risk, agg_brand_safety_profile
models.dietary_exposure → daily intake estimates
models.disease_burden   → Population Attributable Fraction, exposure_alerts
models.trend_analysis   → Mann-Kendall trend + Sen's slope
models.codex_benchmark  → FSSAI vs Codex/EU/WHO-JECFA comparison
models.notifications    → email alerts for matching subscriptions
```

## Status

**Built and working:**
- **Pipeline** — Stages 1–4 (extract → standardise → dedup → confidence
  score), unit-tested (`tests/`). Real live ingesters:
  `pipeline/sources/openfda.py` (US FDA recalls, no key/OCR) and
  `pipeline/sources/agmarknet.py` (Indian district/commodity data from
  data.gov.in), both idempotent. `pipeline/sources/fssai_recall.py` scrapes
  real FoSCoS recalls via headless Chromium. `pipeline/seed_enforcement.py`
  provides a one-shot demo dataset for the India district heatmap.
- **API** — FastAPI with 12+ routers: auth, risk, user, search (+
  autocomplete), fmcg, insurance, meta, disputes, disease, trends, compare,
  admin panel, API keys, subscriptions. Search/risk/meta/disputes are public
  read-only; JWT + API-key auth with tier-based rate limiting gate
  account-specific features. Every record response includes a `source_url`
  and `confidence_score`.
- **Analytics** — computed district/brand risk (Wilson 95% CI), dietary
  exposure → disease burden (PAF), Codex/EU/WHO benchmark gaps, Mann-Kendall
  contamination trends, Bayesian supply-chain propagation, Benford's-Law
  fraud detection, Random Forest district risk (geographic holdout CV).
- **Frontend** — Next.js app (`frontend/`) with search, map, district
  detail, compare, alerts, account, admin, methodology pages, plus a legacy
  single-file `index.html` fallback.
- **Automation** — `.github/workflows/ingest.yml` (daily ingest → aggregate
  → notify) and `.github/workflows/tests.yml` (pytest on every push/PR), both
  against a Supabase Postgres via `DATABASE_URL`.
- **Trust & safety** — disclaimer banners on every risk/record response,
  public dispute submission (`POST /v1/disputes/submit`) with admin review
  queue for fraud/correction flags.

**Honest limitations:**
- **No open API for Indian district-level contamination data** — it exists
  only in FSSAI PDFs, so the India heatmap runs on demo records
  (`pipeline/seed_enforcement.py`) that the aggregation computes over exactly
  as it would real data. FSSAI no longer publishes structured enforcement
  data (recalls are JS-rendered/qualitative; "reports" are news clippings).
  Full investigation + roadmap: [`docs/FSSAI_INGESTION.md`](docs/FSSAI_INGESTION.md).
- **Random Forest** trains on the aggregation table but needs more data than
  the demo set to be meaningful; served scores come from the statistical
  aggregation, not the RF, until enough records accumulate.
- **Supply-chain graph** — `supply_chain: []` until `supply_chain_nodes/edges`
  are populated (no seed graph yet).
- **Production DB role** — API connects as the DB owner; it does not yet set
  the `app.user_id` RLS context the restricted `foodsafe_app` role needs.
- **Disputes → risk feedback loop** — admin review flags/corrects records but
  does not automatically recompute aggregate scores.
- **In-memory rate limiting** resets on deploy and doesn't share state across
  multiple Render instances (API-key usage is persisted; JWT/anonymous is
  not) — accepted tradeoff pending Redis.

**Not started:**
- NER fine-tuning; APEDA / state-health scrapers; age-gating / DOB
  collection.
- Census-2021 district **polygon** choropleth (the map uses risk-coloured
  markers, not GeoJSON polygons).

See [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for what's left before this is
production-ready for real users.
