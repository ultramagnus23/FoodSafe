"""
FoSCoS accessibility probe — read-only, evidence-gathering only.

Part of the India data-accessibility audit (see docs/PAPER_SCOPING.md,
docs/FSSAI_INGESTION.md). Turns the one-off diagnostic from the 2026-07-04
investigation into a recurring, dated measurement: does the
foscos.fssai.gov.in recall API return real data, a maintenance response, or
an auth/captcha gate — and does that answer change over time?

This performs ONLY page loads, DOM reads, and network header inspection.
It never attempts to solve/bypass the captcha, guess credentials, or send
anything other than what a normal browser visiting the public page would
send. If FSSAI's access model changes (opens back up, tightens further,
adds new gates), this is how we'll have dated evidence of it instead of a
single anecdote.

Appends one JSON line per run to docs/foscos_access_log.jsonl. Designed to
run standalone (no DB) so it can run in CI on a schedule independent of the
ingestion pipeline.

Run:  python scripts/probe_foscos.py
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("foodsafe.foscos_probe")

RECALL_URL = "https://foscos.fssai.gov.in/food-recall"
LOG_PATH = Path(__file__).resolve().parent.parent / "docs" / "foscos_access_log.jsonl"

# Endpoints worth tracking individually — the recall API itself, plus one
# unrelated cosmetic endpoint under the same "commonauth_readonly" path.
# Tracking both is what let us tell, on 2026-07-04, that FSSAI locked the
# entire commonapi surface rather than just the recall list.
TRACKED_MARKERS = {
    "recall_api": "getFoodRecallProductHomepage",
    "dropdown_api": "getfinancialyeardropdown",
    "csrf_token": "auth/csrf-token",
}


def probe() -> dict:
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "maintenance_window": None,
        "search_button_found": None,
        "endpoints": {name: {"hit": False, "status": None, "headers": {}} for name in TRACKED_MARKERS},
        "error": None,
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result["error"] = "playwright not installed"
        return result

    # Vantage point matters: on 2026-09-18 a local run saw the CSRF bootstrap
    # return 401 while six consecutive CI probes recorded no endpoint hits at
    # all, so the same page can fail differently from different networks.
    result["vantage"] = "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local"
    result["body_chars"] = None
    result["console_errors"] = []
    result["failed_requests"] = []
    result["http_errors"] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def on_console(msg):
                if msg.type == "error" and len(result["console_errors"]) < 3:
                    result["console_errors"].append(msg.text[:160])

            def on_request_failed(req):
                if len(result["failed_requests"]) < 5:
                    result["failed_requests"].append({"url": req.url[:100], "reason": (req.failure or "")[:60]})

            def on_http_error(resp):
                if resp.status >= 400 and len(result["http_errors"]) < 5:
                    result["http_errors"].append({"status": resp.status, "url": resp.url[:100]})

            page.on("console", on_console)
            page.on("requestfailed", on_request_failed)
            page.on("response", on_http_error)

            def on_response(resp):
                for name, marker in TRACKED_MARKERS.items():
                    if marker in resp.url:
                        interesting_headers = {
                            k: v for k, v in resp.headers.items()
                            if k.lower() in (
                                "access-control-expose-headers",
                                "access-control-allow-headers",
                                "server",
                            )
                        }
                        result["endpoints"][name] = {
                            "hit": True,
                            "status": resp.status,
                            "headers": interesting_headers,
                        }

            page.on("response", on_response)

            try:
                page.goto(RECALL_URL, wait_until="networkidle", timeout=60000)
            except Exception as e:  # noqa: BLE001
                result["error"] = f"page.goto warning: {e}"
            page.wait_for_timeout(3000)

            # Read the body WITHOUT a waiting locator. page.inner_text("body")
            # blocks 30s and raises when the app crashes on init, which threw
            # away the whole entry (six 2026-08/09 probes lost their endpoint
            # data that way even though the responses had been observed).
            try:
                body_text = page.evaluate("document.body ? document.body.innerText : ''") or ""
            except Exception as e:  # noqa: BLE001
                body_text = ""
                result["error"] = f"body read failed: {e}"
            result["body_chars"] = len(body_text)
            result["maintenance_window"] = "Maintenance" in body_text and "unavailable" in body_text

            if not result["maintenance_window"]:
                search_btn = page.query_selector("button:has-text('Search')")
                result["search_button_found"] = bool(search_btn)
                if search_btn:
                    search_btn.click()
                    page.wait_for_timeout(8000)

            browser.close()
    except Exception as e:  # noqa: BLE001
        result["error"] = f"probe failed: {e}"

    return result


def append_log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    entry = probe()
    append_log(entry)
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
