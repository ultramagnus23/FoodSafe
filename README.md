# FoodSafe India — Foundation + Data Pipeline

## Project Structure

```
foodsafe/
├── schema.sql                   ← Run first. Full PostgreSQL schema.
├── requirements.txt
├── pipeline/
│   ├── config.py                ← All constants, env vars, alias maps
│   ├── ingest.py                ← Main entry point (CLI + Airflow callable)
│   ├── stage1_extract.py        ← PDF OCR + NER → RawRecord
│   ├── stage2_standardise.py    ← Canonicalise → StandardisedRecord
│   ├── stage3_and_4.py          ← Dedup + confidence score → ScoredRecord
│   ├── airflow_dags.py          ← 3 DAGs (FSSAI weekly, USFDA daily, AGMARKNET daily)
│   └── sources/
│       └── fssai.py             ← FSSAI scraper (link discovery + download)
└── api/                         ← (next: FastAPI backend)
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
```

### 4. Environment variables
```bash
export DATABASE_URL="postgresql://foodsafe_app:password@localhost:5432/foodsafe"
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

## What's Next

- `api/` — FastAPI with all endpoints from Section 5
- `models/district_risk.py` — Random Forest risk score model
- `models/supply_chain.py` — Bayesian propagation graph
- `frontend/` — React + India map
- NER model fine-tuning on annotated FSSAI PDFs
- APEDA and state health department scrapers
