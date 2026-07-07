# FoodSafe India — Product Requirements Document (v1: H1 + H2)

Status: draft, scoped from `Phase 0 audit` (see conversation / `docs/` for supporting evidence).
Scope: only H1 (trust & correctness) and H2 (user value loop) features. H3/H4 are spec'd in the master
build prompt but explicitly out of scope for this document — do not build against them yet.

## Positioning decision (resolves Phase 0 item 14)

FoodSafe India ships as a **transparent beta**. The site is honest that:
- Methodology, statistical/ML machinery, and the openFDA-backed US comparison layer are real and live.
- India district-level enforcement scores are currently backed by **synthetic demonstration data**
  (`pipeline/seed_enforcement.py`), because FSSAI/FoSCoS have no programmatically accessible real
  enforcement dataset today (`docs/FSSAI_INGESTION.md`, `docs/REACHABLE_TEXT_INVENTORY.md`). This is
  disclosed, not hidden, and is itself a documented finding (the parallel research paper, `docs/PAPER_SCOPING.md`).
- The product's job in v1 is to be the credible, disclosed, ready-to-ingest shell that goes live with
  real Indian coverage the moment a real feed exists (RTI response, state portal, or FSSAI policy change) —
  not to imply real coverage it doesn't have.

This decision governs every acceptance criterion below: any feature touching India district/brand/commodity
risk must carry a visible provenance indicator, no exceptions.

## Problem statement

India has no unified, credible, source-attributed view of food-safety enforcement outcomes. Consumers,
journalists, QA leads, and exporters each need a different slice of this signal, but today they either have
nothing (no open FSSAI data), or unverifiable social-media rumor, which itself creates defamation and
misinformation risk. FoodSafe India's job is to be the place that tells the truth about what is and isn't
known — including "we don't have real data for this district yet" — while providing a real, working,
US-benchmarked methodology so the moment real Indian data becomes reachable, the product is ready.

## Personas & jobs-to-be-done

1. **Urban consumer** — "Before I buy/eat X, is there any documented safety signal for this product/place,
   and can I trust the answer, including 'no data'?"
2. **Journalist/researcher** — "Give me a citable, source-linked fact I can quote without exposing myself
   to a defamation claim, and let me tell when a claim is real vs. demonstration data."
3. **Food-business QA lead** — "Let me monitor recall/enforcement signal relevant to my supply chain and
   get alerted when something changes, without false alarms from synthetic noise."
4. **Exporter** — "Show me how Indian limits compare to Codex/EU/US so I know where my compliance risk is,
   backed by defensible methodology."

## H1 — Trust & correctness

### H1.1 Provenance UI
**User story:** As any user, when I see a risk score, alert, or ranking, I can immediately see where the
number came from, how fresh it is, and how much to trust it.
**Acceptance criteria:**
- Every risk score, alert card, search result, and map marker displays: source type (real / synthetic-demo),
  fetch/generation date, and confidence score.
- "Synthetic-demo" is visually distinct (not just a tooltip) — a persistent badge/color, not hover-only.
- `/methodology` states in plain language what fraction of currently-displayed India records are synthetic
  and why, linking to `docs/FSSAI_INGESTION.md`'s finding.
- API responses (`/v1/risk/*`, `/v1/disease/*`, `/v1/compare/*`) already return `source_type`/`confidence_score`
  fields — no backend schema change needed, this is a frontend surfacing requirement.
**Out of scope:** per-record citation links to original PDFs (no real PDFs exist yet for India).

### H1.2 Coverage-map honesty
**User story:** As a consumer looking at the map, a district with no data must look different from a
district with good data, so silence is never read as safety.
**Acceptance criteria:**
- `/map` renders a distinct "no data" state (e.g., gray/hatched) wherever `n_tests` is 0 or below a stated
  minimum, never defaulting to a green/low-risk color.
- Same rule applies to `/compare` and `/district/[id]`.
- Verified via test: a district with zero `enforcement_records` renders visually distinct from a district
  with a real low fail rate.

### H1.3 Scraper health dashboard + alerting
**User story:** As the operator, I need to know the difference between "FSSAI blocked as expected" and
"openFDA ingestion broke" without reading logs.
**Acceptance criteria:**
- New `pipeline_runs` table logs each `.github/workflows/ingest.yml` step: source, start/end time, status,
  row count, error detail.
- `/admin` overview shows last-run status per source with an explicit "expected failure" flag for
  FSSAI/FoSCoS (401/captcha) vs. an unexpected failure for openFDA/AGMARKNET.
- Unexpected failure (any source other than FSSAI/FoSCoS failing, or FSSAI/FoSCoS returning something
  other than 401/403/503) triggers a GitHub issue or email to the operator.
**Out of scope:** paging/on-call integration.

### H1.4 Model-card page
**User story:** As a journalist or researcher, I can find a single page describing exactly how risk scores
and disease-burden estimates are computed, their known limitations, and their calibration status.
**Acceptance criteria:**
- Extends existing `/methodology` (does not require a new route).
- States: features used, target definition, class imbalance handling, evaluation method (must state
  temporal split, not random, once backtesting exists), and the synthetic-data caveat from H1.1.
- Links to the backtest report (H1.5) once published.

### H1.5 Backtest report
**User story:** As a researcher, I can see evidence the risk model has been checked against real-world
corroborated events, not just self-reported fit.
**Acceptance criteria:**
- Evaluated only against the real-data slice of the pipeline (openFDA-backed records) — do not backtest
  against synthetic India data and present it as validation.
- Temporal split (train on earlier period, evaluate on later), not random split.
- Publishes Brier score (or equivalent calibration metric) and a plain-language limitations paragraph.
- Rendered as a static section linked from `/methodology`, not a new interactive feature.

## H2 — User value loop

### H2.1 Location-based alert subscriptions
Status: **already implemented** (`/account/alerts`, `alert_subscriptions` table, `models/notifications.py`
via Resend email). Acceptance for v1: confirm existing flow correctly tags synthetic-vs-real alerts per
H1.1 before counting as "done" for this PRD's trust bar.

### H2.2 Product/brand recall search
Status: **already implemented** (`/search`). Acceptance for v1: add provenance badge per H1.1; add brand
disambiguation warning is already present — verify it still appears for ambiguous brand names.

### H2.3 FSSAI license lookup / inspection history
**Status: not started, and blocked.** No reachable structured FSSAI source exists today
(`docs/FSSAI_INGESTION.md`). Do not build this until either (a) a real feed becomes reachable (RTI response,
policy change, state portal), or (b) scope is explicitly redefined to a different lookup source.
**Out of scope for v1.**

### H2.4 Report-an-issue flow
**User story:** As a consumer, I can report a suspected food-safety issue, understood as a low-credibility,
high-volume signal distinct from lab-verified enforcement data.
**Acceptance criteria:**
- New consumer-facing submission form (separate from `/v1/disputes`, which is for correcting existing
  records, not reporting new issues).
- Submitted reports are stored with `source_type='consumer_report'` and a low default confidence score;
  never displayed with the same visual weight as lab-verified records (ties back to H1.1's provenance rule).
- Reports never auto-publish a brand/product accusation — they queue for admin review before any public
  surfacing, consistent with the defamation-avoidance hard constraint.
**Out of scope:** report-driven automatic risk score changes (feeds into H2.6/disputes loop later, not v1).

### H2.5 Embeddable district-risk widget
**User story:** As a journalist, I can embed a small, correctly-captioned risk widget in an article.
**Acceptance criteria:**
- Widget inherits the same provenance badge/disclosure as the main site — cannot be embedded without the
  synthetic-data disclosure if the underlying district is synthetic-only.
- Read-only, iframe-embeddable, no auth required for public districts.
**Out of scope:** custom theming, analytics on embed views.

### H2.6 Disputes → confidence feedback loop
**User story:** As the operator, when a dispute is resolved, the underlying record's confidence score
should reflect that outcome automatically, not just sit in an admin log.
**Acceptance criteria:**
- On `resolved_removed`: mark record `is_duplicate` or a new `is_retracted` flag; excluded from aggregation.
- On `resolved_flagged`: reduce `confidence_score` and pipe into `fraud_audit`.
- On `resolved_kept`: no change, but timestamp the review so it doesn't need re-litigating.
- `models/aggregate.py` recompute picks up these changes on next scheduled run.

## Success metrics

- WAU (weekly active users)
- Alert subscription count (new signups + retention of existing subscriptions)
- Repeat-visit-within-30-days (leading indicator of trust/value, tracked per persona segment where possible)
- API signups (B2B key creation via `/account/api`)
- **Provenance-badge impression rate** (added metric specific to this PRD's positioning: % of risk-score
  views that show a provenance badge — should be ~100% once H1.1 ships; used as a build QA metric, not a
  growth metric)

## Non-goals

- No individual-restaurant ratings.
- No medical advice or real-time claims.
- No FSSAI license lookup (H2.3) until a real data source exists.
- No SMS/WhatsApp alert channel in this scope (email only; WhatsApp Business API is H3/H4, spec-only).
- No Hindi UI, no lab-marketplace, no tiered API monetization changes beyond what's already shipped —
  all H3/H4 per the master prompt.

## Risks (carried from Phase 0 register)

- Synthetic India data rendered indistinguishably from real data — **addressed directly by H1.1–H1.3**, the
  reason this PRD prioritizes them first.
- "Best districts" ranking (`/compare`) reaching press/social media as if real — mitigated by H1.1's
  mandatory badge plus H1.4's explicit methodology caveat; recommend a distinct on-page warning specifically
  on `/compare`'s ranking view given its highest-risk framing (a ranked list reads as more authoritative than
  a single lookup).
- No backtest/model card today — addressed by H1.4/H1.5, scoped only to the real (openFDA) data slice.
- RLS/API-key-as-DB-owner and in-memory rate limiting — explicitly **not** in this PRD; flagged for a
  separate infra hardening pass before any real multi-tenant B2B scale-up.
