# EU RASFF notifications (India-origin food) — method, validation, limits

**Module:** `pipeline/sources/rasff.py`
**Tables:** `rasff_notifications`, `rasff_hazards`, `schema_migration_021.sql`
**API:** `GET /v1/rasff`, `GET /v1/rasff/summary` · registry entry: `api/source_registry.py` (`rasff`)
**Run:** `python -m pipeline.run_and_log rasff --limit N` (daily in `ingest.yml`)
**Tests:** `tests/test_rasff.py` (fixtures are real, trimmed API responses)

## What this is

The European Commission's **Rapid Alert System for Food and Feed (RASFF)**
publishes every notification an EU/EEA food-safety authority raises about a
food or feed consignment: the hazard found, the measured value, the legal
limit, the product, and the action taken. It is reachable through an
unauthenticated public API behind the RASFF Window site — no key, no captcha.

Filtered to notifications naming **India** among their origin countries, this
is the one source in the project with real **measured concentrations checked
against a legal limit** for Indian-origin food, published by an official
regulator, in machine-readable form. Confirmed live 2026-09-19: 2,220
notifications, 2019 → today.

## What it is NOT

* **Not a sample of food eaten in India.** Every notification is a consignment
  checked at an EU border or on the EU market, selected by risk-based
  targeting — the opposite of a random sample. A high rate for a
  product/hazard pair reflects what EU inspectors chose to check as much as
  what is actually present.
* **Not a finding against a producer.** A notification is what a notifying
  member state's authority reported; it is not a conviction, and India is not
  a party to it.
* **Not exhaustive of what leaves India.** Only consignments an EU/EEA country
  actually tested and flagged appear; most exports are never notified.
* A notification without a public detail page (`has_detail = false`) keeps
  only its list-level fields (subject, category, risk decision) — it has *no*
  hazard rows. Absence of hazards there means "detail not public," not "no
  hazard."

## Two endpoints, both public

```
POST .../rasff-window/backend/public/notification/search/consolidated/
     list, paginated, filterable by origin country. India's filter value is
     5118 (its countryNetworkOrganizationId — the ISO code 'IN' is rejected
     by the API with ERR-1003).
GET  .../rasff-window/backend/public/notification/view/id/{id}/en/
     one notification's hazards, product, and measures. Some notifications
     return 401/404 here (no public detail) — not an error, a real state.
```

## Correct-by-construction parsing

Same discipline as the Lok Sabha parsers: a value is stored only when it is
unambiguous, otherwise the field is left `NULL` rather than guessed.

| Rule | Guards against |
|---|---|
| Kept only if `IN` is among `originCountries` (list filter trusted but re-checked) | a filter change or bug silently widening scope |
| `result_value` parsed only from one clean number: `'0.26'`, `'5,0'` (decimal comma), `'42±13'` → 42 (uncertainty dropped, not folded in) | ranges, prose ("positive in 25g"), `'nd'` become `NULL`, never a guess |
| `'1,000'` is refused (thousand or 1.000 — the notifier's convention is unknowable) | silently picking the wrong magnitude |
| censored results keep their qualifier (`'>150000'` → value 150000, qualifier `'>'`) | losing the direction of a detection-limit result |
| `exceedance_ratio` computed only when result and limit share the **same, comparable unit** (`mg/kg`, `ug/kg`, `mg/l`, `ug/l`, `%`) | comparing `mg/kg` to `CFU/g` |
| a censored result can still say `exceeds_limit` when it is unambiguous (`'>150000'` vs limit 100000 → exceeds; `'<0.01'` vs limit 0.05 → does not) — otherwise `NULL` | overclaiming from a censored value |
| a zero-tolerance limit (`'not permitted'`, printed as 0) gets no ratio, only exceeds/not | dividing by zero |
| a detail page's named contact person (`additionalInformations[].contactPerson`) is never read into any row | storing personal data |
| `notif_id` and `ecValidationDate` must both parse, else the whole record is refused | a malformed list entry |

## Backfill and daily operation

The list (about 23 pages) is fetched in full every run — cheap, and it is how
new notifications and revised classifications are found. Detail pages are
fetched newest-first, capped at `--limit` per run (default 400) via
`detail_checked_at`: `NULL` means never attempted (the backfill queue); a
notification whose detail was unavailable is retried only while it is recent
(≤60 days), since older gaps are very unlikely to become public later.
2,220 list-level rows, ~400/run of detail → the first backfill spans about
six daily runs. `rasff` is in `EXPECTED_EMPTY_SOURCES`: once the backfill
finishes, most days will legitimately insert nothing new.

`RasffUnavailable` is raised (not swallowed) if the list endpoint cannot be
read at all — an outage must reach the alerter, not look like "no
notifications," the same lesson `loksabha_qa` learned on 2026-09-19
(see `docs/PAPER_SCOPING.md` §5b and `[[foodsafe-lok-sabha-sampling]]`).

## Validation (2026-09-19, live pull of all 2,220 India-origin notifications)

* **By year:** 13 (2019, partial) · 442 (2020) · 350 (2021) · 322 (2022) ·
  297 (2023) · 342 (2024) · 291 (2025) · 163 (2026, partial).
* **By classification:** 1,099 border rejections, 624 alerts, 347 information
  (for attention), 150 information (for follow-up).
* **By product category:** nuts/nut products/seeds 669, herbs and spices 433,
  cereals and bakery products 303, fruits and vegetables 203, dietetic
  foods/supplements 200.
* **Hazard detail sample (398 of 2,220 fetched in a full local backfill run):**
  662 hazard rows; 557 carried a parseable result, 459 had a same-unit limit
  to compare against, and 458 of those exceeded it. By category: pesticide
  residues 462 (377 exceeding), mycotoxins 53 (42 exceeding), pathogenic
  micro-organisms 37 (0 — these are presence/absence tests, not a
  concentration vs. limit), environmental pollutants 26 (11), heavy metals 17
  (10).
* **Largest exceedances seen:** ethylene oxide in a spice consignment,
  81.1 mg/kg against a 0.1 mg/kg limit (811×); chlorpyrifos, 0.315 mg/kg
  against 0.001 mg/kg (315×). These are real notified values, not
  representative of typical exports — they are exactly the risk-targeted
  extreme cases RASFF exists to catch.
* Re-running the ingest twice against this same pull inserted the migration's
  tables once and the second `run()` inserted zero new rows and zero new
  hazards — idempotent.

## Known limits

* **Pathogenic micro-organisms rarely have a numeric result** (`'positive in
  25g'`), so most of that category's exceedance flag stays `NULL` — the
  hazard is real, but this source cannot quantify it.
* **Hazard names are the notifier's own free text** (`"chlorpyrifos - unauthorised substance"`);
  the same active ingredient can appear under slightly different names across
  notifications and is not yet canonicalised against `contaminants`.
* **No product/brand identity** — a notification names a product category and
  a short description, not a specific commercial product.
* Only 398 of 2,220 detail pages had been fetched at the time of this write-up
  (the rest complete over the following backfill runs); summary counts above
  the "hazard detail sample" line are from the full list, everything below it
  is from that partial detail set and will grow as the backfill completes.

## Relevance to the model and the paper

* **Model:** the one source with true measured concentrations against a legal
  limit for Indian-origin food. Still not usable for a district or brand risk
  score (no India-side geography), but it is real evidence for the
  contamination-relevant claim the literature layer alone cannot make: which
  hazards actually appear in Indian exports, and by how much they exceed
  limits when they do.
* **Paper B (access audit):** a useful contrast case — unlike FSSAI's own
  gated portal, a foreign regulator publishes the equivalent kind of finding
  about Indian food in a fully open, machine-readable API. The comparison
  sharpens the argument that the access barrier is a choice, not a technical
  necessity.
