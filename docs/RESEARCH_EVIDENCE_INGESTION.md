# Scientific evidence ingestion (OpenAlex)

**What this is:** `pipeline/sources/research_evidence.py` links each
contaminant already in the `contaminants` table to real, peer-reviewed
literature about its health effects, using the
[OpenAlex](https://openalex.org) works API — free, no API key, ~250M
scholarly works with real DOIs, titles, authors, journals, abstracts, and
concept tags.

**What this is NOT:** a claim that a contaminant was found in any Indian
sample or product. It is a citation layer only — "peer-reviewed literature
associates X with Y" — kept in `research_sources` /
`contaminant_research_links` (`schema_migration_015.sql`), entirely
separate from `enforcement_records`. Nothing here feeds the risk scores in
`models/aggregate.py` or `models/disease_burden.py`.

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
- Like every other connector, run via `python -m pipeline.run_and_log
  research_evidence --limit N`, which logs the run in `pipeline_runs`.

## Run

```bash
python -m pipeline.run_and_log research_evidence --limit 5
```

Scheduled daily in `.github/workflows/ingest.yml`, `continue-on-error:
true` (supplementary literature layer, not core enforcement data — a
failure here should not block the rest of the ingest run).
