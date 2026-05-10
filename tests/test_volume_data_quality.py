"""Tests for Fix 3: suspicious volume guard in analyze_volume.

Asserts that signals with a volume multiple > 10x receive
data_quality: "suspicious_volume", and all others receive "ok".
"""

from __future__ import annotations

import pytest

from analyzers.volume_analyzer import analyze_volume


def _mkt(current: float, avg: float) -> dict:
    return {"current_volume": current, "avg_volume_30d": avg}


# ── happy-path ────────────────────────────────────────────────────────────────

def test_normal_volume_is_ok():
    result = analyze_volume(_mkt(1_000_000, 1_000_000))
    assert result["data_quality"] == "ok"
    assert result["classification"] == "normal"


def test_elevated_volume_is_ok():
    result = analyze_volume(_mkt(2_000_000, 1_000_000))
    assert result["data_quality"] == "ok"
    assert result["classification"] == "elevated"


def test_anomalous_volume_is_ok():
    result = analyze_volume(_mkt(3_500_000, 1_000_000))
    assert result["data_quality"] == "ok"
    assert result["classification"] == "anomalous"


def test_extreme_volume_below_10x_is_ok():
    result = analyze_volume(_mkt(9_900_000, 1_000_000))
    assert result["data_quality"] == "ok"
    assert result["classification"] == "extreme"


# ── boundary ──────────────────────────────────────────────────────────────────

def test_exactly_10x_is_ok():
    """The threshold is strictly > 10x; exactly 10.0x must NOT be flagged."""
    result = analyze_volume(_mkt(10_000_000, 1_000_000))
    assert result["ratio"] == 10.0
    assert result["data_quality"] == "ok"


# ── suspicious ────────────────────────────────────────────────────────────────

def test_just_above_10x_is_suspicious():
    result = analyze_volume(_mkt(10_000_001, 1_000_000))
    assert result["data_quality"] == "suspicious_volume"


def test_commodity_like_spike_is_suspicious():
    """Reproduces the GC=F / SI=F 46x pattern from May 7 production email."""
    result = analyze_volume(_mkt(46_000_000, 1_000_000))
    assert result["data_quality"] == "suspicious_volume"
    assert result["classification"] == "extreme"


def test_25x_is_suspicious():
    result = analyze_volume(_mkt(25_000_000, 1_000_000))
    assert result["data_quality"] == "suspicious_volume"


# ── edge: zero baseline ───────────────────────────────────────────────────────

def test_zero_baseline_returns_ok():
    """No division by zero; falls through to the early-return path."""
    result = analyze_volume(_mkt(1_000_000, 0))
    assert result["data_quality"] == "ok"
    assert result["ratio"] == 0.0
