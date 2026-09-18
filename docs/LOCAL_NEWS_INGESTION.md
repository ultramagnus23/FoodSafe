# Local news ingestion — investigation & status

**Module:** `pipeline/sources/local_news.py`
**Run (standalone):** `python -m pipeline.sources.local_news --limit 20`
**Run (logged, matches other sources):** `python -m pipeline.run_and_log local_news --limit 20`
**Scheduled:** daily in `.github/workflows/ingest.yml` since 2026-09-18
(`continue-on-error`, in `EXPECTED_EMPTY_SOURCES`).

## 2026-09-18 update — extended to five metros

Originally Mumbai-only (see "Real test run" below). Extended to the four
other metros `localities` already has real, seeded neighbourhoods for
(Delhi, Bengaluru, Chennai, Pune — `schema_migration_010.sql`), via the
same Hindustan Times city-feed URL pattern, verified live to return
HTTP 200 for all four new slugs. `SOURCES` now has 6 entries (2 Mumbai +
1 each for the other four cities); `MUMBAI_LOCALITIES` was joined with
`DELHI_LOCALITIES`/`BENGALURU_LOCALITIES`/`CHENNAI_LOCALITIES`/
`PUNE_LOCALITIES` into `ALL_METRO_LOCALITIES` — every name copied
verbatim from `schema_migration_009.sql`/`010.sql`, not invented here, so
a keyword hit is always resolvable against a real seeded row.

**`source_type` changed from `'local_news_mumbai'` to a generic
`'local_news'`** (`schema_migration_017.sql` widens the CHECK constraint
to accept both — old Mumbai rows are left as `'local_news_mumbai'`, not
backfilled). Rationale: a per-city value would need a new migration every
time a city is added, and the geographic specificity already lives in
`district_id`/`locality_id` on the same row. The Maharashtra-only state
fallback (used only when NER extracts no state and no locality resolves)
is now looked up per-source via `_SOURCE_HOME_STATE`, so a Delhi article
with no NER state hit no longer silently gets tagged Maharashtra.

**Live dry-run the same day** (`fetch_records(limit=50)`, no DB write):
6/6 sources fetched successfully, 134 listing items seen across all five
cities, 3 passed the food-safety filter (2 Mumbai, 1 Pune — "FDA raids 14
establishments, suspends The New Poona Club's food licence"), 2 of those
3 named a real neighbourhood. Confirms the expansion works end-to-end,
not just in theory — real signal from a second city (Pune) on the first
pull.

## Why this source

`docs/FSSAI_INGESTION.md` and `docs/REACHABLE_TEXT_INVENTORY.md` found that
the OCR+NER pipeline works end-to-end but returns ~0 real structured hits
against *national* FSSAI press-clipping PDFs (277 empty-shell `RawRecord`s,
0 real field values across a 15-document sample) — because that corpus is
narrative news, not tabular test data. The hypothesis behind this module:
*local* city news, unlike national wire coverage, tends to actually name a
neighbourhood when reporting a food-safety incident. The app's geography
currently bottoms out at `districts` (e.g. "Mumbai") — there is no
locality/neighbourhood table yet (one, `localities`, is being added in a
parallel migration this session; this module does not touch it).

## Sources evaluated

| Candidate | Result | Notes |
| --- | --- | --- |
| **Hindustan Times — "Mumbai News" RSS** (`hindustantimes.com/feeds/rss/cities/mumbai-news/rssfeed.xml`) | **Used** | `robots.txt` disallows only `/intfeeds/`; `/feeds/*` is unrestricted. Feed returns ~8 recent items, static XML, no JS. Article pages are static HTML — body text sits in `<p class="content">`. |
| **Free Press Journal — Mumbai section listing** (`freepressjournal.in/mumbai`) | **Used** | `robots.txt` disallows `*/feed` (so FPJ's own RSS is out — we deliberately do not fetch it) but the plain listing page and `/mumbai/<slug>` article pages are not covered by any Disallow rule. Article body sits in `<article> <p>` tags, static HTML, no JS render needed. |
| Times of India (`timesofindia.indiatimes.com`) | **Rejected** | `robots.txt` disallows `/feeds/` outright, and `/rssarticleshow*`. No non-blocked way to list recent Mumbai articles was found. Not scraped. |
| Mumbai Mirror | **Rejected** | Now redirects into `timesofindia.indiatimes.com/city/mumbai` — same robots.txt, same exclusion. |

### robots.txt compliance mechanism

`local_news.py` does not just document compliance manually — `_robots_allows()`
fetches and parses each origin's `robots.txt` at runtime (via `urllib.robotparser`,
fed text fetched with the module's declared User-Agent) and gates every listing
and article fetch on `can_fetch()`. If a robots.txt fetch fails for any reason,
the code fails closed (`disallow_all = True`) rather than assuming access is fine.

One implementation snag worth recording: Python's `robotparser.read()` uses
urllib's *default*, UA-less opener internally. Free Press Journal's server
403s that default UA on `/robots.txt` itself, which makes `robotparser`
silently set `disallow_all = True` — i.e. it looked identical to "robots.txt
disallows everything" when the real cause was "the default urllib UA got
blocked fetching robots.txt." Fixed by fetching `robots.txt` manually with
the module's own `User-Agent` header and feeding the text to
`RobotFileParser.parse()` instead of calling `.read()`. Worth knowing if
future sources report spurious "blocked by robots.txt" results.

## What the module does

1. Fetch each source's listing (RSS or HTML), respecting robots.txt.
2. Keyword-filter titles/descriptions for food-safety relevance (`fda`,
   `fssai`, `food poisoning`, `adulterat*`, `contaminat*`, `raid`, `hygiene`,
   `food inspector`, etc. — see `FOOD_SAFETY_KEYWORDS` in the module).
3. Fetch the body of each relevant article (BeautifulSoup, per-source CSS
   selector), polite 1.5s delay between requests.
4. Run the article text through **the same NER engine the PDF path uses** —
   `pipeline.stage1_extract.FSSAINERExtractor`, imported directly, not
   forked — to pull whatever contaminant/product/date/state/district fields
   it can find.
5. Regex-match the text against a hardcoded list of real Mumbai
   neighbourhood names (`MUMBAI_LOCALITIES` — Juhu, Vile Parle, Chembur,
   Andheri, etc.) to flag which articles are locality-taggable once the
   `localities` migration lands. This is a plain keyword list, not the real
   `localities` table — that table doesn't exist here.
6. Wrap each accepted article as a `LocalNewsRecord` (a `stage1_extract.RawRecord`
   — same shape a PDF page produces, so it's structurally ready for
   `stage2_standardise`/`stage3_and_4` unchanged — plus the locality-name
   list as extra metadata `ingest()` uses for `locality_id` resolution).
7. `ingest()` resolves each `LocalNewsRecord` and writes it to
   `enforcement_records` (see "Database write path" below).

Because this is qualitative event text (like FoSCoS recalls or openFDA
advisories), `fetch_records()` accepts a *candidate* article once it passes
the keyword filter — NER is not required to find a contaminant/value to
keep the record. The database write in `ingest()` is stricter: a
contaminant match is required before a row is inserted, because
`enforcement_records.contaminant_id` is `NOT NULL` — there's no schema-legal
way to write a row without one. This mirrors fssai_recall.py's
`skipped_nomap` behaviour exactly.

## Locality-name resolution

`schema_migration_009.sql` added the `localities` table (real, geocoded
neighbourhoods, e.g. "Andheri West", "Andheri East", "Juhu") and a nullable
`locality_id` FK on `enforcement_records`. The plain-text neighbourhood
keywords `_find_localities()` extracts from article text (e.g. "Andheri")
don't match `localities.name_canonical` values exactly, because the seed
data includes directional suffixes the keyword list doesn't. Resolution
works like this (`pipeline/sources/local_news.py`):

- `_normalise_locality_key(name)` strips a trailing " West"/"East"/"North"/
  "South" and lowercases — `"Vile Parle West"` and `"Vile Parle East"` both
  normalise to `"vile parle"`.
- `build_locality_lookup(localities_rows)` builds a normalised-key ->
  `[(locality_id, parent_district_id), ...]` dict from whatever rows
  `SELECT id, name_canonical, parent_district_id FROM localities` returns.
  Nothing here is Mumbai-specific — it works unchanged as `localities`
  gains more cities (Delhi/Bengaluru/Chennai/Pune, seeded separately in
  `schema_migration_010.sql`).
- `resolve_locality_id(locality_names, lookup)` tries each of an article's
  matched keywords in turn and returns the first match's
  `(locality_id, parent_district_id)`. If a normalised key maps to more
  than one row (e.g. "andheri" -> both Andheri West and Andheri East), the
  lowest-id row is picked deterministically — a genuine ambiguity this
  keyword-based matcher can't resolve any further (the article text itself
  doesn't say which one).
- All three functions are pure (no DB connection) — `ingest()` fetches the
  `localities` rows once per run and passes the resulting lookup in. This
  is what `tests/test_local_news.py` exercises without a live database.

## Database write path

`ingest(conn, records)` (called by `run()`, which owns its own connection —
same pattern as `fssai_recall.py`) does, per `LocalNewsRecord`:

1. Match a contaminant against `contaminants.name_canonical`/`aliases` in
   the extracted `contaminant` field + article title. No match ->
   `skipped_no_contaminant`, nothing is written.
2. Build a dedup hash — `sha256(source_url + "|" + contaminant_id)` — and
   skip if it already exists in `enforcement_records.dedup_hash` (idempotent
   re-runs). This is a natural key deliberately narrower than
   `stage3_and_4.py`'s general cross-source hash: one article can only ever
   produce one `enforcement_records` row per contaminant it names, since
   there's no per-record lab/value/date precision to also key on.
3. Upsert a `commodities` row from the extracted product name (falls back
   to `"packaged food"`), same pattern as `openfda.py`/`fssai_recall.py`.
4. Resolve `locality_id` via `resolve_locality_id()`; if resolved, its
   `parent_district_id` is used directly for `district_id` (skipping the
   fuzzy district-name match, since the locality table's district FK is
   already authoritative). If no locality resolves, `district_id` falls
   back to `stage2_standardise.GeoStandardiser.resolve_district()` against
   the NER-extracted district text.
5. `test_date` comes from `stage2_standardise.DateStandardiser` parsing the
   NER-extracted date field, falling back to `date.today()` if unparseable
   or absent — the article's own publish date isn't currently threaded
   through to this function, so this is an honest approximation, not a
   claim of a real test date.
6. `raw_value_ppb` stays `0.0` (qualitative event, no lab reading) unless
   NER found both a value and a unit. `pass_fail` uses
   `stage2_standardise.normalise_pass_fail()` on the extracted pass/fail
   text, and is `None` (unknown) when nothing was extracted — this module
   does not force `FALSE` the way `fssai_recall.py` does for recalls, since
   a news article isn't inherently a "failure" record.
7. Inserted with `source_type='local_news_mumbai'`, `confidence_score=0.75`
   (`LOCAL_NEWS_CONFIDENCE` — clears `CONFIDENCE_MIN_USABLE` but set lower
   than `fssai_recall.py`'s 0.80 since this is our own scrape/keyword/NER
   chain, not an official government portal listing).

**Update 2026-09-18:** done — see "2026-09-18 update" above.
`source_type='local_news'` (generic) is what new rows write now, via
`schema_migration_017.sql`; the city is recoverable from
`locality_id`/`district_id` on the same row rather than baked into the
`source_type` string. Rows inserted before this migration keep their
original `'local_news_mumbai'` value.

## Real test run (2026-07-11, `--limit 20`)

```
sources_tried: 2
sources_blocked_by_robots: 0
listing_items_seen: 28        (8 from HT RSS, 20 from the FPJ Mumbai listing page)
food_safety_relevant: 1
articles_fetched_ok: 1
mentioned_a_locality: 1
ner_field_hits: 7
records_produced: 1
```

The one relevant article found in this run: **"Maharashtra FDA Bans Loose
Milk Sales; Only Sealed, Labelled Milk Can Be Sold Across State"**
(Free Press Journal, Mumbai). It genuinely confirms the hypothesis:

- **Named four real Mumbai neighbourhoods in body text**: Chembur, Andheri,
  Goregaon, Thane (quoting local milk retailers/residents by area) — exactly
  the kind of locality mention the national FSSAI clippings never contained.
- NER pulled real signal from this one, unlike the 277-record PDF sample:
  `contaminant = "Aflatoxin"`, `product_name = "Aflatoxin M1"`,
  `state = "Maharashtra"`, `district = "Mumbai"`, `date = "July 2026"`.
  (`brand` false-positived on the headline itself — spaCy's ORG tagger
  picked up "Maharashtra FDA Bans Loose Milk Sales" as an organisation name;
  a known weakness of the rule-based fallback noted in `stage1_extract.py`'s
  own docstring, not something this module introduced.)
- `value`/`unit`/`pass_fail` stayed `None` — the article states a policy
  change (a ban on loose milk), not a specific lab measurement, so there is
  honestly nothing there for those fields to extract. Expected, not a bug.

## Honest limitations

- **Yield is real but thin at this sample size**: 1 relevant article out of
  28 listing items in a single-page pull from each source. Both sources are
  un-paginated single fetches (RSS returns only ~8 latest items; the FPJ
  listing page shows one page of recent stories) — a production run would
  need to poll on a schedule and accumulate over days/weeks, the same way
  `agmarknet.py` already runs daily via `.github/workflows/ingest.yml`
  rather than expecting one large single pull.
- **Locality *extraction* (from article text) is still a hardcoded keyword
  list** (`MUMBAI_LOCALITIES`) — that part hasn't changed. What's new is
  that once a keyword is found, `resolve_locality_id()` now maps it to a
  real `locality_id` against the `localities` table (see "Locality-name
  resolution" above) instead of just being reported as a yield statistic.
  A locality-taggable article whose neighbourhood isn't in
  `MUMBAI_LOCALITIES` — or is in another city not yet in `localities` —
  still won't get a `locality_id`; it will still get an
  `enforcement_records` row (with `locality_id = NULL`), same as any other
  district-only record.
- **NER on narrative text is still narrative-NER**: it can and did produce a
  false-positive `brand` (the headline itself). This module does not clean
  that up beyond what `FSSAINERExtractor` already does — cleaning up the
  shared rule engine is out of scope here since it's shared with the PDF
  path.
- **Database write path** (`ingest()`, see above) uses `source_type='local_news'`
  (generic, `schema_migration_017.sql`) and the `locality_id` column. Wired
  into `pipeline/run_and_log.py` (`python -m pipeline.run_and_log
  local_news --limit N`), listed in `EXPECTED_EMPTY_SOURCES` there since a
  low row count is the documented, expected outcome at this sample size —
  a genuine regression would need to show up as an exception, not just a
  low row count — and now scheduled daily in `.github/workflows/ingest.yml`.
- **`test_date` is an approximation** (parsed NER date field, or
  `date.today()` if that fails) — the article's actual publish date isn't
  currently threaded from `Candidate.pub_date` into the record written to
  the DB. Worth tightening in a follow-up if `test_date` accuracy matters
  for this source's records specifically.
- Only two sources were validated end-to-end; other Mumbai-focused outlets
  (Mid-Day, DNA, Loksatta) were not checked and are an open item, not a
  claim of exhaustiveness.
