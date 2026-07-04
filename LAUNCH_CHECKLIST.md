# Launch Checklist

Status snapshot for turning FoodSafe India from a working local pipeline into
a live, publicly usable product. See [README.md](README.md) for setup and
architecture; this is the "what's left" list.

## Done

- [x] Repo restructured into `pipeline/`, `api/`, `models/`, `frontend/`.
- [x] FastAPI with public read-only search/risk/meta/disputes endpoints — no
      login required for the core "look something up" flow.
- [x] Every enforcement record response includes `source_url` and
      `confidence_score` (`api/other_routes.py`, `api/routes/risk.py`).
- [x] S3 and Airflow made optional — `requirements-api.txt` (deploy) has
      neither; only `requirements.txt` (full OCR pipeline, dev-only) does.
- [x] `render.yaml` targets Supabase Postgres via `DATABASE_URL`, no Docker
      dependency (Render's native Python runtime).
- [x] One-shot demo ingest: `python -m pipeline.seed_enforcement` + `python -m
      models.aggregate` populates a searchable dataset without OCR or
      Airflow.
- [x] Next.js frontend (`frontend/`) with search, district detail, map,
      compare, alerts, account, admin pages.
- [x] Disclaimer banners on risk/record responses
      (`frontend/components/ui/DisclaimerBanner.tsx`, disclaimer fields in
      API responses).
- [x] Dispute mechanism wired end-to-end: `POST /v1/disputes/submit` (public)
      → admin review queue (`GET/POST /v1/admin/disputes`).
- [x] Tests for stage2 standardisation and stage3 dedup/confidence scoring
      (`tests/`, 34 cases, no DB required) + CI
      (`.github/workflows/tests.yml`) running them on every push/PR.
- [x] Daily automated real-data ingestion in the cloud
      (`.github/workflows/ingest.yml`): openFDA → AGMARKNET → FoSCoS →
      aggregate → disease burden → notifications.

## Before real users hit this

- [ ] **India district contamination data is still demo-seeded.** The only
      real signal is FSSAI PDFs (blocked — see
      [`docs/FSSAI_INGESTION.md`](docs/FSSAI_INGESTION.md)) and FoSCoS
      recalls (`pipeline/sources/fssai_recall.py`, best-effort headless
      browser scrape). Decide whether to launch with a clear "demo data"
      label on the India heatmap, or hold until FoSCoS coverage is
      sufficient.
- [ ] **Production DB role** — API runs as the Postgres owner; the
      restricted `foodsafe_app` role + row-level security exist in
      `schema.sql` but `app.user_id` is never set. Wire this in before
      handling real user data at scale.
- [ ] **Rate limiting is in-memory** for JWT/anonymous traffic — resets on
      every Render deploy and doesn't share state across instances if you
      scale beyond one dyno. Fine for launch traffic; revisit with
      Redis if usage grows.
- [ ] **Disputes don't feed back into scores** — admin review can flag/edit a
      record but doesn't trigger `models.aggregate` to recompute. Manual
      re-run (`POST /v1/admin/aggregate`) needed after a batch of reviews.
- [ ] **Legal review of disclaimer language** — current copy states data is
      OCR-extracted from public enforcement documents and may contain
      errors; get this checked before wide release given it touches food
      safety claims about named brands.
- [ ] **Error tracking / uptime monitoring** — nothing wired yet (e.g.
      Sentry, Render health-check alerts beyond the basic `/` check in
      `render.yaml`).
- [ ] **Secrets rotation** — confirm `JWT_SECRET`, `DATABASE_URL`, and
      `RESEND_API_KEY` are set as Render/Vercel/GitHub Actions secrets (not
      just locally) before the first real deploy.

## Explicitly deferred (not blocking launch)

- NER fine-tuning, APEDA / state-health scrapers, age-gating.
- Census-2021 polygon choropleth (current map uses coloured markers).
- Random Forest district-risk model going live (needs more real records
  than the demo set provides; statistical aggregation serves scores today).
- Supply-chain propagation graph (`supply_chain: []` until seeded).
