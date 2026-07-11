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
- [x] **H1 (trust & correctness) closed** per `PRD.md`/`TRD.md`: provenance
      badges on every score/marker/result (`ProvenanceBadge.tsx`,
      `api/provenance.py`), honest map "no data" state (distinct gray
      marker, never defaulted to low-risk), `pipeline_runs` health table +
      expected-vs-unexpected-failure alerting, model-card + backtest report
      published on `/methodology` (honest null result on openFDA's 66
      recall-only records).
- [x] **H2 (user value loop) closed**: disputes → confidence feedback loop
      (`resolved_removed`/`resolved_flagged` now mutate `enforcement_records`
      and `models.aggregate` picks it up), consumer report intake
      (`api/routes/reports.py`, `/report`), embeddable district-risk widget
      (`api/routes/widget.py`, `/embed/district/[id]`).
- [x] Full design-system redesign ("The Public Register") with light/dark
      theming, AA-contrast-verified tokens.

## Before real users hit this

- [ ] **India district (and now locality) contamination data is still
      demo-seeded.** The only real signal is FSSAI PDFs (blocked — see
      [`docs/FSSAI_INGESTION.md`](docs/FSSAI_INGESTION.md)) and FoSCoS
      recalls (`pipeline/sources/fssai_recall.py`, best-effort headless
      browser scrape). This is now disclosed end-to-end (H1.1/H1.2), so
      "launch with a demo-data label" is effectively the decision already
      made — remaining question is only whether that's sufficient or you
      hold for real coverage. Since this was last written: added
      locality-level geography below district (`schema_migration_009.sql`
      — real Mumbai neighborhoods/pincodes, see
      [`docs/LOCALITY_DATA.md`](docs/LOCALITY_DATA.md)) with a pincode-aware
      report form as the realistic near-term real-data path; confirmed
      FoSCoS's FBO/license search is blocked the same way the recall API is
      ([`docs/FSSAI_FBO_LICENSE_INVESTIGATION.md`](docs/FSSAI_FBO_LICENSE_INVESTIGATION.md));
      built and validated a local-Mumbai-news ingester that found real
      neighborhood-tagged signal where national FSSAI PDFs found none
      ([`docs/LOCAL_NEWS_INGESTION.md`](docs/LOCAL_NEWS_INGESTION.md), not
      yet wired into the DB).
- [x] **TLS/JWT-secret gaps closed** — the Supabase connection had
      certificate verification fully disabled (`api/db.py`); `JWT_SECRET`
      silently fell back to a hardcoded string if unset (`api/auth_utils.py`,
      now fails fast in production instead).
- [ ] **Production DB role** — `schema.sql` already defines the restricted
      `foodsafe_app` role + RLS policies keyed on `app.user_id`. Scaffolding
      is now real: `api/db.py`'s `user_scoped()` sets that session variable
      for the routes that touch it, `schema_migration_008.sql` fixed a
      `refresh_tokens` policy gap and missing grants, and
      `python -m scripts.verify_rls_activation` automates the pre-flip
      smoke test against a staging DB. **Not yet activated** — switching
      the real `DATABASE_URL` to `foodsafe_app` is a deliberate, tested
      infra decision, not a code change; see
      [`docs/RLS_ACTIVATION.md`](docs/RLS_ACTIVATION.md).
- [x] **Rate limiting for the two public unauthenticated write endpoints**
      (`POST /v1/reports`, `POST /v1/disputes/submit`) is now DB-backed and
      persisted (`api/public_rate_limit.py`, `public_submission_log`),
      rather than resetting on every deploy.
- [ ] **Rate limiting for JWT/anonymous read traffic is still in-memory**
      (`api/main.py:_rate_limit_state`) — deliberately left as-is: `render.yaml`
      runs a single free-tier instance today, so the "doesn't share state
      across instances" failure mode doesn't apply yet, and adding a
      synchronous DB round-trip to every API request to persist this now
      would trade a real latency cost for a benefit (surviving a deploy
      mid-window) that only matters once you're actually scaling. Move to
      Redis at that point, per the original note here, rather than Postgres.
- [ ] **Legal review of disclaimer language** — current copy states data is
      OCR-extracted from public enforcement documents and may contain
      errors; get this checked before wide release given it touches food
      safety claims about named brands. Full list of every file this copy
      lives in: [`docs/PRE_LAUNCH_OPS.md`](docs/PRE_LAUNCH_OPS.md).
- [x] **Error tracking wired** — `sentry_sdk.init()` in `api/main.py`, opt-in
      via `SENTRY_DSN` (unset = no-op, exactly the prior behavior). Render
      health-check alerting beyond the basic `/` check in `render.yaml` is
      still unconfigured — that's a Render dashboard setting, not code.
- [ ] **Secrets rotation** — confirm `JWT_SECRET`, `DATABASE_URL`,
      `RESEND_API_KEY`, and (new) `SENTRY_DSN` are set as real
      Render/Vercel/GitHub Actions secrets, not just locally. Exact
      names-per-platform checklist: [`docs/PRE_LAUNCH_OPS.md`](docs/PRE_LAUNCH_OPS.md).

## Explicitly deferred (not blocking launch)

- H2.3 FSSAI license lookup / inspection history — blocked on a real feed,
  per `PRD.md`.
- NER fine-tuning, APEDA / state-health scrapers, age-gating.
- Census-2021 polygon choropleth (current map uses coloured markers).
- Random Forest district-risk model going live (needs more real records
  than the demo set provides; statistical aggregation serves scores today).
- Supply-chain propagation graph (`supply_chain: []` until seeded).
- WhatsApp alerts, Hindi UI, lab marketplace, tiered API monetization
  beyond what's shipped — all H3/H4 per `PRD.md`, spec-only, do not build
  yet.
