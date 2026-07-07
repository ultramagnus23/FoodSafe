"""
Tests for api/provenance.py — the real/synthetic-data disclosure logic (H1.1).
No DB connection needed: compute_synthetic_fraction/summarize are pure functions.
"""
from __future__ import annotations

from api.provenance import EMPTY_PROVENANCE, compute_synthetic_fraction, summarize


def test_compute_synthetic_fraction_no_records():
    assert compute_synthetic_fraction(0, 0) is None


def test_compute_synthetic_fraction_all_real():
    assert compute_synthetic_fraction(10, 0) == 0.0


def test_compute_synthetic_fraction_all_synthetic():
    assert compute_synthetic_fraction(0, 10) == 1.0


def test_compute_synthetic_fraction_mixed():
    assert compute_synthetic_fraction(3, 1) == 0.25


def test_summarize_flags_any_synthetic_as_synthetic():
    # Even one synthetic record must flag is_synthetic=True — a user can't
    # tell which specific number in a mixed result came from which record,
    # so a partial synthetic backing is disclosed the same as a full one.
    result = summarize(real_count=99, synthetic_count=1)
    assert result.is_synthetic is True
    assert result.real_count == 99
    assert result.synthetic_count == 1
    assert result.synthetic_fraction == 0.01


def test_summarize_all_real_not_flagged_synthetic():
    result = summarize(real_count=5, synthetic_count=0)
    assert result.is_synthetic is False
    assert result.synthetic_fraction == 0.0


def test_summarize_no_records_is_not_synthetic():
    # Absence of any record must never be conflated with "confirmed synthetic"
    # or "confirmed real" — it's its own no-data case.
    result = summarize(real_count=0, synthetic_count=0)
    assert result.is_synthetic is False
    assert result.synthetic_fraction is None


def test_empty_provenance_constant():
    assert EMPTY_PROVENANCE.real_count == 0
    assert EMPTY_PROVENANCE.synthetic_count == 0
    assert EMPTY_PROVENANCE.synthetic_fraction is None
    assert EMPTY_PROVENANCE.is_synthetic is False
