"""Tests for tracker.cluster_detector.

Coverage:
  1. 2 tickers from the same sector + direction → cluster does NOT trigger (threshold is 3)
  2. 3 semis tickers all bubble_forming within 5 days → cluster detected, boost +1
  3. 5 semis tickers (mixed bubble_forming + reduce_exposure) within 5 days
       → cluster detected as bearish_overheating, boost +2
  4. 3 semis bubble_forming + 3 mega_tech irrational_panic → 2 separate clusters
  5. 3 semis bubble_forming, but spread across 8 business days → does NOT trigger
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from tracker.cluster_detector import apply_cluster_boosts, detect_clusters


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_signals(logs_dir: str, date_str: str, signals: list[dict]) -> None:
    path = os.path.join(str(logs_dir), f"signals_{date_str}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"date": date_str, "signals": signals}, fh)


def _sig(ticker: str, classification: str, recommendation: str, confidence: int = 7) -> dict:
    return {
        "ticker": ticker,
        "classification": classification,
        "recommendation": recommendation,
        "confidence": confidence,
        "reasoning": "test fixture",
    }


_REF = dt.date(2026, 5, 6)   # Wednesday; last-5-bdays = 05-06,05-05,05-04,05-01,04-30


# ── test 1 ────────────────────────────────────────────────────────────────────

def test_below_threshold_no_cluster(tmp_path):
    """2 semis tickers bubble_forming — cluster does NOT trigger (need ≥ 3)."""
    _write_signals(
        tmp_path, "2026-05-06",
        [
            _sig("NVDA", "bubble_forming", "reduce_exposure"),
            _sig("AMD",  "bubble_forming", "reduce_exposure"),
        ],
    )
    clusters = detect_clusters(days_window=5, logs_dir=str(tmp_path), reference_date=_REF)
    assert clusters == [], "Expected no cluster for 2 tickers"


# ── test 2 ────────────────────────────────────────────────────────────────────

def test_three_semis_bubble_forming_boost_one(tmp_path):
    """3 semis tickers all bubble_forming within the window → boost +1."""
    _write_signals(
        tmp_path, "2026-05-06",
        [
            _sig("NVDA",  "bubble_forming", "reduce_exposure", 8),
            _sig("AMD",   "bubble_forming", "reduce_exposure", 7),
            _sig("SMCI",  "bubble_forming", "reduce_exposure", 9),
        ],
    )
    clusters = detect_clusters(days_window=5, logs_dir=str(tmp_path), reference_date=_REF)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["sector"]          == "semis"
    assert c["direction_group"] == "bearish_overheating"
    assert c["count"]           == 3
    assert c["boost"]           == 1
    assert set(c["tickers"])    == {"NVDA", "AMD", "SMCI"}


# ── test 3 ────────────────────────────────────────────────────────────────────

def test_five_semis_mixed_classification_boost_two(tmp_path):
    """5 semis tickers — mix of bubble_forming classification and reduce_exposure
    recommendation — all map to bearish_overheating → boost +2."""
    _write_signals(
        tmp_path, "2026-05-04",
        [
            _sig("NVDA", "bubble_forming", "reduce_exposure", 8),
            _sig("AMD",  "bubble_forming", "reduce_exposure", 7),
        ],
    )
    _write_signals(
        tmp_path, "2026-05-05",
        [
            _sig("SMCI", "ambiguous",      "reduce_exposure", 6),  # rec maps to bearish
            _sig("ARM",  "bubble_forming", "wait",            6),  # cls maps to bearish
        ],
    )
    _write_signals(
        tmp_path, "2026-05-06",
        [
            _sig("INTC", "bubble_forming", "reduce_exposure", 6),
        ],
    )
    clusters = detect_clusters(days_window=5, logs_dir=str(tmp_path), reference_date=_REF)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["sector"]          == "semis"
    assert c["direction_group"] == "bearish_overheating"
    assert c["count"]           == 5
    assert c["boost"]           == 2
    assert set(c["tickers"])    == {"NVDA", "AMD", "SMCI", "ARM", "INTC"}


# ── test 4 ────────────────────────────────────────────────────────────────────

def test_two_independent_clusters(tmp_path):
    """3 semis bubble_forming + 3 mega_tech irrational_panic → 2 separate clusters."""
    _write_signals(
        tmp_path, "2026-05-06",
        [
            _sig("NVDA",  "bubble_forming",  "reduce_exposure", 8),
            _sig("AMD",   "bubble_forming",  "reduce_exposure", 7),
            _sig("SMCI",  "bubble_forming",  "reduce_exposure", 9),
            _sig("AAPL",  "irrational_panic", "contrarian_buy", 7),
            _sig("MSFT",  "irrational_panic", "contrarian_buy", 8),
            _sig("GOOGL", "irrational_panic", "contrarian_buy", 7),
        ],
    )
    clusters = detect_clusters(days_window=5, logs_dir=str(tmp_path), reference_date=_REF)
    assert len(clusters) == 2

    by_sector = {c["sector"]: c for c in clusters}
    assert "semis"     in by_sector
    assert "mega_tech" in by_sector

    semis = by_sector["semis"]
    assert semis["direction_group"] == "bearish_overheating"
    assert semis["count"]           == 3
    assert semis["boost"]           == 1

    mega = by_sector["mega_tech"]
    assert mega["direction_group"] == "bullish_panic"
    assert mega["count"]           == 3
    assert mega["boost"]           == 1


# ── test 5 ────────────────────────────────────────────────────────────────────

def test_out_of_window_no_cluster(tmp_path):
    """3 semis tickers bubble_forming but all 8 business days before reference →
    outside the 5-day window, so no cluster triggered."""
    # 8 business days before 2026-05-06:
    #   -1 05-05, -2 05-04, -3 05-01, -4 04-30, -5 04-29,
    #   -6 04-28, -7 04-27, -8 04-24
    _write_signals(
        tmp_path, "2026-04-24",
        [
            _sig("NVDA", "bubble_forming", "reduce_exposure", 8),
            _sig("AMD",  "bubble_forming", "reduce_exposure", 7),
            _sig("SMCI", "bubble_forming", "reduce_exposure", 9),
        ],
    )
    clusters = detect_clusters(days_window=5, logs_dir=str(tmp_path), reference_date=_REF)
    assert clusters == [], "Signals from 8 bdays ago must not trigger a 5-day cluster"


# ── apply_cluster_boosts ──────────────────────────────────────────────────────

_SEMIS_BEARISH_CLUSTER = {
    "sector": "semis",
    "direction_group": "bearish_overheating",
    "tickers": ["AMD", "NVDA", "SMCI"],
    "count": 3,
    "boost": 1,
    "first_seen": "2026-05-04",
    "last_seen": "2026-05-06",
}


def test_boost_applies_to_matching_signal():
    sig = _sig("NVDA", "bubble_forming", "reduce_exposure", 7)
    apply_cluster_boosts([sig], [_SEMIS_BEARISH_CLUSTER])
    assert sig["confidence"] == 8
    assert sig["cluster_boost"]["original_confidence"] == 7
    assert sig["cluster_boost"]["boost_amount"] == 1
    assert sig["cluster_boost"]["sector"] == "semis"


def test_boost_never_rearms_macro_capped_signal():
    """A bubble short capped to 5 by the macro fear gate must NOT be boosted
    back above MIN_SHORT_CONFIDENCE — that would silently defeat the cap."""
    sig = _sig("NVDA", "bubble_forming", "reduce_exposure", 5)
    sig["v2_gate"] = {
        "action": "confidence_capped",
        "rule": "macro_fear_cap",
        "original_confidence": 8,
    }
    apply_cluster_boosts([sig], [_SEMIS_BEARISH_CLUSTER])
    assert sig["confidence"] == 5
    assert "cluster_boost" not in sig


def test_boost_caps_confidence_at_ten():
    sig = _sig("NVDA", "bubble_forming", "reduce_exposure", 10)
    apply_cluster_boosts([sig], [_SEMIS_BEARISH_CLUSTER])
    assert sig["confidence"] == 10


def test_boost_requires_cluster_membership():
    """A signal matching a cluster's sector/direction but absent from its
    ticker list was never verified against the pattern (today's signals are
    persisted before detection) — it must not be boosted."""
    sig = _sig("INTC", "bubble_forming", "reduce_exposure", 7)  # semis, bearish
    apply_cluster_boosts([sig], [_SEMIS_BEARISH_CLUSTER])       # members: AMD/NVDA/SMCI
    assert sig["confidence"] == 7
    assert "cluster_boost" not in sig


def test_boost_ignores_non_matching_sector_or_direction():
    other_sector = _sig("AAPL", "bubble_forming", "reduce_exposure", 7)   # mega_tech
    other_dir    = _sig("NVDA", "irrational_panic", "contrarian_buy", 7)  # bullish
    apply_cluster_boosts([other_sector, other_dir], [_SEMIS_BEARISH_CLUSTER])
    assert other_sector["confidence"] == 7
    assert other_dir["confidence"] == 7
    assert "cluster_boost" not in other_sector
    assert "cluster_boost" not in other_dir
