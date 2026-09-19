"""
Tests for the FoSCoS gate classification in pipeline/sources/fssai_recall.py.

Why it exists: since the week of 2026-08-10 the portal's CSRF bootstrap returns
401 to an anonymous visitor and the app crashes on init, leaving an empty body.
The scraper used to hit page.inner_text('body'), time out, and report that
documented gate as a daily regression. These tests pin what counts as an
EXPLAINED gate (quiet) versus an UNEXPLAINED blank page (must stay loud).
"""
from __future__ import annotations

import pytest

from pipeline.sources.fssai_recall import classify_portal_state, read_body_text


def test_maintenance_page_is_recognised():
    assert classify_portal_state("Daily Maintenance in Progress. Service unavailable.", None, None) == "maintenance"


def test_recall_api_401_is_the_auth_gate():
    assert classify_portal_state("Search food recalls", 401, None) == "auth_gate"


def test_csrf_bootstrap_401_with_an_empty_body_is_the_auth_gate():
    # The 2026-08 symptom: no recall call is ever made, the CSRF call 401s, page is blank.
    assert classify_portal_state("", None, 401) == "auth_gate"


def test_a_gate_is_still_a_gate_when_some_text_rendered():
    assert classify_portal_state("Loading...", 200, 401) == "auth_gate"


def test_blank_page_with_no_explaining_status_is_unrendered_not_gate():
    # An unexplained blank page must NOT be filed under the expected gate.
    assert classify_portal_state("", None, None) == "unrendered"
    assert classify_portal_state("   \n ", 200, 200) == "unrendered"


def test_connection_timeout_from_the_runner_is_unreachable_not_unrendered():
    # 2026-09-18 21:40 UTC, GitHub runner: net::ERR_CONNECTION_TIMED_OUT, no page, no API calls.
    err = "Page.goto: net::ERR_CONNECTION_TIMED_OUT at https://foscos.fssai.gov.in/food-recall"
    assert classify_portal_state("", None, None, err) == "unreachable"


@pytest.mark.parametrize("err", [
    "Page.goto: net::ERR_NAME_NOT_RESOLVED at https://foscos.fssai.gov.in/food-recall",
    "Page.goto: net::ERR_CONNECTION_RESET at https://foscos.fssai.gov.in/food-recall",
])
def test_other_network_errors_are_unreachable(err):
    assert classify_portal_state("", None, None, err) == "unreachable"


def test_a_non_network_navigation_timeout_is_not_called_unreachable():
    # networkidle never settling is not proof the network is down: with a blank
    # page and no status it must stay 'unrendered' (loud).
    assert classify_portal_state("", None, None, "Page.goto: Timeout 60000ms exceeded.") == "unrendered"


def test_a_network_error_does_not_mask_an_explained_401_gate():
    # If something did render/answer, trust the status rather than the error text.
    assert classify_portal_state("Loading", 401, None, "net::ERR_ABORTED") == "auth_gate"


def test_healthy_page_is_open():
    assert classify_portal_state("Food Recall  Search  Filter", 200, 200) == "open"


def test_maintenance_wins_over_a_status_code():
    assert classify_portal_state("Maintenance ... unavailable", 401, 401) == "maintenance"


class _Page:
    def __init__(self, value=None, exc=None):
        self._value, self._exc = value, exc
        self.waited = 0

    def evaluate(self, _js):
        if self._exc:
            raise self._exc
        return self._value

    def wait_for_load_state(self, *_a, **_k):
        self.waited += 1


def test_read_body_text_returns_text():
    assert read_body_text(_Page("hello")) == "hello"


def test_read_body_text_swallows_evaluation_errors_instead_of_blocking():
    assert read_body_text(_Page(exc=RuntimeError("Execution context was destroyed"))) == ""


@pytest.mark.parametrize("value", [None, ""])
def test_read_body_text_normalises_empty_results(value):
    assert read_body_text(_Page(value)) == ""


class _FlakyPage(_Page):
    """First read hits a navigation (context destroyed), the second succeeds."""

    def __init__(self, text):
        super().__init__(text)
        self.calls = 0

    def evaluate(self, js):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        return self._value


def test_read_body_text_retries_once_after_a_navigation_destroys_the_context():
    page = _FlakyPage("Food Recall")
    assert read_body_text(page) == "Food Recall"
    assert page.calls == 2 and page.waited == 1


def test_read_body_text_gives_up_after_the_retry():
    page = _Page(exc=RuntimeError("Execution context was destroyed"))
    assert read_body_text(page) == "" and page.waited == 1


def test_ending_on_the_browsers_own_error_page_is_unreachable_even_after_a_goto_timeout():
    # 2026-09-19 CI: goto 'timed out' (not net::ERR_*), then the tab sat on chrome-error://chromewebdata/.
    err = "Page.goto: Timeout 60000ms exceeded."
    assert classify_portal_state("", None, None, err, "chrome-error://chromewebdata/") == "unreachable"
    # ...even if the error page has text (the read succeeded on it) — it is still not the portal.
    assert classify_portal_state("This site can't be reached", None, None, err, "chrome-error://chromewebdata/") == "unreachable"


def test_a_real_401_still_beats_the_error_page_heuristic():
    assert classify_portal_state("", 401, None, "", "chrome-error://chromewebdata/") == "auth_gate"


def test_a_blank_page_on_the_portals_own_url_stays_unrendered():
    assert classify_portal_state("", None, None, "Page.goto: Timeout 60000ms exceeded.",
                                 "https://foscos.fssai.gov.in/food-recall") == "unrendered"
