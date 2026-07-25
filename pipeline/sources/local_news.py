"""
FoodSafe India — Local Mumbai News Ingester (locality-level event text)

Hypothesis under test: national FSSAI press-clipping PDFs are narrative and
yield ~zero structured fields (see docs/REACHABLE_TEXT_INVENTORY.md,
docs/FSSAI_INGESTION.md — 277 empty-shell RawRecords, 0 real hits). *Local*
Mumbai news, unlike national coverage, tends to actually name a neighbourhood
when it reports a food-safety incident ("FDA raids restaurant in Vile
Parle"). The app's finest geography today is `districts` (e.g. "Mumbai") —
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
openFDA advisories), not lab ppb data. We do not force a contaminant/value
match to accept a record — an article that clears the food-safety keyword
filter is kept even if NER finds nothing further, same as fssai_recall.py's
"qualitative event" treatment. Because `source_type` CHECK on
enforcement_records does not yet include a local-news value and
`locality_id` does not exist on any table, this module intentionally does
NOT write to the database — see docs/LOCAL_NEWS_INGESTION.md. It fetches,
filters, extracts and reports yield only, standalone.

Run:  python -m pipeline.sources.local_news --limit 20
"""

from __future__ import annotations

import argparse
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
from urllib import robotparser
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from pipeline.stage1_extract import FSSAINERExtractor, RawRecord

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
    },
    {
        "name": "free_press_journal_mumbai",
        "kind": "html_listing",
        "listing_url": "https://www.freepressjournal.in/mumbai",
        "link_pattern": re.compile(r"^https://www\.freepressjournal\.in/mumbai/[a-z0-9-]+$"),
        "body_selector": ("article p", None),
    },
]

# Real Mumbai-area neighbourhood names. This is a plain keyword list, NOT the
# `localities` table (that migration is being done elsewhere in this work
# session) — it exists here only so this module can flag which articles
# would be locality-taggable once that table lands.
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
LOCALITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in MUMBAI_LOCALITIES) + r")\b"
)

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
                source_type="local_news_mumbai",
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
            records.append(LocalNewsRecord(raw=rec, title=cand.title, locality_names=localities))
            stats["records_produced"] += 1

        if len(records) >= limit:
            break

    return records, stats


def run(limit: int = 20) -> dict:
    records, stats = fetch_records(limit=limit)
    stats["note"] = (
        "no DB write performed — source_type='local_news_mumbai' is not in "
        "enforcement_records' source_type CHECK constraint and locality_id "
        "does not exist on any table yet; wire up once the locality "
        "migration lands (see docs/LOCAL_NEWS_INGESTION.md)"
    )
    for r in records[:5]:
        logger.info("sample: %-60s localities=%s", r.title[:60], r.locality_names)
    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description="Fetch + filter + NER-extract Mumbai local food-safety news")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    summary = run(limit=args.limit)
    print("\n=== LOCAL NEWS (MUMBAI) INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
