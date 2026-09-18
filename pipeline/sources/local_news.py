"""
FoodSafe India — Local News Ingester (locality-level event text)

Hypothesis under test: national FSSAI press-clipping PDFs are narrative and
yield ~zero structured fields (see docs/REACHABLE_TEXT_INVENTORY.md,
docs/FSSAI_INGESTION.md — 277 empty-shell RawRecords, 0 real hits). *Local*
news, unlike national coverage, tends to actually name a neighbourhood
when it reports a food-safety incident ("FDA raids restaurant in Vile
Parle"). Validated first against Mumbai alone (1/28 listing items relevant,
but that one article named 4 real neighbourhoods and yielded real NER
signal); now extended to the four other metros `localities` already covers
(Delhi, Bengaluru, Chennai, Pune — schema_migration_010.sql) via the same
Hindustan Times city-feed pattern, verified live to return HTTP 200 for
each. The app's finest geography today is `districts` (e.g. "Mumbai") —
there is no locality/neighbourhood table yet; one is being added in a
parallel migration (`localities`, pincode-linked, real Mumbai neighbourhoods)
elsewhere in this work session. This module does NOT touch the schema. It
produces locality-tagged text records now, ready to load once `locality_id`
exists on enforcement_records/consumer_reports.

Sources (both plain HTTP GET, no login/paywall/JS-render; robots.txt checked
programmatically before every fetch AND manually inspected — see
docs/LOCAL_NEWS_INGESTION.md for the full compliance table):

  - Hindustan Times, "Mumbai News" RSS feed
    https://www.hindustantimes.com/feeds/rss/cities/mumbai-news/rssfeed.xml
    robots.txt allows `/feeds/*` (only `/intfeeds/` is disallowed).
    Article body is static HTML: <p class="content">.

  - Free Press Journal, Mumbai section listing page
    https://www.freepressjournal.in/mumbai
    robots.txt allows `/mumbai` and `/mumbai/<slug>` article pages (it
    disallows `*/feed`, so we do NOT use FPJ's RSS feed — the HTML listing
    page itself is unrestricted, so we scrape that instead).
    Article body is static HTML: <article> <p>.

Candidates considered and rejected:
  - Times of India: robots.txt disallows `/feeds/` outright — RSS and the
    natural listing-page pattern both fall under paths TOI blocks. Skipped,
    not scraped.
  - Mumbai Mirror: folded into TOI's timesofindia.indiatimes.com/city/mumbai
    section as of this check — same robots.txt, same exclusion.

This module reuses (does not fork) the existing spaCy NER rule engine from
pipeline.stage1_extract.FSSAINERExtractor — the same class the PDF/OCR path
uses — pointed at article body text instead of OCR'd PDF text.

Honesty note: this is qualitative, event-level text (like FoSCoS recalls or
openFDA advisories), not lab ppb data. `fetch_records()` does not force a
contaminant/value match to accept a *candidate* record — an article that
clears the food-safety keyword filter is kept even if NER finds nothing
further. The database write path (`ingest()`), however, DOES require a
contaminant match before writing, same as fssai_recall.py's and openfda.py's
"skipped_no_contaminant" behaviour — `enforcement_records.contaminant_id` is
NOT NULL, so a record with no matchable contaminant genuinely cannot be
inserted, not just isn't a great candidate.

`schema_migration_009.sql` added `source_type='local_news_mumbai'` to
`enforcement_records`'s CHECK constraint and a nullable `locality_id` FK to
the new `localities` table, so this module now writes to the database:
`fetch_records()` fetches/filters/NER-extracts (unchanged), and `ingest()`
resolves each article's matched neighbourhood keyword(s) to a real
`locality_id` (via `resolve_locality_id()`, matched generically against
whatever `localities.name_canonical` rows exist — not hardcoded to Mumbai)
and upserts an `enforcement_records` row. See docs/LOCAL_NEWS_INGESTION.md
for the full write-path description and current limitations.

Run:  python -m pipeline.sources.local_news --limit 20
      python -m pipeline.run_and_log local_news --limit 20
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import psycopg2
from bs4 import BeautifulSoup

from pipeline.config import pg_connect
from pipeline.stage1_extract import FSSAINERExtractor, RawRecord
from pipeline.stage2_standardise import DateStandardiser, GeoStandardiser, UnitConverter, normalise_pass_fail

logger = logging.getLogger("foodsafe.local_news")

USER_AGENT = "FoodSafe-India/1.0 (+local-news research ingester)"
REQUEST_DELAY_S = 1.5   # be polite between article fetches
REQUEST_TIMEOUT_S = 20

# ------------------------------------------------------------
# Source registry
# ------------------------------------------------------------

SOURCES = [
    {
        "name": "hindustan_times_mumbai",
        "kind": "rss",
        "listing_url": "https://www.hindustantimes.com/feeds/rss/cities/mumbai-news/rssfeed.xml",
        "body_selector": ("p.content", None),   # (css selector, container selector)
        "home_state": "Maharashtra",
    },
    {
        "name": "free_press_journal_mumbai",
        "kind": "html_listing",
        "listing_url": "https://www.freepressjournal.in/mumbai",
        "link_pattern": re.compile(r"^https://www\.freepressjournal\.in/mumbai/[a-z0-9-]+$"),
        "body_selector": ("article p", None),
        "home_state": "Maharashtra",
    },
    # Same Hindustan Times city-feed pattern as Mumbai, verified live to
    # return HTTP 200 for each of these four slugs. robots.txt is checked
    # per-URL at fetch time by _robots_allows() regardless of city — the
    # site's rule (`/feeds/*` allowed, only `/intfeeds/` disallowed) is
    # domain-wide, not path-specific, so nothing city-specific needed
    # re-verifying here. These are the same four metros
    # schema_migration_010.sql already seeds real `localities` rows for,
    # via schema_reference_districts.sql's reference district rows.
    {
        "name": "hindustan_times_delhi",
        "kind": "rss",
        "listing_url": "https://www.hindustantimes.com/feeds/rss/cities/delhi-news/rssfeed.xml",
        "body_selector": ("p.content", None),
        "home_state": "Delhi",
    },
    {
        "name": "hindustan_times_bengaluru",
        "kind": "rss",
        "listing_url": "https://www.hindustantimes.com/feeds/rss/cities/bengaluru-news/rssfeed.xml",
        "body_selector": ("p.content", None),
        "home_state": "Karnataka",
    },
    {
        "name": "hindustan_times_chennai",
        "kind": "rss",
        "listing_url": "https://www.hindustantimes.com/feeds/rss/cities/chennai-news/rssfeed.xml",
        "body_selector": ("p.content", None),
        "home_state": "Tamil Nadu",
    },
    {
        "name": "hindustan_times_pune",
        "kind": "rss",
        "listing_url": "https://www.hindustantimes.com/feeds/rss/cities/pune-news/rssfeed.xml",
        "body_selector": ("p.content", None),
        "home_state": "Maharashtra",
    },
]

# Real neighbourhood names for all five metros this module now covers. This
# is a plain keyword list, NOT the `localities` table — it exists only so
# _find_localities() can flag candidate neighbourhood mentions in article
# text; resolve_locality_id() does the real resolution against whatever
# `localities` rows actually exist in the DB. Every name below is copied
# verbatim from schema_migration_009.sql (Mumbai) / schema_migration_010.sql
# (Delhi, Bengaluru, Chennai, Pune) — not invented here, so a keyword hit is
# guaranteed resolvable against a real seeded row.
MUMBAI_LOCALITIES = [
    "Juhu", "Vile Parle", "Andheri", "Bandra", "Khar", "Santacruz",
    "Churchgate", "Colaba", "Fort", "Marine Lines", "Charni Road",
    "Girgaon", "Malabar Hill", "Grant Road", "Byculla", "Mazgaon",
    "Wadala", "Dadar", "Matunga", "Sion", "Parel", "Lower Parel", "Worli",
    "Chembur", "Ghatkopar", "Vikhroli", "Bhandup", "Mulund", "Kurla",
    "Powai", "Vidyavihar", "Kandivali", "Kandivli", "Borivali", "Borivli",
    "Malad", "Goregaon", "Jogeshwari", "Oshiwara", "Versova",
    "Dahisar", "Mira Road", "Thane", "Vashi", "Navi Mumbai", "Panvel",
    "Kalyan", "Dombivli", "Bhayandar",
]
DELHI_LOCALITIES = [
    "Connaught Place", "Karol Bagh", "Chandni Chowk", "Hauz Khas", "Saket",
    "Vasant Kunj", "Dwarka", "Rohini", "Lajpat Nagar", "Greater Kailash",
    "Rajouri Garden", "Pitampura", "Janakpuri", "Mayur Vihar",
]
BENGALURU_LOCALITIES = [
    "Koramangala", "Indiranagar", "Whitefield", "Jayanagar", "Malleshwaram",
    "Rajajinagar", "HSR Layout", "Electronic City", "Marathahalli",
    "Basavanagudi", "Yelahanka", "JP Nagar", "Banashankari",
]
CHENNAI_LOCALITIES = [
    "T Nagar", "Anna Nagar", "Adyar", "Mylapore", "Velachery",
    "Nungambakkam", "Besant Nagar", "Egmore", "Guindy", "Tambaram",
    "Porur", "Kilpauk", "Perambur",
]
PUNE_LOCALITIES = [
    "Koregaon Park", "Shivajinagar", "Kothrud", "Viman Nagar", "Aundh",
    "Baner", "Hadapsar", "Deccan Gymkhana", "Wakad", "Katraj", "Kondhwa",
    "Yerawada", "Sinhagad Road",
]
ALL_METRO_LOCALITIES = (
    MUMBAI_LOCALITIES + DELHI_LOCALITIES + BENGALURU_LOCALITIES
    + CHENNAI_LOCALITIES + PUNE_LOCALITIES
)
LOCALITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in ALL_METRO_LOCALITIES) + r")\b"
)

_SOURCE_HOME_STATE = {cfg["name"]: cfg["home_state"] for cfg in SOURCES}

# Keyword filter: article title/description must hit at least one of these
# to be considered food-safety relevant.
FOOD_SAFETY_KEYWORDS = [
    "fda", "fssai", "food poisoning", "food-poisoning", "adulterat",
    "contaminat", "food safety", "unhygienic", "hygiene", "raid",
    "food inspector", "expired food", "stale food", "rotten food",
    "licence cancelled", "license cancelled", "license suspended",
    "licence suspended", "sealed restaurant", "eatery sealed",
    "shut down restaurant", "food joint", "restaurant raid",
]
_KEYWORD_RE = re.compile("|".join(re.escape(k) for k in FOOD_SAFETY_KEYWORDS), re.IGNORECASE)


# ------------------------------------------------------------
# robots.txt compliance
# ------------------------------------------------------------

_robots_cache: dict[str, robotparser.RobotFileParser] = {}


def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        robots_url = urljoin(origin, "/robots.txt")
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        # RobotFileParser.read() uses urllib's default (UA-less) opener,
        # which several news sites 403 outright — that made read() silently
        # set disallow_all=True (fail-closed on a 403, not a real robots
        # rule). Fetch with our declared User-Agent instead, same as every
        # other request this module makes, then hand robotparser the text.
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            rp.parse(text.splitlines())
        except Exception as e:  # noqa: BLE001
            logger.warning("could not fetch robots.txt for %s (%s) — refusing to crawl", origin, e)
            rp.disallow_all = True
        _robots_cache[origin] = rp
    return rp.can_fetch(USER_AGENT, url)


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def _fetch(url: str) -> Optional[str]:
    if not _robots_allows(url):
        logger.warning("robots.txt disallows fetching %s — skipping", url)
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %s fetching %s", e.code, url)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch failed for %s: %s", url, e)
    return None


# ------------------------------------------------------------
# Listing parsers
# ------------------------------------------------------------

@dataclass
class Candidate:
    title: str
    link: str
    summary: str
    pub_date: Optional[str]
    source_name: str


def _parse_rss_listing(xml_text: str, source_name: str) -> list[Candidate]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error("RSS parse error for %s: %s", source_name, e)
        return out
    for item in root.findall(".//item"):
        def tag(name: str) -> str:
            el = item.find(name)
            return (el.text or "").strip() if el is not None else ""
        out.append(Candidate(
            title=tag("title"),
            link=tag("link"),
            summary=tag("description"),
            pub_date=tag("pubDate") or None,
            source_name=source_name,
        ))
    return out


def _parse_html_listing(html_text: str, source_cfg: dict) -> list[Candidate]:
    soup = BeautifulSoup(html_text, "lxml")
    pattern = source_cfg["link_pattern"]
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if not pattern.match(href) or href in seen:
            continue
        seen.add(href)
        title = a.get_text(strip=True)
        if not title:
            continue
        out.append(Candidate(title=title, link=href, summary="", pub_date=None,
                              source_name=source_cfg["name"]))
    return out


def _list_candidates(source_cfg: dict) -> list[Candidate]:
    html_or_xml = _fetch(source_cfg["listing_url"])
    if html_or_xml is None:
        return []
    if source_cfg["kind"] == "rss":
        return _parse_rss_listing(html_or_xml, source_cfg["name"])
    return _parse_html_listing(html_or_xml, source_cfg)


# ------------------------------------------------------------
# Relevance filter + article body extraction
# ------------------------------------------------------------

def _is_relevant(candidate: Candidate) -> bool:
    return bool(_KEYWORD_RE.search(f"{candidate.title} {candidate.summary}"))


def _extract_body(html_text: str, source_cfg: dict) -> str:
    soup = BeautifulSoup(html_text, "lxml")
    selector, _ = source_cfg["body_selector"]
    paras = soup.select(selector)
    return "\n".join(p.get_text(" ", strip=True) for p in paras)


def _find_localities(text: str) -> list[str]:
    hits = LOCALITY_PATTERN.findall(text)
    # de-dupe, preserve first-seen order, normalise casing variants
    seen: list[str] = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    return seen


# ------------------------------------------------------------
# Record shape
# ------------------------------------------------------------

@dataclass
class LocalNewsRecord:
    """RawRecord plus locality metadata the DB can't hold yet.

    `raw` is a stage1_extract.RawRecord — unchanged shape, so once this
    source is wired up it flows into stage2_standardise/stage3_and_4 exactly
    like a PDF-derived record. `locality_names` is extra, forward-looking
    metadata for the `locality_id` column landing in a parallel migration;
    it is not persisted anywhere today.
    """
    raw: RawRecord
    title: str
    source_name: str = ""
    locality_names: list[str] = field(default_factory=list)


# ------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------

def fetch_records(limit: int = 20) -> tuple[list[LocalNewsRecord], dict]:
    """Fetch, filter, and NER-extract local Mumbai food-safety news.

    Returns (records, stats). Does not touch the database — see module
    docstring / docs/LOCAL_NEWS_INGESTION.md for why.
    """
    ner = FSSAINERExtractor()
    stats = {
        "sources_tried": 0,
        "sources_blocked_by_robots": 0,
        "listing_items_seen": 0,
        "food_safety_relevant": 0,
        "articles_fetched_ok": 0,
        "mentioned_a_locality": 0,
        "ner_field_hits": 0,
        "records_produced": 0,
    }
    records: list[LocalNewsRecord] = []

    for source_cfg in SOURCES:
        stats["sources_tried"] += 1
        if not _robots_allows(source_cfg["listing_url"]):
            stats["sources_blocked_by_robots"] += 1
            logger.warning("%s listing blocked by robots.txt — skipping source", source_cfg["name"])
            continue

        candidates = _list_candidates(source_cfg)
        stats["listing_items_seen"] += len(candidates)
        relevant = [c for c in candidates if _is_relevant(c)]
        stats["food_safety_relevant"] += len(relevant)

        for cand in relevant:
            if len(records) >= limit:
                break
            body_html = _fetch(cand.link)
            if body_html is None:
                continue
            stats["articles_fetched_ok"] += 1
            time.sleep(REQUEST_DELAY_S)

            body_text = _extract_body(body_html, source_cfg)
            full_text = f"{cand.title}\n{cand.summary}\n{body_text}"
            if not body_text.strip():
                logger.info("no body text extracted for %s (selector may need adjustment)", cand.link)

            localities = _find_localities(full_text)
            if localities:
                stats["mentioned_a_locality"] += 1

            fields = ner.extract(full_text, ocr_confidence=1.0, source="html")
            stats["ner_field_hits"] += sum(1 for v in fields.values() if v is not None)

            rec = RawRecord(
                source_url=cand.link,
                source_type="local_news",
                date=fields["date"],
                product_name=fields["product_name"],
                brand=fields["brand"],
                contaminant=fields["contaminant"],
                value=fields["value"],
                unit=fields["unit"],
                state=fields["state"] or None,
                district=fields["district"],
                pass_fail=fields["pass_fail"],
                page_ocr_confidence=1.0,
            )
            records.append(LocalNewsRecord(
                raw=rec, title=cand.title, source_name=source_cfg["name"], locality_names=localities,
            ))
            stats["records_produced"] += 1

        if len(records) >= limit:
            break

    return records, stats


# ------------------------------------------------------------
# Locality-name resolution
# ------------------------------------------------------------
#
# `MUMBAI_LOCALITIES`/`_find_localities()` above extract plain-text
# neighbourhood *keywords* from an article ("Andheri", "Vile Parle"). The
# `localities` table (schema_migration_009.sql) instead stores real,
# geocoded rows like "Andheri West" / "Andheri East" / "Vile Parle West".
# The functions below resolve a keyword to a `locality_id` generically —
# by normalising away directional suffixes and matching whatever rows
# `localities` actually has — so this keeps working unchanged as the
# table grows beyond Mumbai (parallel `localities` seed-extension work in
# this session adds Delhi/Bengaluru/Chennai/Pune). Pure functions: they
# take an already-fetched `localities` row list / a pre-built lookup dict,
# so they're testable without a live DB connection.

_DIRECTIONAL_SUFFIX_RE = re.compile(r"\s+(west|east|north|south)$", re.IGNORECASE)


def _normalise_locality_key(name: str) -> str:
    """'Vile Parle West' -> 'vile parle'; 'Juhu' -> 'juhu'."""
    return _DIRECTIONAL_SUFFIX_RE.sub("", name.strip().lower())


def build_locality_lookup(
    localities: list[tuple[int, str, int]],
) -> dict[str, list[tuple[int, int]]]:
    """localities: (id, name_canonical, parent_district_id) rows.

    Returns normalised-name -> [(locality_id, parent_district_id), ...].
    A normalised key can map to more than one row (e.g. 'andheri' maps to
    both 'Andheri West' and 'Andheri East') — genuine ambiguity a plain
    keyword can't resolve further; callers pick deterministically.
    """
    lookup: dict[str, list[tuple[int, int]]] = {}
    for lid, name, district_id in localities:
        lookup.setdefault(_normalise_locality_key(name), []).append((lid, district_id))
    return lookup


def resolve_locality_id(
    locality_names: list[str],
    lookup: dict[str, list[tuple[int, int]]],
) -> Optional[tuple[int, int]]:
    """Resolve the first matched article keyword to (locality_id, district_id).

    Returns None if none of `locality_names` matches a row in `lookup`
    (e.g. the neighbourhood isn't seeded yet, or the article is outside
    any city `localities` currently covers).
    """
    for kw in locality_names:
        candidates = lookup.get(_normalise_locality_key(kw))
        if candidates:
            return sorted(candidates)[0]   # lowest id = deterministic pick
    return None


def _load_localities(conn) -> list[tuple[int, str, int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical, parent_district_id FROM localities")
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


# ------------------------------------------------------------
# Database write path
# ------------------------------------------------------------
#
# Mirrors fssai_recall.py's precedent for narrative/qualitative event data:
# contaminant match is required before writing (enforcement_records.
# contaminant_id is NOT NULL — there's no schema-legal way around this),
# commodity is upserted from whatever product text NER found, and dedup is
# a hash over natural keys rather than relying on stage3_and_4's full
# cross-record hash (article URL + contaminant is a good enough natural
# key for one article -> at most one enforcement_records row).

def _load_contaminants(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical, aliases, legal_limit_ppb_fssai FROM contaminants")
        return [(r[0], r[1], (r[2] or []), r[3]) for r in cur.fetchall()]


def _match_contaminant(text: str, contaminants):
    low = (text or "").lower()
    for cid, canonical, aliases, limit in contaminants:
        needles = [canonical.replace("_", " "), canonical.split("_")[0]] + [a.lower() for a in aliases]
        if any(n and n in low for n in needles):
            return cid, (float(limit) if limit is not None else None)
    return None


def _upsert_commodity(conn, product_desc: str) -> Optional[int]:
    name = re.sub(r"[^a-z0-9 ]", "", (product_desc or "").lower()).strip()[:60] or "packaged food"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO commodities (name_canonical, category) VALUES (%s, 'packaged') "
            "ON CONFLICT (name_canonical) DO NOTHING RETURNING id",
            (name,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM commodities WHERE name_canonical = %s", (name,))
        row = cur.fetchone()
        return row[0] if row else None


# Narrative news is a step further removed than an official FoSCoS recall
# listing (fssai_recall.py uses 0.80) — our own scrape/keyword-filter/NER
# chain, not a government portal — so start slightly lower. Still clears
# CONFIDENCE_MIN_USABLE (0.75).
LOCAL_NEWS_CONFIDENCE = 0.75


def ingest(conn, records: list[LocalNewsRecord]) -> dict:
    """Resolve locality + contaminant and upsert into enforcement_records.

    Idempotent: dedups on sha256(source_url + '|' + contaminant_id), same
    style as fssai_recall.py's dedup_hash — a URL can only ever map to one
    (contaminant, locality) enforcement_records row from this source.
    """
    contaminants = _load_contaminants(conn)
    locality_lookup = build_locality_lookup(_load_localities(conn))
    date_std = DateStandardiser()
    unit_conv = UnitConverter()
    geo = GeoStandardiser(conn)

    summary = {
        "records_in": len(records),
        "matched_contaminant": 0,
        "locality_resolved": 0,
        "inserted": 0,
        "skipped_dupe": 0,
        "skipped_no_contaminant": 0,
    }

    for rec in records:
        raw = rec.raw
        contaminant_text = f"{raw.contaminant.value if raw.contaminant else ''} {rec.title}"
        match = _match_contaminant(contaminant_text, contaminants)
        if not match:
            summary["skipped_no_contaminant"] += 1
            continue
        contaminant_id, legal_limit = match
        summary["matched_contaminant"] += 1

        dedup_hash = "local-news-" + hashlib.sha256(
            f"{raw.source_url}|{contaminant_id}".encode()
        ).hexdigest()[:40]
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM enforcement_records WHERE dedup_hash=%s LIMIT 1", (dedup_hash,))
            if cur.fetchone():
                summary["skipped_dupe"] += 1
                continue

        commodity_id = _upsert_commodity(conn, raw.product_name.value if raw.product_name else "")
        if commodity_id is None:
            summary["skipped_no_contaminant"] += 1
            continue

        loc_match = resolve_locality_id(rec.locality_names, locality_lookup)
        locality_id: Optional[int] = None
        district_id: Optional[int] = None
        if loc_match:
            locality_id, district_id = loc_match
            summary["locality_resolved"] += 1

        home_state = _SOURCE_HOME_STATE.get(rec.source_name, "Maharashtra")
        state_canonical = geo.standardise_state(raw.state.value if raw.state else None) or home_state
        if district_id is None:
            district_id, _ = geo.resolve_district(
                raw.district.value if raw.district else None, state_canonical
            )

        test_date, _ = date_std.standardise(raw.date.value if raw.date else "")
        test_date = test_date or date.today()

        value_ppb = 0.0
        if raw.value and raw.unit:
            value_ppb = unit_conv.convert(raw.value.value, raw.unit.value) or 0.0

        pass_fail = normalise_pass_fail(raw.pass_fail.value if raw.pass_fail else None)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO enforcement_records (
                            test_date, source_url, source_type, commodity_id, contaminant_id,
                            raw_value_ppb, legal_limit_ppb, pass_fail, state, district_id,
                            locality_id, confidence_score, dedup_hash, is_duplicate,
                            etl_version, parsed_at
                        ) VALUES (%s,%s,'local_news',%s,%s,%s,%s,%s,%s,%s,
                                  %s,%s,%s,FALSE,'local-news-1.1',NOW())""",
                    (
                        test_date, raw.source_url, commodity_id, contaminant_id,
                        value_ppb, legal_limit, pass_fail, state_canonical, district_id,
                        locality_id, LOCAL_NEWS_CONFIDENCE, dedup_hash,
                    ),
                )
            summary["inserted"] += 1
        except psycopg2.Error as e:
            logger.error("insert failed for %s: %s", raw.source_url, e)
            conn.rollback()

    conn.commit()
    return summary


def run(limit: int = 20) -> dict:
    records, fetch_stats = fetch_records(limit=limit)
    for r in records[:5]:
        logger.info("sample: %-60s localities=%s", r.title[:60], r.locality_names)

    conn = pg_connect()
    try:
        ingest_stats = ingest(conn, records)
    finally:
        conn.close()

    return {**fetch_stats, **ingest_stats}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description="Fetch + filter + NER-extract + ingest Mumbai local food-safety news")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    summary = run(limit=args.limit)
    print("\n=== LOCAL NEWS (MUMBAI) INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
