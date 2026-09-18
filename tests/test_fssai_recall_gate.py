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


def test_healthy_page_is_open():
    assert classify_portal_state("Food Recall  Search  Filter", 200, 200) == "open"


def test_maintenance_wins_over_a_status_code():
    assert classify_portal_state("Maintenance ... unavailable", 401, 401) == "maintenance"


class _Page:
    def __init__(self, value=None, exc=None):
        self._value, self._exc = value, exc

    def evaluate(self, _js):
        if self._exc:
            raise self._exc
        return self._value


def test_read_body_text_returns_text():
    assert read_body_text(_Page("hello")) == "hello"


def test_read_body_text_swallows_evaluation_errors_instead_of_blocking():
    assert read_body_text(_Page(exc=RuntimeError("Execution context was destroyed"))) == ""


@pytest.mark.parametrize("value", [None, ""])
def test_read_body_text_normalises_empty_results(value):
    assert read_body_text(_Page(value)) == ""
