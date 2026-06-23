"""
FoodSafe India — FSSAI Source Scraper
Scrapes: enforcement reports, recall notices, lab test results
Site: https://fssai.gov.in

Strategy:
  - Scrape listing pages for new PDF links
  - Download PDFs to S3 (raw/) and local cache
  - Track already-downloaded URLs in DB to avoid re-processing
  - Respect FSSAI_SCRAPE_DELAY_S between requests
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import boto3
import httpx
from bs4 import BeautifulSoup

from pipeline.config import (
    FSSAI_SCRAPE_DELAY_S,
    RAW_DIR,
    S3_BUCKET,
    S3_REGION,
)

logger = logging.getLogger(__name__)

# ============================================================
# FSSAI LISTING PAGES
#
# NOTE (2026-06): the old cms/enforcement-reports.php, recall-notices.php,
# lab-test-results.php and food-safety-mitra-reports.php URLs now 302-redirect
# to the homepage — FSSAI restructured the site. The current reachable pages
# are below. See docs/FSSAI_INGESTION.md for the full investigation: the
# food-recall data is JS-rendered (not in the static HTML / not PDFs) and the
# "report" PDFs are news clippings, so this scraper currently yields little
# structured enforcement data. It is kept functional against live URLs; the
# remaining work (trained NER model, headless render for recalls) is documented.
# ============================================================

FSSAI_PAGES = {
    "food_recall":         "https://fssai.gov.in/cms/food-recall.php",
    "food_recall_archive": "https://fssai.gov.in/cms/food-recall-archive.php",
    "food_testing":        "https://fssai.gov.in/index.php?page=food-testing.php",
}

# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class PDFLink:
    url: str
    title: str
    source_type: str        # "fssai"
    page_type: str          # "enforcement_reports" | "recall_notices" | ...
    discovered_at: datetime
    state_hint: Optional[str] = None   # extracted from title if possible


@dataclass
class DownloadedFile:
    pdf_link: PDFLink
    local_path: Optional[Path]
    s3_key: Optional[str]
    file_size_bytes: int
    download_ok: bool
    error: Optional[str] = None


# ============================================================
# HTTP CLIENT (shared, with retry + rate limiting)
# ============================================================

class RateLimitedClient:
    """httpx client with automatic rate limiting and retry."""

    def __init__(self, delay_s: float = FSSAI_SCRAPE_DELAY_S, max_retries: int = 3):
        self.delay_s     = delay_s
        self.max_retries = max_retries
        self._last_call  = 0.0
        self._client     = httpx.Client(
            timeout=30,
            headers={
                "User-Agent": (
                    "FoodSafe India Data Pipeline / research@foodsafe.in "
                    "(public food safety data collection)"
                ),
            },
            follow_redirects=True,
        )

    def get(self, url: str, **kwargs) -> httpx.Response:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.get(url, **kwargs)
                self._last_call = time.monotonic()
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 60 * attempt
                    logger.warning("Rate limited on %s — waiting %ds", url, wait)
                    time.sleep(wait)
                elif e.response.status_code >= 500:
                    logger.warning("Server error %d on %s (attempt %d/%d)",
                                   e.response.status_code, url, attempt, self.max_retries)
                    time.sleep(5 * attempt)
                else:
                    raise
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("Network error on %s (attempt %d/%d): %s", url, attempt, self.max_retries, e)
                time.sleep(5 * attempt)

        raise RuntimeError(f"Failed to GET {url} after {self.max_retries} attempts")

    def close(self):
        self._client.close()


# ============================================================
# LINK DISCOVERER
# ============================================================

class FSSAILinkDiscoverer:
    """
    Scrapes FSSAI listing pages and extracts PDF links.
    Handles pagination (FSSAI uses ?page=N query params).
    """

    MAX_PAGES = 50   # safety limit

    def __init__(self, client: RateLimitedClient):
        self.client = client

    def discover(self, page_type: str, max_pages: int = MAX_PAGES) -> list[PDFLink]:
        base_url = FSSAI_PAGES[page_type]
        all_links: list[PDFLink] = []
        seen_urls: set[str] = set()

        for page_num in range(1, max_pages + 1):
            url = f"{base_url}?page={page_num}" if page_num > 1 else base_url
            logger.info("Discovering %s — page %d", page_type, page_num)

            try:
                resp = self.client.get(url)
            except RuntimeError as e:
                logger.error("Failed to fetch listing page: %s", e)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            pdf_links = self._extract_pdf_links(soup, base_url, page_type)

            if not pdf_links:
                logger.info("No PDF links on page %d — stopping pagination", page_num)
                break

            new_links = [l for l in pdf_links if l.url not in seen_urls]
            if not new_links:
                logger.info("No new links on page %d — stopping", page_num)
                break

            for link in new_links:
                seen_urls.add(link.url)
            all_links.extend(new_links)

        logger.info("Discovered %d PDF links for %s", len(all_links), page_type)
        return all_links

    def _extract_pdf_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        page_type: str,
    ) -> list[PDFLink]:
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue

            full_url = href if href.startswith("http") else urljoin(base_url, href)
            title    = a.get_text(strip=True) or a.get("title", "") or Path(urlparse(full_url).path).stem
            state    = self._guess_state_from_title(title)

            links.append(PDFLink(
                url           = full_url,
                title         = title,
                source_type   = "fssai",
                page_type     = page_type,
                discovered_at = datetime.utcnow(),
                state_hint    = state,
            ))
        return links

    @staticmethod
    def _guess_state_from_title(title: str) -> Optional[str]:
        """Try to extract a state name from the document title."""
        from pipeline.config import STATE_ALIASES
        title_lower = title.lower()
        for alias, canonical in STATE_ALIASES.items():
            if alias in title_lower:
                return canonical
        return None


# ============================================================
# DOWNLOAD MANAGER
# ============================================================

class PDFDownloadManager:
    """
    Downloads PDFs to local disk and optionally to S3.
    Tracks downloaded URLs in DB to avoid re-downloading.
    """

    def __init__(
        self,
        client: RateLimitedClient,
        local_dir: Path = RAW_DIR,
        use_s3: bool = False,
        db_conn=None,
    ):
        self.client    = client
        self.local_dir = local_dir
        self.use_s3    = use_s3
        self.db_conn   = db_conn
        self._s3       = boto3.client("s3", region_name=S3_REGION) if use_s3 else None

        local_dir.mkdir(parents=True, exist_ok=True)

    def already_downloaded(self, url: str) -> bool:
        """Check DB for existing record with this source_url."""
        if not self.db_conn:
            return False
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM enforcement_records WHERE source_url = %s LIMIT 1",
                    (url,)
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def download(self, link: PDFLink) -> DownloadedFile:
        if self.already_downloaded(link.url):
            logger.debug("Already downloaded: %s", link.url)
            return DownloadedFile(
                pdf_link=link,
                local_path=None,
                s3_key=None,
                file_size_bytes=0,
                download_ok=True,
                error="already_downloaded",
            )

        # Derive local filename from URL
        filename = Path(urlparse(link.url).path).name or "report.pdf"
        local_path = self.local_dir / link.source_type / link.page_type / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            resp = self.client.get(link.url)
            content = resp.content

            local_path.write_bytes(content)
            logger.info("Downloaded %s → %s (%d bytes)", link.url, local_path.name, len(content))

            s3_key = None
            if self.use_s3 and self._s3:
                s3_key = self._upload_to_s3(content, link, filename)

            return DownloadedFile(
                pdf_link       = link,
                local_path     = local_path,
                s3_key         = s3_key,
                file_size_bytes = len(content),
                download_ok    = True,
            )

        except Exception as e:
            logger.error("Download failed for %s: %s", link.url, e)
            return DownloadedFile(
                pdf_link       = link,
                local_path     = None,
                s3_key         = None,
                file_size_bytes = 0,
                download_ok    = False,
                error          = str(e),
            )

    def _upload_to_s3(self, content: bytes, link: PDFLink, filename: str) -> Optional[str]:
        now = datetime.utcnow()
        key = (
            f"raw/{link.source_type}/{link.page_type}/"
            f"{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
        )
        try:
            self._s3.put_object(
                Bucket      = S3_BUCKET,
                Key         = key,
                Body        = content,
                ContentType = "application/pdf",
                Metadata    = {
                    "source_url":  link.url,
                    "title":       link.title,
                    "page_type":   link.page_type,
                    "state_hint":  link.state_hint or "",
                },
            )
            logger.info("Uploaded to s3://%s/%s", S3_BUCKET, key)
            return key
        except Exception as e:
            logger.error("S3 upload failed: %s", e)
            return None

    def download_batch(self, links: list[PDFLink]) -> list[DownloadedFile]:
        results = []
        for link in links:
            results.append(self.download(link))
        return results


# ============================================================
# FULL FSSAI SCRAPE JOB (called by Airflow)
# ============================================================

def run_fssai_scrape(
    page_types: list[str] | None = None,
    use_s3: bool = False,
    db_conn=None,
    max_pages: int = 10,   # lower for testing; use 50 in prod
) -> list[DownloadedFile]:
    """
    Top-level job:
    1. Discover all PDF links from FSSAI listing pages
    2. Download any not already processed
    3. Return list of DownloadedFile for the extraction stage
    """
    if page_types is None:
        page_types = list(FSSAI_PAGES.keys())

    client    = RateLimitedClient()
    discoverer = FSSAILinkDiscoverer(client)
    downloader = PDFDownloadManager(client, use_s3=use_s3, db_conn=db_conn)

    all_files: list[DownloadedFile] = []
    try:
        for page_type in page_types:
            links = discoverer.discover(page_type, max_pages=max_pages)
            files = downloader.download_batch(links)
            all_files.extend(files)
    finally:
        client.close()

    ok    = sum(1 for f in all_files if f.download_ok and f.error != "already_downloaded")
    skip  = sum(1 for f in all_files if f.error == "already_downloaded")
    fail  = sum(1 for f in all_files if not f.download_ok)
    logger.info("FSSAI scrape complete: %d downloaded, %d skipped, %d failed", ok, skip, fail)

    return [f for f in all_files if f.download_ok and f.local_path is not None]
