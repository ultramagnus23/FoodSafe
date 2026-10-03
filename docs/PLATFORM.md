# FoodSafe India — platform structure

FoodSafe answers four questions with public records only, and says plainly where
the records run out:

1. **What do the rules allow?** India's legal limits for pesticides, metals,
   mycotoxins and other contaminants, set beside the EU, Codex and the US — and why
   each limit exists.
2. **What is actually found in food?** Contamination records: EU border and market
   findings (all origins), India's pesticide-residue monitoring and state sampling
   outcomes disclosed to Parliament, local news.
3. **What does that mean for health?** Every finding classified by hazard, and each
   hazard linked to the diseases it is known to cause (cited); how much of a
   contaminated food reaches a safe-intake limit; global burden context.
4. **How do places compare?** Indian states, countries (food-safety capacity,
   nutrition, EU findings), and the nutrition of packaged food sold in India.

Public face: **https://ultramagnus23.github.io/FoodSafe/** (static portal rebuilt
daily from the production database) and the REST API (`/v1/...`, docs at `/docs`).

## Layers

```
 public records ──► connectors (pipeline/sources/*) ──► Postgres (Supabase)
                                                          │
          knowledge + models (models/*, hazard_kb) ◄──────┤
                                                          │
                     REST API (api/routes/*) ◄────────────┤
                     static portal (scripts/export_portal.py → site/) ◄──┘
```

| Layer | What it holds | Where |
|---|---|---|
| **Contamination records** | EU RASFF notifications, every origin, 2020→ (~32,800; India ~2,200) with measured values vs legal limits; Lok Sabha state sampling outcomes (2013-14→2025-26) and pesticide-residue monitoring (2012-13→2018-19); FSSAI annual report; openFDA (comparison); local news | `rasff.py`, `loksabha_*.py`, `fssai_annual_report.py`, `openfda.py`, `local_news.py` |
| **Standards** | ~56,000 legal limits from four rule-books, keyed for comparison; ~1,700 India-vs-world comparisons with the basis of every value | `standards_*.py`, `models/standards_compare.py`, `docs/STANDARDS.md` |
| **Hazard → health knowledge** | IARC classification of 1,128 agents; 52 curated hazards and 5 pesticide classes with outcomes, organ systems, timing, vulnerable groups, each cited (WHO, IARC, EFSA, EPA, CDC, FAO); ADI/ARfD/TDI reference values (EFSA, JMPR, JECFA) | `hazard_kb.py`, `docs/HAZARD_KB.md` |
| **Models** | (a) hazard-category text classifier (ML); (b) disease classification of findings (knowledge base); (c) health-outcome profiles per origin; (d) safe-intake calculator; (e) nutrition classification; (f) state sampling backtest | `models/hazard_text_classifier.py`, `health_classifier.py`, `health_profile.py`, `safe_intake.py`, `nutrition.py`, `backtest_sampling.py` |
| **Places** | Indian states (sampling, enforcement, labs, commissioners); 217 countries (WHO food-safety capacity, World Bank nutrition, EU findings); WHO global foodborne burden by hazard | `api/routes/places.py`, `country_indicators.py`, `api/routes/countries.py` |
| **Nutrition** | ~21,000 packaged foods sold in India (Open Food Facts): Nutri-Score, NOVA, UK front-of-pack traffic lights | `off_india.py`, `models/nutrition.py` |
| **Trust** | Every source classified (high / medium / low) by a fixed rubric; its scope limits served next to its data | `api/source_registry.py`, `GET /v1/meta/sources` |

## The models, and what each is (and is not)

* **Hazard-category classifier (ML).** TF-IDF + logistic regression trained on 15,210
  EU RASFF notification subjects (all origins, 2020–2024), tested on the 6,934 that
  came later (2025–2026): accuracy 0.918, macro-F1 0.777, against 0.796 / 0.586 for a
  keyword baseline. India-origin test accuracy 0.947. Labels are the notifying
  authorities' own hazard categories. Model card: `docs/MODEL_HAZARD_CLASSIFIER.md`.
  It classifies what a text says; it cannot detect contamination.
* **Disease classification.** Deterministic: a finding's hazard → the knowledge base's
  outcomes for that hazard (or its pesticide class, or the notifier's category), each
  with its source. No trained "disease predictor" exists because no public dataset
  links contamination in a place to illness in that place — building one would mean
  inventing training data, which this project does not do.
* **Health-outcome profiles.** Per origin country: how many findings involve a hazard
  that can cause each outcome. Counts findings, never illnesses.
* **Safe-intake calculator.** Grams of a food that reach the ADI/TDI (daily, for life)
  or ARfD (one day) at a measured concentration. Refuses to give a number for
  genotoxic carcinogens and where JECFA/EFSA withdrew or could not set a value.
* **Nutrition classification.** Published rules (UK DHSC front-of-pack thresholds);
  Nutri-Score and NOVA as Open Food Facts computes them. A model trained to reproduce
  a deterministic score would add nothing.
* **State sampling backtest.** Last year's non-conforming rate predicts the next far
  better than the national rate, but no model beat persistence
  (`docs/BACKTEST_SAMPLING.md`).

## What the first full run found (2026-10-03)

Measured on a database built from the live sources (production loads run in CI;
the portal and `GET /v1/standards/summary` always show current values):

* India permits more than the EU in **831 of 1,711** food–hazard pairs it regulates
  (pesticides 759 of 1,297; contaminants 72 of 414). **Why:** in 683 of the 759
  pesticide pairs the EU permits no use of that pesticide on that food (497 not
  approved in the EU, 94 approved but not for that food, 92 never assessed), so its
  limit is the detection floor — "should not be found", not a safe level. In only 76
  does the EU set a residue level above detection (an EU use, an import tolerance or
  a temporary limit); there India's limit is a median 3× the EU's
  (`docs/STANDARDS.md`, "Why limits differ").
* **114** of the pesticides India sets food limits for are not approved in the EU
  (approval status of the specific substance, from the EU Pesticides Database).
* Lead in dried spices: India 10 mg/kg vs EU 0.6–1.5 and Codex 0.6–2.0. Aflatoxin M1
  in milk: India 0.5 µg/kg vs EU 0.05. Total aflatoxins in spices: India 30 µg/kg vs
  EU 10, Codex 20 (chilli).
* Food from India drew **2,118** EU notifications in 2020–2026 (second to Türkiye).
  Linked through the knowledge base, the leading implied outcomes are cancer (662
  findings, mostly ethylene oxide), acute cholinergic poisoning from organophosphate
  pesticides (375), aflatoxin liver toxicity (164) and salmonellosis (145).
* WHO's 2021 global estimate of foodborne deaths, as loaded: **1.52 million**,
  matching WHO's published figure; inorganic arsenic (641,000) and lead (466,000) lead.
* India: anaemia in 53.7% of women of reproductive age, stunting in 32.9% of children
  under 5 (World Bank, latest years); food-safety capacity self-assessed at 60% (WHO).
* Of 3,802 graded packaged foods sold in India, 61% score D or E on Nutri-Score; 55%
  of those with a NOVA group are ultra-processed.

## Limits, stated once

* No district-level contamination data exists publicly for India; nothing here is a
  prevalence estimate. EU findings are risk-targeted checks of exports; Lok Sabha
  samples are inspector-targeted.
* A legal limit is a regulatory line, not a safety verdict.
* Open Food Facts is crowd-sourced label data.
* India's food-recall portal (FoSCoS) refuses anonymous access; IDSP outbreak reports
  were unreachable from here (see `docs/PAPER_SCOPING.md`).

## Running it

Daily `ingest.yml` (contamination records, RASFF all origins, health profiles), weekly
`standards.yml` (rule-books, knowledge base, country indicators, packaged foods,
comparison), daily `deploy-pages.yml` (portal). Each step logs to `pipeline_runs`;
failures open one rolling GitHub issue (`scripts/ingest_alert.py`). Schema:
`scripts/bootstrap_db.py` applies `schema.sql` + every migration, idempotently.

## For funders and collaborators

* **Novel and open:** the first machine-readable, cited comparison of India's food
  rule-book with the EU, Codex and the US; a hazard→health knowledge base tied to real
  findings; all code and methods public.
* **Honest by construction:** every value keeps the printed source cell, the document
  version (sha256) and a confidence level; synthetic data is never served.
* **Next, with support:** district-level testing data via RTI and state partnerships;
  IDSP outbreak digitisation; FSSAI veterinary-drug limits; Hindi and regional-language
  interfaces; an independent expert review of the knowledge base.
