"""
Tests for models/backtest.py's analyze() — the H1.5 backtest classification
logic. No DB needed: analyze() is a pure function over an in-memory record
list (load_real_records is the only DB-touching piece, tested separately).
"""
from __future__ import annotations

from datetime import date

from models.backtest import analyze


def _record(day: int, commodity_id: int, pass_fail: bool, source_type: str = "usfda") -> dict:
    return {
        "test_date": date(2024, 1, 1).replace(day=day) if day <= 28 else date(2024, 2, day - 28),
        "source_type": source_type,
        "state": "CA",
        "commodity_id": commodity_id,
        "pass_fail": pass_fail,
    }


def test_analyze_no_records():
    result = analyze([])
    assert result["n_records"] == 0
    assert result["verdict"] == "no real records available yet"


def test_analyze_flags_degenerate_all_fail_as_not_meaningful():
    # Mirrors the real openFDA data: every record is a confirmed recall,
    # so there's no negative class to score discrimination against.
    records = [_record(day=d, commodity_id=d, pass_fail=False) for d in range(1, 11)]
    result = analyze(records)
    assert result["meaningful"] is False
    assert "NOT MEANINGFUL" in result["verdict"]
    assert result["pass_fail_breakdown"] == {"fail": 10, "pass": 0}


def test_analyze_flags_sparse_data_as_not_meaningful_even_with_both_classes():
    # Both classes present, but too few records / too spread across
    # commodities to be a statistically meaningful temporal holdout.
    records = [_record(day=d, commodity_id=d, pass_fail=(d % 2 == 0)) for d in range(1, 11)]
    result = analyze(records)
    assert result["meaningful"] is False
    assert "too sparse" in result["verdict"]


def test_analyze_meaningful_when_balanced_and_dense():
    # 40 records, both classes present, concentrated in a few commodities
    # (>=5 records each) — enough to clear the sparsity/balance bar.
    records = []
    for i in range(40):
        day = (i % 28) + 1
        records.append(_record(day=day, commodity_id=i % 3, pass_fail=(i % 2 == 0)))
    result = analyze(records)
    assert result["meaningful"] is True
    assert result["verdict"].startswith("Meaningful")


def test_analyze_temporal_split_is_80_20_by_order():
    records = [_record(day=(d % 28) + 1, commodity_id=1, pass_fail=(d % 2 == 0)) for d in range(50)]
    result = analyze(records)
    assert result["n_train"] == 40
    assert result["n_test"] == 10
