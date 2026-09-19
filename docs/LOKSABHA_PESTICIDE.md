# Pesticide-residue monitoring results (MPRNL, via Lok Sabha) — method, validation, limits

**Module:** `pipeline/sources/loksabha_pesticide.py`
**Table:** `pesticide_residue_annual`, `schema_migration_020.sql` (shares `loksabha_question_log` with `docs/LOKSABHA_SAMPLING.md`)
**API:** `GET /v1/meta/pesticide-residues` · **UI:** Directory → "Pesticide Residues Above the Legal Limit (National)"
**Run:** `python -m pipeline.run_and_log loksabha_pesticide` (daily in `ingest.yml`)
**Tests:** `tests/test_loksabha_pesticide.py` (each rejection rule is pinned to a real answer's table or text)

## What this is

The Agriculture Ministry's scheme *Monitoring of Pesticide Residues at National
Level* (MPRNL) tests food commodities in participating laboratories and counts
samples **above the FSSAI Maximum Residue Limit (MRL)**. Those counts reach the
public through Lok Sabha written answers. This is real contamination test data
with a pass side (`analysed − above MRL`) — the kind the project otherwise
cannot get, because FSSAI's enforcement records are not accessible
(`docs/FSSAI_INGESTION.md`).

**Grain: national × commodity × period.** No state, district, brand, product or
lab. Coverage is 2012-13 → 2018-19, from six answers in the 16th and 17th Lok
Sabha; nothing later has been found (LS18 answers on pesticide residues quote
policy and lab counts, not results). The 15th Lok Sabha's search results carry no
PDF URL, so its pesticide answers were not reachable.

## What it is NOT

* Not a prevalence estimate. Samples are collected by a monitoring scheme, not
  drawn at random from what people eat, and the commodity mix changes by year.
* "Above MRL" is a regulatory-limit exceedance for a pesticide residue; it does
  not say a food was harmful.
* Not comparable across scopes: a part-year row (`Apr 2016–Jul 2016`) and a
  multi-year pool (`2014-19`) are stored as such and are not full fiscal years.
  `meat` (a 4-commodity answer) and `meat_egg` (an 11-commodity answer) are kept
  apart — the labels differ, so scope is not assumed even though the numbers
  coincide in 2014-15 and 2015-16.

## Three shapes, one rule

| Shape | Example | Support for a row |
|---|---|---|
| **table** — commodity rows × (analysed, above MRL) column pairs, one pair per period | LS16 Q3401 (11 commodities) | printed Total row equals the column sums (`total_row_sum`) |
| **text block** — one block per commodity, a row per fiscal year, then a printed total | LS16 Q1312 ("Details of vegetable samples analysed under MPRNL (2012-18)"), LS16 Q127 (Annexure II) | year rows sum to the printed Total / Grand Total (`total_row_sum`) |
| **sentence** — "During 2018-19; 29,410 samples … 863 (2.93 %) … above MRL" | LS17 Q3823, LS17 Q2630, LS16 Q1242 | only the printed percentage matches above/analysed (`pct_consistent`) — the weaker tier, labelled as such |

A block is accepted only if every check passes, otherwise rejected whole and
logged (`loksabha_question_log.reject_detail`):

| Check | Guards against |
|---|---|
| every count is one clean integer (`22 39` and `2239/40` are rejected, never read as 2,239) | fused cells |
| above ≤ analysed | column mix-up |
| a printed percentage must match above/analysed within one unit of its last digit | a misread digit (the answers both round and truncate: 98/6336 is printed 1.54, 863/29,410 is printed 2.93) |
| printed Total must equal the sum of the rows (tables and text blocks) | a missing or misread row |
| a period header must parse as a full year or a stated part-year, else reject | wrong-period attribution |
| the same (commodity, period) with **different** figures inside one answer → both blocks rejected | ambiguity (identical repeats are harmless) |
| a PDF must mention MPRNL / pesticide residues before it is parsed at all | parsing unrelated tables |

## Validation (2026-09-19, the six real answers in scope)

* **73 rows**: 33 from the table, 36 from text blocks, 4 sentences. Nothing was
  rejected. (The parser was written *after* reading these answers, so this shows
  it handles them — not that it generalises; a new layout will simply be
  rejected and logged.)
* **Cross-answer agreement.** 16 (commodity, period) cells are disclosed by more
  than one answer: **8 agree exactly, 8 conflict.** LS16 Q3401 (2016) and LS16
  Q1312 (2018) agree on all six cells they share (vegetables, fruits and spices
  for 2014-15 and 2015-16), and the two answers quoting the 2012-18 pool agree.
  **All 8 conflicts involve LS16 Q127 (December 2015), the earliest answer:** it
  differs from the later ones on the 2012-13 and 2013-14 figures of every
  commodity but meat-2013-14, and on spices 2014-15 (107 vs 106). Every
  disagreeing figure is internally consistent (its own percentage matches), so
  these are **revised vintages, not parse errors** — e.g. vegetables 2013-14
  above MRL is 221 (2015) vs 192 (2018); spices 2012-13 analysed is 388 vs 1,119.
  All are kept with their source; the API marks `single_source` /
  `corroborated` / `conflicting`. Which vintage is "right" is not decided here.
* The four commodities' rows in LS16 Q1312 sum to 86,810 of the 121,944 samples
  the same answer states for 2012-18; the rest are commodities it does not
  itemise.

## What the numbers show (and how far to trust the reading)

Full-year above-MRL rates in LS16 Q3401, the only source with all 11 commodities:

| Commodity | 2014-15 | 2015-16 |
|---|---|---|
| Spices | 106 / 1,299 = 8.2% | 86 / 1,390 = 6.2% |
| Rice | 68 / 1,076 = 6.3% | 45 / 1,128 = 4.0% |
| Vegetables | 306 / 10,593 = 2.9% | 329 / 12,035 = 2.7% |
| Tea | 4 / 174 = 2.3% | 8 / 181 = 4.4% |
| Wheat | 17 / 805 = 2.1% | 27 / 843 = 3.2% |
| Fruits | 40 / 2,239 = 1.8% | 27 / 2,364 = 1.1% |
| Pulses | 1 / 715 = 0.1% | 0 / 749 = 0% |
| Fish, meat/egg, milk, water (pooled) | 0 of 3,717 | 0 of 3,413 |

Spices and rice are consistently the highest; the aggregate is about 2.4–2.9%
in each year quoted. With samples this small per commodity (tea: 174), one year's
rate is noisy (tea moves 2.3% → 4.4% on 4 → 8 samples), so year-to-year changes
in small commodities should not be read as trends.

## Known limits

* **Six answers only; nothing after 2018-19.** The series stops where
  Parliament's disclosures stop. It is a stock of published figures, not a feed;
  most daily runs will insert nothing (`loksabha_pesticide` is in
  `EXPECTED_EMPTY_SOURCES`).
* **Which residue, which pesticide, which state** is not in any of these answers.
* **The weakest tier.** The four prose figures (`pct_consistent`) have no total to
  add up to; the printed percentage is their only check.
* **Layout coverage is narrow.** Three layouts are handled because those are the
  ones that exist in the answers found; every other pesticide answer either
  carries no numbers or is rejected and logged.
* Parser version is `pesticide-1`. Bump `PARSER_VERSION` when rules change: the
  runner re-processes questions logged under an older version, and re-processing
  replaces that question's rows in one transaction.

## Relevance to the model and the paper

* **Model:** with six years, a national commodity grain and no covariates, there
  is nothing to train. Its use is as *ground truth with a pass side* that a
  future commodity-level prior could be checked against, and as evidence for the
  contamination-relevant claim "some monitored commodities exceeded legal
  pesticide limits at a measurable rate" that the literature layer
  (`docs/RESEARCH_EVIDENCE_INGESTION.md`) alone cannot make.
* **Paper B (access audit):** another instance of the pattern in
  `docs/LOKSABHA_SAMPLING.md` — results the regulator does not publish in
  structured form are recoverable from Parliament, one PDF at a time, at
  national grain only, with later-revised vintages disagreeing with earlier ones.
