# Scientific evidence ingestion (OpenAlex + Europe PMC)

**What this is:** two connectors link each contaminant already in the
`contaminants` table to real, peer-reviewed literature about its health
effects, sharing one set of tables so the second source enriches the
first instead of duplicating it:

- `pipeline/sources/research_evidence.py` — [OpenAlex](https://openalex.org)
  works API, free, no API key, ~250M scholarly works with real DOIs,
  titles, authors, journals, abstracts, and concept tags.
- `pipeline/sources/europepmc_evidence.py` — [Europe PMC](https://europepmc.org)
  REST API, free, no API key, PubMed/PMC plus preprints and patents. Its
  value here isn't more volume, it's `pubTypeList`: a real per-work
  publication-type tag (Systematic Review, Meta-Analysis, Randomized
  Controlled Trial, Cohort Studies, Case Reports, ...) that OpenAlex's
  single `type` field (article/review) can't distinguish.

**Cross-dedup, not duplication:** Europe PMC looks up each candidate work
by DOI or PMID against `research_sources` before inserting. A match
found from an earlier OpenAlex pass is *enriched* — `study_design` filled
in from Europe PMC's real pubType tag, `pmcid` added, `source_apis` grows
to `{openalex, europepmc}` — never inserted as a second row. If that
richer classification turns out to be a systematic review or
meta-analysis that OpenAlex's coarser `type` field missed, the existing
`contaminant_research_links.evidence_level` is upgraded from `'C'` to
`'B'` — upgraded only, never downgraded, and never past `'B'`/`'C'` (see
below).

**What this is NOT:** a claim that a contaminant was found in any Indian
sample or product. It is a citation layer only — "peer-reviewed literature
associates X with Y" — kept in `research_sources` /
`contaminant_research_links` (`schema_migration_015.sql`,
`schema_migration_016.sql`), entirely separate from `enforcement_records`.
Nothing here feeds the risk scores in `models/aggregate.py` or
`models/disease_burden.py`.

## How a record is built

1. For each contaminant, query `GET api.openalex.org/works` with
   `search=<canonical name> health disease toxicity` and `filter=has_doi:true`.
2. Reconstruct the abstract from OpenAlex's `abstract_inverted_index`
   (word → positions; OpenAlex stores it this way to avoid redistributing
   publisher-copyrighted abstract text verbatim).
3. **Skip** — don't insert — any result missing a DOI, title, or
   reconstructable abstract. Verified live 2026-09-16: about 9 of 10
   results for "aflatoxin health disease" have abstracts; the rest are
   dropped, not backfilled with placeholder text.
4. Classify `evidence_level` from OpenAlex's own `type` field only:
   - `B` — `type == "review"`
   - `C` — anything else (the default for a normal peer-reviewed article)
   - `A` and `D` are never produced by this connector. `A` would require
     this project's own direct measurement; `D` (mechanistic/toxicology)
     would need full-text access to classify honestly, not just an
     abstract. Adding either later needs a human-reviewed process, not an
     automated guess.
5. Extract `matched_health_terms` from OpenAlex's own `concepts[]` list,
   keeping only concepts whose name contains a disease/health-outcome
   keyword (cancer, toxicity, syndrome, poisoning, etc. — see
   `HEALTH_TERM_KEYWORDS` in the connector). This is OpenAlex's existing
   tagging, filtered, not a new classification invented here.

Europe PMC (`europepmc_evidence.py`) runs the same per-contaminant search
against `GET ebi.ac.uk/europepmc/webservices/rest/search`
(`resultType=core`), strips the HTML/entities its abstracts and titles
carry (`<i>`, `<sub>`, `&lt;`, ...), and additionally:

- Classifies `study_design` from the work's real `pubTypeList` via an
  ordered keyword table (`_STUDY_DESIGN_RULES` in the connector) —
  `systematic_review`, `meta_analysis`, `randomized_trial`, `cohort`,
  `case_control`, `cross_sectional`, `case_report`, `clinical_trial`,
  `comparative_study`, `review`, `commentary`, or `unclassified` if only
  a generic "Journal Article" tag is present. This column has no `CHECK`
  constraint — Europe PMC's vocabulary is broad enough that a new
  legitimate pubType value shouldn't need a migration to record.
- Derives `evidence_level` from `study_design`: `'B'` only for
  `systematic_review`/`meta_analysis`, `'C'` otherwise — same two-value
  ceiling as OpenAlex, just triggered by a more specific, source-reported
  field.
- Extracts `matched_health_terms` from the work's real MeSH heading list
  (`meshHeadingList.meshHeading[].descriptorName`) when PubMed has
  indexed one, through the same keyword filter OpenAlex's concepts use.

## Idempotency

`research_sources.doi` is `UNIQUE`; `contaminant_research_links` is unique
on `(contaminant_id, research_source_id)`. Re-running the connector is
safe — matches every other source's `ON CONFLICT DO NOTHING` convention.

## Known limitations

- Abstract-only: no full-text extraction, so effect sizes, sample sizes,
  and study populations mentioned deep in a paper are not captured — only
  what OpenAlex's own metadata and abstract expose.
- Evidence-level classification is a two-value heuristic (review vs. not),
  not a systematic-review-quality assessment. It should be read as "source
  type," not "strength of evidence."
- Search relevance depends on OpenAlex's full-text search ranking, not a
  curated reading list — some results will be tangential. The API layer
  (`GET /v1/research`) surfaces exactly what was ingested, including any
  weak matches, so review by a human before treating any single result as
  authoritative.
- At ~1,860 papers, relevance dilutes further down each contaminant's
  ranking (limit=150 pulls deeper than the top-20 that was first
  validated). Volume is not quality — read counts as "sources retrieved,"
  not "sources vetted."
- Like every other connector, run via `python -m pipeline.run_and_log
  research_evidence --limit N`, which logs the run in `pipeline_runs`.

## API surface

- `GET /v1/research?contaminant_id=&q=&limit=&offset=` — paginated list
  (max 200/page). `q` is a case-insensitive title substring; LIKE wildcards
  (`%`, `_`) in `q` are escaped so they search for the literal character.
  One row per (contaminant, paper) link, so a paper tied to two
  contaminants appears twice — the frontend keys cards on both ids.
- `GET /v1/research/summary` — `total_papers` (distinct `research_sources`
  rows; the number to quote), `total_links`, and breakdowns by contaminant,
  study design and source API. Use this rather than counting `inserted`
  lines in run logs.
- Frontend `/research`: contaminant filter, debounced title search,
  pagination (20/page), and the summary line.

## Run

```bash
python -m pipeline.run_and_log research_evidence --limit 5     # OpenAlex, small local test
python -m pipeline.run_and_log europepmc_evidence --limit 5    # Europe PMC, small local test
```

Production (`.github/workflows/ingest.yml`) runs both at `--limit 150` — verified live against the real OpenAlex API at `per-page=200` (its documented max) returning ~150-165 usable (doi+title+abstract) rows per contaminant search term, so 150 has headroom without hitting the ceiling. Across the 9 seeded contaminants that's up to ~1,350 OpenAlex candidates plus Europe PMC's enrichment pass per run, comfortably past the 1,000-paper target — first run does the bulk load, later runs mostly re-hit the same top-relevance works and dedupe on `doi`, so growth converges rather than compounding daily.

Scheduled daily in `.github/workflows/ingest.yml` in that order, each
`continue-on-error: true` (supplementary literature layer, not core
enforcement data — a failure here should not block the rest of the
ingest run). Running Europe PMC before OpenAlex on a given day still
works correctly (dedup is by DOI/PMID lookup, not by run order) but
misses that day's enrichment opportunity for OpenAlex-only rows until
the next run.
