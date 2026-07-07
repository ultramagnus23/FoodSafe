# FoodSafe India — Technical Requirements Document (v1: H1 + H2)

Companion to `PRD.md`. Scoped to the same H1/H2 feature set. Reflects the actual current architecture
(verified against the repo), not a greenfield design.

## 1. Architecture (current + additions)

```mermaid
flowchart LR
    subgraph Ingestion
        openfda[openfda.py\nreal, working]
        agmark[agmarknet.py\nreal, working]
        fssai[fssai.py / fssai_recall.py\nblocked 401+captcha]
        seed[seed_enforcement.py\nsynthetic demo fill]
    end

    subgraph Pipeline["4-stage ETL"]
        s1[stage1_extract.py\nOCR + spaCy NER]
        s2[stage2_standardise.py\nfuzzy alias match]
        s3[stage3_and_4.py\ndedup + confidence]
    end

    subgraph Storage["Postgres / Supabase"]
        raw[(enforcement_records\npartitioned by year)]
        runs[(pipeline_runs — NEW)]
        agg[(agg_district_commodity_risk\nagg_brand_safety_profile)]
        disease[(disease_burden_estimates\nexposure_alerts)]
    end

    subgraph Models
        m1[aggregate.py]
        m2[district_risk.py — RF]
        m3[disease_burden.py — PAF/Monte Carlo]
        m4[fraud_detection.py]
        m5[trend_analysis.py]
    end

    subgraph API["FastAPI (12 routers)"]
        v1[/v1/risk, /v1/disease, /v1/compare,\n/v1/trends, /v1/search, /v1/meta.../]
    end

    subgraph Frontend["Next.js (SSR/SSG)"]
        fe[district/[id], map, compare,\nsearch, alerts, admin, methodology]
    end

    openfda --> s1
    fssai -.blocked.-> s1
    agmark --> raw
    seed --> raw
    s1 --> s2 --> s3 --> raw
    raw --> runs
    raw --> m1 --> agg
    raw --> m2
    agg --> m3 --> disease
    raw --> m4
    agg --> m5
    agg --> v1
    disease --> v1
    v1 --> fe
```

Ingestion, pipeline stages, storage, and API layers already exist and work as drawn. The additions in this
TRD are: `pipeline_runs` table (H1.3), provenance fields surfaced through to the frontend (H1.1 — fields
already exist, wiring doesn't), and the confidence-feedback path from disputes back into `enforcement_records`
(H2.6).

## 2. Data contracts

Existing schema (`schema.sql` + migrations 002–004) already versions tables reasonably well via sequential
migration files. For v1:

- **No new source added** in this scope (FSSAI remains blocked; do not build a data contract for it yet).
- **`source_type` enum** (`fssai | usfda | efsa | apeda | state_health | agmarknet | consumer_report` —
  add `consumer_report` for H2.4) is the drift-detection surface: any ingester writing an unrecognized
  `source_type` should fail the pipeline run loudly (new contract test in `tests/`), not silently insert.
- **Drift-detection tests**: extend `tests/test_stage2_standardise.py` style tests to assert
  `stage3_and_4.py` rejects records missing `source_type`, `source_url`, or `confidence_score` — these three
  fields are the backbone of H1.1's provenance UI and must never be nullable in practice even though the
  column may allow it.

## 3. Pipeline orchestration additions

- **New table `pipeline_runs`**: `id, source, started_at, finished_at, status (success|failed|expected_failure),
  rows_ingested, error_detail, workflow_run_url`.
- `ingest.yml` writes a row per source step (openfda, agmarknet, fssai_recall) at start and finish.
- FSSAI/FoSCoS step: any 401/403/503 response is written as `expected_failure` (matches the documented,
  intentional blocked state) and does **not** trigger alerting. Any other failure mode (5xx from openFDA,
  AGMARKNET timeout beyond retry budget, or FSSAI suddenly returning 200 with parseable content — which
  would be a signal worth knowing about) writes `failed` and triggers a GitHub issue via `gh issue create`
  in a follow-up workflow step, or an email via the existing Resend integration.
- Retries: keep existing per-source retry/backoff if present; add a max-retry cap so a single bad run
  doesn't block the daily schedule indefinitely.

## 4. Model spec (scoped to what H1.4/H1.5 need)

- **Features already in use** (`district_risk.py`): lab_fail_rate_12m, n_tests_12m, water_quality_index,
  industrial_proximity_score, seasonal_factor, historical_trend_slope, district_pop_density,
  state_avg_fail_rate.
- **Target**: binary/continuous fail rate over a quarter window — already defined, document as-is on the
  model-card page.
- **Calibration**: not currently done. Add isotonic or Platt scaling as a post-hoc calibration step over
  the openFDA-backed slice only (synthetic India data must not be used to "calibrate" anything, since
  calibrating against fake ground truth produces a false sense of accuracy).
- **Temporal evaluation protocol**: split openFDA records by date (e.g., train ≤ 2024, evaluate 2025–2026),
  never a random shuffle, given this is incident time-series data.
- **Rollback plan**: `agg_district_commodity_risk`/`agg_brand_safety_profile` already carry `model_version`
  — on a bad model deploy, admin `/v1/admin/aggregate` recompute can be re-run against the prior
  `model_version` tag; no new infra needed, just a documented runbook step.

## 5. API design

Already REST, versioned under `/v1`, with JWT + API-key auth and tier-based rate limits (`api/auth_utils.py`,
`api/main.py:56–111`). Additions for this scope:

- Ensure `source_type`, `confidence_score`, `fetch_date`/`created_at` are present in every response payload
  from `/v1/risk/*`, `/v1/disease/*`, `/v1/compare/*`, `/v1/search` — audit each router for a field that's
  computed but not serialized, and add it to the Pydantic response models where missing.
- New `POST /v1/reports` endpoint (H2.4) — public, unauthenticated (rate-limited by IP), writes a
  `source_type='consumer_report'` record with low default confidence, queued (`admin_review_status='pending'`)
  rather than immediately visible.
- No breaking changes to existing endpoint shapes — additive fields only, to avoid an API version bump.

## 6. Frontend rendering strategy

Already SSR/SSG via Next.js app router (`frontend/app/district/[id]/page.tsx` server-renders for SEO,
`sitemap.ts` exists). This satisfies the master prompt's SEO hard constraint — **no migration needed**,
this was already done in a prior sprint. TRD scope here is additive component work only:
- `ProvenanceBadge` component (source type, date, confidence) — shared across map markers, search results,
  district cards, compare rows, and the new embeddable widget (H2.5).
- `NoDataState` component for the map/compare/district views (H1.2) — visually distinct fill/marker style,
  not a copy-paste of the low-risk style with different text.

## 7. Alerts infra

Already implemented: `alert_subscriptions` table, `models/notifications.py` via Resend email. No change
needed for H2.1 beyond the provenance-badge audit already covered in H1.1. WhatsApp Business API remains
H3/H4 — spec only, do not build.

## 8. Security / legal

- **Takedown/dispute flow**: `/v1/disputes` + admin review UI already exist. H2.6 closes the loop so a
  resolved dispute actually changes what's displayed, not just what's logged.
- **Disclaimer copy**: standardize the existing per-response disclaimer text (already present per Phase 0
  audit — "never names brand/manufacturer/batch") to also state synthetic-vs-real status inline, reusing
  the same string the `ProvenanceBadge` component renders, so there's one source of truth for the wording
  rather than duplicated copy in the API and frontend.
- **Data retention**: no change proposed in this scope; `audit_log` table already exists for access
  tracking. Out of scope: formal retention-period policy document (flag as a follow-up, not H1/H2).
- **Consumer report abuse**: H2.4's public unauthenticated endpoint needs basic abuse controls — rate limit
  by IP (reuse existing rate-limit middleware pattern), and admin-review-before-publish (never auto-publish)
  is the primary defamation safeguard, not CAPTCHA or similar friction.

## Explicitly not in this TRD

RLS `app.user_id` context fix, DB-backed (vs in-memory) rate limiting for JWT users, FSSAI real ingestion,
FSSAI license lookup, WhatsApp alerts, lab marketplace, Hindi UI — all either infra-hardening follow-ups
independent of H1/H2, or explicitly blocked/deferred per the PRD.
