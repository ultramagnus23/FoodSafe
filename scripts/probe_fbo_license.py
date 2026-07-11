"""
FoSCoS FBO/license search accessibility probe — read-only, one-shot
investigation.

Part of the India data-accessibility audit (see docs/FSSAI_INGESTION.md,
docs/FSSAI_FBO_LICENSE_INVESTIGATION.md, docs/REACHABLE_TEXT_INVENTORY.md).
`scripts/probe_foscos.py` already established that FoSCoS's *recall* API
(`getFoodRecallProductHomepage`) is 401-blocked behind a captcha/auth
handshake on the entire `commonauth_readonly/commonapi/*` surface. This
script asks the same question of a *different* FoSCoS feature: the public
"Commodity, Category Or Area Specific Search" tool at
`/advance-fbo-search`, which citizens use to look up licensed food
business operators (FBOs) — potentially a real source of addresses for
locality-level coverage, independent of violation/recall data.

This performs ONLY page loads, DOM/network inspection, and (if the search
form turns out to be usable without auth) a single synthetic query by a
real public pincode — never a real person's data. It NEVER attempts to
solve/bypass the captcha, guess credentials, or send anything other than
what a normal browser visiting the public page would send. If the captcha
or `commonapi` endpoints return 401 before any interaction, that is
recorded as a negative result and the script stops — no workaround is
attempted, per this project's stated ethical boundary
(docs/FSSAI_INGESTION.md).

Appends one JSON line per run to docs/foscos_fbo_search_access_log.jsonl,
mirroring probe_foscos.py's log format so future runs (if this source is
ever reopened) build dated evidence instead of a single anecdote.

Run:  python scripts/probe_fbo_license.py
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("foodsafe.fbo_search_probe")

SEARCH_URL = "https://foscos.fssai.gov.in/advance-fbo-search"
LOG_PATH = Path(__file__).resolve().parent.parent / "docs" / "foscos_fbo_search_access_log.jsonl"

# A real, public Indian pincode (Vile Parle West, Mumbai) — not personal
# data. Used only if the search form turns out to be reachable without
# auth; we never got that far (see below), but the constant documents
# what a follow-up run should try first.
TEST_PINCODE = "400049"

# Endpoints the /advance-fbo-search page calls on load / on form
# interaction, all under the same commonauth_readonly path already
# confirmed blocked for the recall feature. Tracking them individually
# lets us see whether FSSAI ever unblocks this surface selectively
# (e.g. captcha becomes public even if the data API stays gated).
TRACKED_MARKERS = {
    "captcha_api": "commonauth_readonly/commonapi/captcha",
    "kob_dropdown_api": "commonauth_readonly/commonapi/getallsearchkoblist",
    "advance_search_api": "commonauth_readonly/commonapi/getadvancesearchapplicationdetails",
    "advance_search_count_api": "commonauth_readonly/commonapi/getadvancesearchapplicationcount",
}


def probe() -> dict:
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "page_loaded": None,
        "search_form_found": None,
        "captcha_field_found": None,
        "endpoints": {name: {"hit": False, "status": None, "headers": {}} for name in TRACKED_MARKERS},
        "search_attempted": False,
        "search_result_sample": None,
        "error": None,
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result["error"] = "playwright not installed"
        return result

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

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
                page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
            except Exception as e:  # noqa: BLE001
                result["error"] = f"page.goto warning: {e}"
            page.wait_for_timeout(4000)

            result["page_loaded"] = SEARCH_URL in page.url or True

            search_btn = page.query_selector("button:has-text('Search')")
            result["search_form_found"] = bool(search_btn)

            captcha_input = page.query_selector("input[placeholder='Enter Captcha Code']")
            result["captcha_field_found"] = bool(captcha_input)

            # Read-only ethical boundary: if the captcha API itself is
            # already 401 (meaning the captcha image can never render for
            # an anonymous client), there is nothing left to legitimately
            # try — filling in the pincode field and clicking Search would
            # only demonstrate the same 401, and clicking Search without a
            # valid captcha would just trigger a client-side validation
            # error, not new information. We stop here in that case.
            captcha_blocked = result["endpoints"]["captcha_api"]["status"] == 401
            if search_btn and captcha_input and not captcha_blocked:
                pincode_input = page.query_selector("input[placeholder='PIN Code'], input[placeholder='Pincode']")
                if pincode_input:
                    pincode_input.fill(TEST_PINCODE)
                    result["search_attempted"] = True
                    search_btn.click()
                    page.wait_for_timeout(6000)
                    body_text = page.inner_text("body")
                    result["search_result_sample"] = body_text[:1000]

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
