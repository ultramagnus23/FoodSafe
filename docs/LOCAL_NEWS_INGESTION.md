# Local Mumbai news ingestion — investigation & status

**Module:** `pipeline/sources/local_news.py`
**Run:** `python -m pipeline.sources.local_news --limit 20`

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
   list as forward-looking metadata).

Because this is qualitative event text (like FoSCoS recalls or openFDA
advisories), an article is accepted once it passes the keyword filter —
NER is not required to find a contaminant/value to keep the record.

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
- **Locality extraction is a hardcoded keyword list**, not a linked table —
  it does not resolve to a `locality_id` or pincode; that mapping has to
  happen once the real `localities` table lands.
- **NER on narrative text is still narrative-NER**: it can and did produce a
  false-positive `brand` (the headline itself). This module does not clean
  that up beyond what `FSSAINERExtractor` already does — cleaning up the
  shared rule engine is out of scope here since it's shared with the PDF
  path.
- **No database write**: `enforcement_records.source_type` CHECK constraint
  is `('fssai','usfda','efsa','apeda','state_health','agmarknet')` — it does
  not include a local-news value, and no table has a `locality_id` column
  yet. Per the task scope, this module does not modify the schema and is
  not wired into `.github/workflows/ingest.yml`. `run()` fetches, filters,
  extracts, and reports yield only; `fetch_records()` returns the
  `LocalNewsRecord` list in-process for whoever wires up the DB write once
  the locality migration and a `source_type` value for this source both
  exist.
- Only two sources were validated end-to-end; other Mumbai-focused outlets
  (Mid-Day, DNA, Loksatta) were not checked and are an open item, not a
  claim of exhaustiveness.
