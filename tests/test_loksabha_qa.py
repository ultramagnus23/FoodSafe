"""
Tests for pipeline/sources/loksabha_qa.py question identity across Lok Sabha
terms. No network or DB: `_search` is monkeypatched.

The bug these guard against: question numbers restart every Lok Sabha, so
keying on quesNo alone would merge unrelated questions from different terms
(and, with the old (state, fiscal_year, source_question_no) DB key, silently
overwrite one term's disclosure with another's).
"""
from __future__ import annotations

from pipeline.sources import loksabha_qa as L

HFW = "HEALTH AND FAMILY WELFARE"


def _q(lok, no, ministry=HFW, subject="x"):
    return {"lokNo": str(lok), "quesNo": str(no), "ministry": ministry, "subjects": subject,
            "questionsFilePath": f"https://sansad.in/{lok}/{no}.pdf"}


def test_question_key_normalises_types_and_whitespace():
    assert L.question_key({"lokNo": "17", "quesNo": " 1234 "}) == (17, "1234")
    assert L.question_key({"lokNo": 17, "quesNo": 1234}) == (17, "1234")


def test_same_number_in_different_terms_are_distinct_questions(monkeypatch):
    def fake_search(kw, term, page_size=200):
        return [_q(term, 1234, subject=f"term {term}")]
    monkeypatch.setattr(L, "_search", fake_search)
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a"])

    found = L.discover_questions(terms=(18, 17, 16))

    assert len(found) == 3
    assert {q["subjects"] for q in found} == {"term 18", "term 17", "term 16"}


def test_same_question_returned_by_several_keywords_is_deduped(monkeypatch):
    monkeypatch.setattr(L, "_search", lambda kw, term, page_size=200: [_q(term, 7)])
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a", "b", "c"])

    assert len(L.discover_questions(terms=(17,))) == 1


def test_non_health_ministry_questions_are_dropped(monkeypatch):
    monkeypatch.setattr(L, "_search", lambda kw, term, page_size=200: [
        _q(term, 1), _q(term, 2, ministry="AGRICULTURE AND FARMERS WELFARE"),
    ])
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a"])

    found = L.discover_questions(terms=(17,))

    assert [q["quesNo"] for q in found] == ["1"]


def test_one_failing_search_does_not_abort_the_rest(monkeypatch):
    def flaky(kw, term, page_size=200):
        if kw == "bad":
            raise RuntimeError("boom")
        return [_q(term, 5)]
    monkeypatch.setattr(L, "_search", flaky)
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["bad", "good"])

    assert len(L.discover_questions(terms=(17,))) == 1


# ---- an unreachable source must fail the run, not look like "no questions" ----

import pytest  # noqa: E402


def test_every_search_failing_raises_instead_of_returning_nothing(monkeypatch):
    calls = []

    def dead(kw, term, page_size=200):
        calls.append((kw, term))
        raise OSError("timed out")
    monkeypatch.setattr(L, "_search", dead)
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a", "b", "c", "d", "e"])

    with pytest.raises(L.SearchUnavailable):
        L.discover_questions(terms=(18, 17))
    # Three failures in a row abandon a term: 3 per term, not 5.
    assert len(calls) == 6


def test_a_dead_term_is_abandoned_but_the_next_term_is_still_tried(monkeypatch):
    def flaky(kw, term, page_size=200):
        if term == 18:
            raise OSError("timed out")
        return [_q(term, 9)]
    monkeypatch.setattr(L, "_search", flaky)
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a", "b", "c", "d"])

    found = L.discover_questions(terms=(18, 17))

    assert [int(q["lokNo"]) for q in found] == [17]


def test_a_success_resets_the_failure_streak(monkeypatch):
    seq = iter([OSError("x"), OSError("x"), None, OSError("x"), OSError("x"), None])

    def spotty(kw, term, page_size=200):
        r = next(seq)
        if r:
            raise r
        return [_q(term, int(ord(kw)))]
    monkeypatch.setattr(L, "_search", spotty)
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a", "b", "c", "d", "e", "f"])

    assert len(L.discover_questions(terms=(17,))) == 2   # never three failures in a row


def test_a_search_that_succeeds_with_no_matches_is_not_an_outage(monkeypatch):
    monkeypatch.setattr(L, "_search", lambda kw, term, page_size=200: [])
    monkeypatch.setattr(L, "SEARCH_KEYWORDS", ["a", "b"])
    assert L.discover_questions(terms=(17,)) == []
