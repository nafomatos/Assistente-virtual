"""Tests for tracker/recommendation_parser.py.

Covers the code-enforced actionable-confidence floors (shorts ≥ 6, longs ≥ 7)
and robust per-recommendation confidence parsing (a malformed value must not
abort the whole batch).
"""

from __future__ import annotations

import datetime as dt

import tracker.recommendation_parser as rp


def _patch_tracker(monkeypatch, price: float | None = 100.0) -> list[dict]:
    """Stub out the live price fetch and position persistence."""
    added: list[dict] = []

    def _fake_add(**kwargs):
        added.append(kwargs)
        return kwargs

    monkeypatch.setattr(rp, "fetch_price", lambda ticker: price)
    monkeypatch.setattr(rp, "add_position", _fake_add)
    return added


_DATE = dt.date(2026, 6, 8)


def _rec(ticker: str, recommendation: str, confidence) -> dict:
    return {
        "ticker": ticker,
        "classification": "bubble_forming",
        "recommendation": recommendation,
        "reasoning": "test",
        "confidence": confidence,
    }


def test_short_below_floor_is_skipped(monkeypatch):
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add([_rec("NVDA", "reduce_exposure", 5)], date=_DATE)
    assert added == []


def test_short_at_floor_is_added(monkeypatch):
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add([_rec("NVDA", "reduce_exposure", 6)], date=_DATE)
    assert len(added) == 1
    assert added[0]["direction"] == "short"
    assert added[0]["confidence"] == 6


def test_long_below_floor_is_skipped(monkeypatch):
    """contrarian_buy requires confidence ≥ 7 — enforced in code, not just prompt."""
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add([_rec("SOFI", "contrarian_buy", 6)], date=_DATE)
    assert added == []


def test_long_at_floor_is_added(monkeypatch):
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add([_rec("SOFI", "contrarian_buy", 7)], date=_DATE)
    assert len(added) == 1
    assert added[0]["direction"] == "long"


def test_malformed_confidence_does_not_abort_batch(monkeypatch):
    """A string confidence defaults to 5 (below both floors → skipped) and the
    remaining recommendations are still processed."""
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add(
        [
            _rec("NVDA", "reduce_exposure", "high"),
            _rec("SOFI", "contrarian_buy", 8),
        ],
        date=_DATE,
    )
    assert [p["ticker"] for p in added] == ["SOFI"]


def test_confidence_clamped_to_valid_range(monkeypatch):
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add([_rec("NVDA", "reduce_exposure", 15)], date=_DATE)
    assert added[0]["confidence"] == 10


def test_non_directional_recommendations_skipped(monkeypatch):
    added = _patch_tracker(monkeypatch)
    rp.parse_and_add(
        [_rec("NVDA", "wait", 9), _rec("AAPL", "no_action", 9)], date=_DATE
    )
    assert added == []
