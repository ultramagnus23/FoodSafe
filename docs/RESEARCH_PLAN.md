# Research plan: estimating the disease burden of food contamination in India from open data

Chaitanya Tripathi · suhsuhbros@gmail.com · version 1, 2026-10-06

Live platform: https://foodsafev2.vercel.app · Code and data pipeline: https://github.com/ultramagnus23/FoodSafe

This document is the scope of the paper: what it asks, what it will and will not include,
which data it uses, how each part is done and checked, and the timeline. It supersedes the
paper scope in `PAPER_SCOPING.md` (the data-access audit there becomes one part of this
paper; see section 14).

---

## 1. Summary

Food contamination causes disease, but in India nobody can say how much, where, or from
what. The food regulator publishes no machine-readable test results, and no public dataset
records where contaminated food makes people ill. A disease "predictor" trained on
contamination and illness data is therefore not possible: there is nothing to train it on,
and building one would mean inventing ground truth.

There is a defensible alternative, and it is the one WHO and JECFA use: quantitative risk
assessment. The dose-response relationship comes from toxicology and epidemiology that
already exist; exposure is estimated from how contaminated foods are and how much of them
people eat; expected cases follow. FoodSafe already holds most of the pieces as an open,
cited, daily-updated platform: India's legal limits beside the EU, Codex and the US
(56,619 limits, 1,711 compared pairs), 32,805 EU contamination findings across 164 origin
countries, India's state testing outcomes from Parliament, a hazard-to-disease knowledge
base with a source for every link, and a validated hazard classifier.

The paper builds the missing step for one hazard where the science is strongest, aflatoxin
and liver cancer, and asks four things: how India's limits compare and where the gaps matter
for health; what annual burden of liver cancer dietary aflatoxin implies for India, by state,
using only public data; whether that estimate agrees with independent estimates; and which
missing data limit it most. The engine code for the burden step is written and already
reproduces a published risk assessment for India exactly (section 8.3).

## 2. Why this matters

* WHO estimates 1.52 million deaths a year worldwide from foodborne disease (2021 estimates,
  loaded in the platform). Among chemical hazards, inorganic arsenic (641,000 deaths) and
  lead (466,000) lead; aflatoxin B1 causes an estimated 13,996 liver cancers and 13,175
  deaths a year (412,396 DALYs). WHO publishes these at global level only.
* India had about 30,000 new liver cancers in 2016, and the male rate varied 7.9-fold across
  states (India State-Level Disease Burden Initiative, Lancet Oncology 2018). How much of
  that is dietary aflatoxin is unknown. Liu & Wu (2010) put India's aflatoxin exposure
  somewhere between 4 and 100 ng/kg body weight per day, a 25-fold range, because the
  occurrence data were thin.
* India's limits are often looser than the EU's. Aflatoxin M1 in milk: 0.5 µg/kg in India,
  0.05 in the EU. Total aflatoxins in spices: 30 µg/kg in India, 10 in the EU. Whether that
  matters for health is a question nobody has put a number on.
* India's regulator blocks anonymous access to its testing and recall portal. The only real
  pass/fail data over 13 years is state-level yearly totals disclosed to Parliament. A
  method that works on public data, and says exactly what data would improve it, is useful
  to researchers, journalists and the regulator itself.

## 3. Research questions and hypotheses

| | Question | Pre-specified hypothesis or expectation |
|---|---|---|
| **RQ1** Rules | How do India's legal limits for contaminants and pesticide residues compare with the EU, Codex and the US, and which gaps involve hazards with serious health outcomes? | H1: India's limit is above the EU's in most compared pesticide pairs, mostly because the EU permits no use of that pesticide on that food (as measured on 2026-10-03: 759 of 1,297 pesticide pairs higher; 683 of those are EU detection-floor limits). Re-measured on the frozen snapshot. |
| **RQ2** Hazard identification | Can public contamination records be classified by hazard reliably enough to feed the engine? | Already measured: accuracy 0.918 and macro-F1 0.777 on 6,934 later notifications, against 0.796 / 0.586 for a keyword baseline; 0.947 on India-origin notifications. The paper adds calibration and an error analysis. |
| **RQ3** Burden (primary) | Using only public data, what annual burden of liver cancer does dietary aflatoxin imply for India, nationally and by state, and does it agree with independent estimates? | H2: the national estimate falls inside the range implied by Liu & Wu (2010) for India, is a small fraction of WHO's 2021 global aflatoxin total, and in every state stays below total liver-cancer incidence (a hard plausibility bound; see 8.3). |
| **RQ4** Scenario | How would the estimate change if India's aflatoxin limits were the EU's or Codex's? | Expectation (not a hypothesis test): the change is concentrated in the foods where India's limit is furthest above the EU's (milk, spices); its size depends on how much of the occurrence distribution lies between the two limits. |
| **RQ5** Data gaps | Which missing data limit the estimate most, and what would it take to go from state to district resolution? | H3: uncertainty in contamination levels contributes more to output variance than consumption, hepatitis B prevalence or potency. |

## 4. Contributions

1. **An open disease-risk engine for food contamination** built only from public records,
   following the Codex risk-assessment steps, with every value traceable to its source,
   a document hash and a confidence level. Software, not a one-off analysis: it updates
   daily.
2. **The first machine-readable, health-linked comparison of India's food limits** with
   the EU, Codex and the US, with the reason each gap exists.
3. **An open, reproducible state-level estimate of aflatoxin-attributable liver cancer in
   India**, using current consumption data (HCES 2022-23), with stated uncertainty and
   checked against independent estimates.
4. **A quantified account of the data gap**: which inputs drive the uncertainty, and dated
   evidence of what India's regulator does and does not make available.

## 5. Scope

### In scope

| Area | Included |
|---|---|
| Geography | India: national and state/UT level. Other countries only as benchmarks and context. |
| Burden estimate | Aflatoxins (B1 and its total; M1 in milk) and hepatocellular carcinoma (ICD-10 C22.0). Foods: groundnut, maize, rice, chillies and other spices, milk; others if the review finds Indian occurrence data. |
| Screening | Hazard quotient or margin of exposure for every hazard with a measured concentration on Indian food (EU findings and the reviewed literature), as a risk flag, not a case count. |
| Standards | All 1,711 India-vs-world pairs from the frozen snapshot (pesticide MRLs and contaminant maximum levels). |
| Hazard identification | The existing classifier: evaluation, calibration, errors. |
| Data gaps | Variance decomposition of the burden estimate, plus the dated access evidence (FoSCoS probe log, RTI reply, extraction cost of the parliamentary data). |

### Out of scope, and why

| Excluded | Why |
|---|---|
| A machine-learning model trained to predict disease cases from contamination | No dataset pairs contamination and illness in the same place. Training one would require inventing outcomes. The engine predicts expected burden through published dose-response instead. |
| District, city or market estimates | No public contamination data exists at that grain (section 7.3). The paper says what would be needed. |
| Microbial hazards (Salmonella, E. coli, etc.) | Their burden is estimated from incidence surveillance, not dose-response; India's outbreak surveillance (IDSP) reports were not reachable. Kept as descriptive context. |
| Lead, inorganic arsenic, other chemicals | Their dose-response runs through blood lead or water exposure and needs different inputs. Named as the next extension; screened only. |
| Prevalence of contamination | Every source is risk-targeted testing (border checks, inspector sampling). No prevalence claims. |
| Ratings of brands or producers; health advice | Not what the data support, and legally and ethically out of bounds. |
| Causal or ecological correlation claims ("state X has more cancer because of food") | The estimate is a model output, checked for plausibility, not an observed association. |
| Nutrition of packaged food; the global susceptibility index | On the platform, but separate papers. |
| Any data obtained by getting around access controls | The audit is read-only by design; no captcha or login was bypassed. |
| Synthetic or "demo" data | Never used. The platform's production database is real-only (decided 2026-09-11). |

## 6. Framework: the engine, step by step

The engine follows the four steps of food-safety risk assessment in the Codex Alimentarius
procedural manual, plus a validation step.

| Step | What it answers | Engine component | Status |
|---|---|---|---|
| Context: rules | What each country's law allows | `standards_*.py`, `models/standards_compare.py` | Built |
| Hazard identification | Which hazard a finding or report is about | `models/health_classifier.py` (knowledge-base rules), `models/hazard_text_classifier.py` (ML) | Built and validated |
| Hazard characterisation | What the hazard does, to whom, at what dose | `pipeline/sources/hazard_kb.py` (52 curated hazards, 5 pesticide classes, IARC groups for 1,128 agents, cited outcomes); `hazard_reference_values` (ADI, ARfD, TDI); cancer potency in `models/burden_engine.py` | Built |
| Exposure assessment | How much people take in | `models/safe_intake.py` (single findings); `models/burden_engine.py` (population exposure from occurrence x consumption / body weight) | Code built; India inputs to assemble (section 7.2) |
| Risk characterisation | Expected cases, hazard quotient, margin of exposure | `models/burden_engine.py` (cases with Monte Carlo uncertainty, MOE, HQ) | Code built and tested |
| Validation | Does the estimate agree with independent evidence? | Section 8.3 | Planned |

## 7. Data

### 7.1 In hand (production database, refreshed daily or weekly)

| Dataset | Size | Period | Grain | Confidence | Role in the paper |
|---|---|---|---|---|---|
| Legal limits: FSSAI, EU, Codex, US | 56,619 limits; 1,711 India-vs-world pairs | current rule-books | food x hazard | high (EU, Codex, US), medium (FSSAI, PDF with integrity checks) | RQ1; limits for RQ4 |
| EU RASFF notifications, all origins | 32,805 notifications, 164 origins; India 2,228 (3rd) | 2019 to now | consignment x hazard, with measured value and limit | high | RQ2 training/testing; measured values for screening; upper-bound occurrence for RQ3 sensitivity |
| Lok Sabha state sampling outcomes | 539 state-year rows from 16 validated tables | 2013-14 to 2025-26 | state x year | medium | Context; RQ5 evidence (extraction cost) |
| Pesticide-residue monitoring (MPRNL) | 73 rows | 2012-13 to 2018-19 | national x commodity | medium | Screening context |
| Hazard-to-health knowledge base | 52 curated hazards with 70 cited outcome links (789 hazard-outcome rows in all), 5 pesticide classes, IARC groups for 1,128 agents | current | hazard x outcome | medium (curated, cited) | Hazard characterisation |
| Reference values (ADI, ARfD, TDI) | EFSA, JMPR, JECFA | current | substance | high | Screening |
| WHO foodborne burden (FERG 2021) | 288 rows | 2021 | global x hazard x age | high | Benchmark for RQ3 |
| Country indicators (WHO, World Bank) | 217 countries | latest years | country | high | Context |
| Peer-reviewed literature (OpenAlex, Europe PMC) | 2,569 papers on 9 contaminants | to now | paper | medium (retrieved, not vetted) | Starting corpus for the occurrence review (RQ3) |
| FoSCoS access probe log | 15 dated readings | 2026-07-04 to now | reading | n/a | RQ5 evidence |

### 7.2 To acquire (all public; access terms checked in week 1)

| Input | Source | Access | Effort | Risk |
|---|---|---|---|---|
| Aflatoxin occurrence in Indian foods | Systematic review of published surveys (PRISMA 2020): the 2,569-paper corpus plus PubMed, Scopus and Google Scholar searches | open literature | 3 weeks, the largest task | Uneven regional coverage; heterogeneous methods; publication bias |
| Aflatoxin M1 in milk | FSSAI National Milk Safety and Quality Survey 2018 report; a Lok Sabha answer gives 368 of 6,432 samples above the limit | public PDF | 2 days | Only the share above the limit may be published, not the distribution |
| Food consumption by state | MoSPI Household Consumption Expenditure Survey 2022-23 (and 2023-24): item-level quantities, rural and urban | public reports; unit-level data via MoSPI's microdata portal (registration) | 1 week | Items may be grouped (e.g. groundnut vs groundnut oil); food eaten outside the home under-recorded |
| Body weight | ICMR-NIN reference body weights (2020); NFHS-5 state anthropometry for sensitivity | public; NFHS microdata via DHS Program registration | 2 days | |
| Hepatitis B prevalence | Published meta-analyses (general population roughly 1.5-3.7%) and the 2017-18 national serosurvey (1.1% in children 5-17) | open literature | 2 days | Few adult state-level estimates; handled as a range |
| Population by state | MoHFW Technical Group population projections | public | 1 day | |
| Liver-cancer incidence by state (validation) | GBD 2021 India subnational results (IHME Results Tool); NCRP registry reports (ICMR-NCDIR) | free registration; non-commercial licence | 2 days | Modelled estimates themselves; used as a bound, not ground truth |
| Potency and benchmarks | JECFA potencies via EFSA (2020), verified; Liu & Wu (2010), verified | open | done | |

### 7.3 Not available, with the evidence

* **District or market contamination testing.** FSSAI's FoSCoS portal refuses anonymous
  access (401 from a local network; no connection at all from a GitHub runner); 15 dated
  readings in `docs/foscos_access_log.jsonl`. Enforcement-report URLs redirect to the
  homepage (`docs/FSSAI_INGESTION.md`).
* **Outbreak and illness data by place.** IDSP outbreak reports were unreachable; NCDIR
  cancer data is registry-level with no export.
* **Through RTI.** Filed 2026-07-11 (FSSAI/R/E/26/00836); answered as unable to provide the
  data.
* **Through Parliament.** Recoverable, but at state-year grain only and at high cost: of 70
  candidate tables in 124 answers, 54 failed extraction checks.

## 8. Methods

### 8.0 Common rules

* **Freeze.** The analysis runs on a dated database snapshot (dump plus sha256), so every
  number can be regenerated. The live platform keeps updating; the paper does not.
* **Pre-registration.** This plan's hypotheses, decision rules and analyses are
  time-stamped on OSF before the burden model is run on India data.
* **No tuning to targets.** Inputs are fixed from the data before comparison with
  benchmarks. If a validation check fails, the paper reports the failure and its cause; it
  does not adjust inputs until the check passes.

### 8.1 Study 1: rules (RQ1)

Descriptive analysis of the 1,711 pairs: counts and ratios by jurisdiction, by type
(pesticide MRL or contaminant ML), and by the reason for each gap (EU not approved, no use
on that food, never assessed, EU level above detection). Health-linking: each pair is joined
to the knowledge base, and pairs where India's limit is higher and the hazard is IARC Group 1
or 2A, or has a cited serious outcome, are reported separately. Sensitivity: exclude pairs
where India's value comes from a group or catch-all limit. Framing rule: a limit is a
regulatory line, not a safety verdict.

### 8.2 Study 2: hazard identification (RQ2)

The classifier is already trained on 15,210 EU notification subjects (2020-2024) and tested
on the 6,934 that came later (2025-2026). Added for the paper: per-class precision and recall,
a reliability diagram and expected calibration error, a McNemar test against the keyword
baseline, and a hand-labelled error analysis of 100 India-origin misclassifications. It
classifies text; it detects nothing.

### 8.3 Study 3: aflatoxin and liver cancer (RQ3), the core

**Exposure.** For state *s*:

    E_s = sum over foods f of  C_f x I_(f,s) / BW_s        (ng per kg body weight per day)

where C_f is the aflatoxin concentration distribution in food f (µg/kg), I_(f,s) the mean
daily intake of f in state s (g/day, from HCES), and BW_s body weight. Aflatoxin M1 is
weighted at 0.1 of B1's potency (EFSA 2020).

* *Occurrence (C_f)* from the systematic review: per food, pool reported means, SDs and
  percentiles into a lognormal distribution. Non-detects handled by EFSA practice (lower
  bound = 0, upper bound = LOD), reported both ways. RASFF values on Indian exports are an
  export-biased upper bound, used only as a sensitivity case.
* *Consumption (I)* from HCES 2022-23 state means, rural and urban, converted from monthly
  per-capita quantities to g/day.
* *Susceptibility*: hepatitis B carrier share as a range (section 7.2), higher in the
  north-eastern states where data show it.

**Risk.** Expected incidence per 100,000 per year:

    incidence_s = E_s x (potency_HBsAg+ x p_s + potency_HBsAg- x (1 - p_s))

using JECFA 2016 potencies (0.269 and 0.017 per 100,000 per year per ng/kg bw/day; upper
bounds 0.562 and 0.049), and cases = incidence x population / 100,000. Margin of exposure
against EFSA's BMDL10 of 0.4 µg/kg bw/day is reported alongside (below 10,000 = concern).
DALYs follow FERG: cases converted with GBD 2021 disability weights and life expectancy at
onset.

**Uncertainty.** Monte Carlo, 10,000 draws over concentration, intake, body weight, carrier
share and potency (uniform between central and upper bound); median and 95% interval.

**Validation, in four checks, decided before running:**

1. *Replication (done).* From Liu & Wu's inputs for India (exposure 4 to 100 ng/kg bw/day,
   JECFA 1998 potencies), the engine returns their published incidences exactly: 0.04 to
   1.00 per 100,000 for non-carriers and 1.20 to 30.0 for carriers
   (`tests/test_burden_engine.py`).
2. *External consistency.* The national estimate is compared with the range implied by
   Liu & Wu for India and with WHO's 2021 global aflatoxin total (13,996 cases). India's
   estimate must be a plausible fraction of the global figure.
3. *Plausibility bound.* In every state, attributable cases must stay below GBD's total
   liver-cancer incidence; the implied attributable fraction is compared with published
   ranges (Liu & Wu: 4.6% to 28.2% of liver cancers worldwide). A violation means the inputs
   or model are wrong, and is reported as such.
4. *Sensitivity.* One-at-a-time and variance-based (Sobol) sensitivity identify which inputs
   drive the result (feeds RQ5).

### 8.4 Study 4: limit scenarios (RQ4)

Following EFSA's assessment of raising the EU peanut limit from 4 to 10 µg/kg, concentrations
above a limit are set to that limit (full compliance), first at India's limit, then at the
EU's and Codex's, and the difference in expected cases is reported. This shows how much of
the estimated burden sits in the band between the limits. It is a scenario, not a forecast:
compliance and enforcement are not modelled.

### 8.5 Study 5: data gaps (RQ5)

From 8.3's variance decomposition: how much narrower the interval would be if each input's
uncertainty were halved (a simple value-of-information measure). Combined with the dated
access evidence (section 7.3) into concrete recommendations: what the regulator would need to
publish (machine-readable results with food, hazard, value, limit, district, date) and what
a minimal sampling study would need to measure.

### 8.6 Exploratory, only if time allows (not in the core paper)

Country-level check: does open contamination evidence (RASFF hazard profiles) add information
about national foodborne burden beyond development indicators? Nested cross-validated models;
a null result is expected and would be reported as one.

## 9. Validation at a glance

| Component | Check | Pass criterion | Status |
|---|---|---|---|
| Standards extraction | Integrity checks per rule-book; spot checks against printed documents | Documented in `docs/STANDARDS.md` | Done |
| Hazard classifier | Temporal hold-out, baseline, calibration | Beats baseline (McNemar p < 0.05) | Accuracy and baseline done |
| Burden arithmetic | Reproduce Liu & Wu (2010) India incidences | Exact | Done (19 tests) |
| Burden estimate | Consistency with Liu & Wu and FERG 2021 | Inside the implied range | Planned |
| Burden estimate | Below GBD total liver-cancer incidence in every state | No violation | Planned |
| Inputs | Double extraction on 20% of reviewed studies | Agreement reported (kappa / ICC) | Planned |

## 10. What the paper will not claim

* That anyone was harmed by a specific food, brand or place.
* That contamination is common or rare in India (all sources are targeted testing).
* That a higher Indian limit makes Indian food unsafe; only what the difference implies under
  stated assumptions.
* That the burden estimate is an observed count. It is a model output with an interval.
* That the classifier tests food.

## 11. Ethics and data governance

* Public, aggregate data only; no personal data. The one named person RASFF can carry (a
  notifier's contact) is never stored.
* Read-only access throughout. The FoSCoS audit records what a good-faith visitor can reach
  and never attempts to get around the captcha or login.
* Licences respected: GBD and DHS data under their user agreements (not redistributed);
  MoSPI unit-level data under its terms; derived results released with provenance.
* Harm: nothing names producers; results are framed so as not to alarm, with limits stated
  next to each figure.

## 12. Limitations and threats to validity

* Literature occurrence data are convenience samples with uneven regional coverage and mixed
  methods; publication may favour high findings. Mitigation: quality scoring, sensitivity
  excluding low-quality studies, bounds for non-detects.
* HCES records household purchases, grouped items and little food eaten outside the home.
* Potency comes from cohorts in China and Africa; transfer to India is an assumption, stated.
* Liver cancer has other causes (hepatitis C, alcohol, metabolic disease); the engine
  estimates the aflatoxin share only, checked against the total.
* Cancer appears years after exposure; the model assumes steady state.
* Single country, single hazard for the burden estimate.

## 13. Timeline (12 weeks from supervisor agreement)

| Week | Work | Milestone |
|---|---|---|
| 1 | Freeze snapshot; confirm data access and licences; OSF pre-registration; supervisor review of this plan | Protocol registered |
| 2-4 | Systematic review of aflatoxin occurrence: search, screening, extraction, double extraction on 20% | Occurrence dataset |
| 3-4 | In parallel: consumption, body weight, carrier share, population, GBD validation data | Input tables |
| 5 | Burden runs, validation checks 2-4 | Results, pass or fail |
| 6 | Scenarios, variance decomposition; final standards and classifier analyses | All figures |
| 7-10 | Writing; internal review | Full draft |
| 11 | Supervisor review; revisions | Submission draft |
| 12 | Preprint and journal submission; code and data release with DOI | Submitted |

## 14. Relation to the earlier scope

`PAPER_SCOPING.md` committed to an audit of India's food-safety data access. That evidence is
not dropped: it is RQ5 and the paper's explanation of why the burden estimate stops at state
level. If a supervisor prefers, it can also stand alone as a short companion paper for a
civic-tech venue (COMPASS / AI for Social Good).

## 15. Deliverables and venues

* Paper. Preprint on medRxiv (public health) with the full method; journal candidates: *Food
  and Chemical Toxicology*, *Food Control*, *Risk Analysis*, or *Toxins* for the aflatoxin
  focus. The supervisor's view decides.
* Code (open source) and the frozen dataset with a DOI (Zenodo), including the occurrence
  dataset from the review.
* The live platform, with the engine page showing the burden step once validated.

## 16. What I am asking a supervisor for

1. Is the risk-assessment framing (expected burden from published dose-response) the right
   way to build a disease engine without paired outcome data? What would make it convincing?
2. Review of the occurrence-review protocol and the validation checks before the model runs.
3. Advice on which journal, and whether the data-access audit belongs inside or beside it.
4. Introductions: epidemiologists or toxicologists working on aflatoxin, liver cancer or
   dietary exposure in India; anyone with access to state-level testing data.
5. If appropriate: supervision of the paper and co-authorship as the contribution warrants.

## 17. Status on 2026-10-06

| Piece | State |
|---|---|
| Platform (standards, findings, hazards, places, nutrition, sources, engine page) | Live at https://foodsafev2.vercel.app; data refreshed daily by CI |
| Standards comparison, RASFF all origins, knowledge base, classifier | Built, validated, in production |
| Burden engine (`models/burden_engine.py`) | Written; reproduces Liu & Wu (2010) for India; 19 tests |
| India inputs for the burden estimate | Not yet assembled (section 7.2) |
| Pre-registration, review, writing | Not started |
| Known issue | The July 2026 district engine (`models/disease_burden.py`, `dose_response_params` seeds in `schema_migration_003.sql`) cites "IARC Monograph" for aflatoxin slope factors, but IARC publishes no slope factors, and the seeded values differ from JECFA's by roughly 10-20 times. It produces no output on real data (0 estimates) and is not used by this plan; the seeds should be corrected or retired. |

## References (all checked)

* EFSA CONTAM Panel (2020). Risk assessment of aflatoxins in food. *EFSA Journal* 18(3):6040.
  https://doi.org/10.2903/j.efsa.2020.6040 (JECFA 2016 potencies; AFM1 potency factor 0.1;
  BMDL10 0.4 µg/kg bw/day; MOE below 10,000 a concern.)
* EFSA CONTAM Panel (2018). Effect on public health of a possible increase of the maximum
  level for "aflatoxin total" from 4 to 10 µg/kg in peanuts. *EFSA Journal* 16(2):e05175.
  https://doi.org/10.2903/j.efsa.2018.5175 (limit-scenario method.)
* Liu Y, Wu F (2010). Global burden of aflatoxin-induced hepatocellular carcinoma: a risk
  assessment. *Environmental Health Perspectives* 118(6):818-824.
  https://doi.org/10.1289/ehp.0901388 (25,200-155,000 cases a year worldwide; 4.6-28.2% of
  liver cancers; India exposure 4-100 ng/kg bw/day.)
* India State-Level Disease Burden Initiative Cancer Collaborators (2018). The burden of
  cancers and their variations across the states of India: the Global Burden of Disease
  Study 1990-2016. *Lancet Oncology* 19(10):1289-1306.
  https://doi.org/10.1016/S1470-2045(18)30447-9 (30,000 liver cancers in 2016, 95% UI
  29,000-32,000; crude male incidence varied 7.9-fold across states.)
* Hepatitis-B virus infection in India: findings from a nationally representative serosurvey,
  2017-18. *International Journal of Infectious Diseases* (2020).
  https://www.sciencedirect.com/science/article/pii/S1201971220307128 (HBsAg 1.1% in children
  5-17.)
* WHO Foodborne Disease Burden Epidemiology Reference Group, 2021 estimates, as loaded in the
  platform (`foodborne_burden_global`).
* Platform method documents: `docs/STANDARDS.md`, `docs/HAZARD_KB.md`,
  `docs/MODEL_HAZARD_CLASSIFIER.md`, `docs/RASFF_INGESTION.md`, `docs/LOKSABHA_SAMPLING.md`,
  `docs/BACKTEST_SAMPLING.md`, `docs/PAPER_SCOPING.md`.
