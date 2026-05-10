"""Tests for analyzers/position_sizing.py.

Ten deterministic cases covering the full sizing formula, macro dampener
edge-cases, price-target reversion math, and option strike directions.
"""

from __future__ import annotations

import datetime

import pytest

from analyzers.position_sizing import (
    compute_option_strikes,
    compute_position_size,
    compute_price_targets,
    compute_sizing_block,
    compute_time_windows,
)


# ── fixtures ──────────────────────────────────────────────────────────────

def _sig(confidence: int, rec: str, cluster: bool = False) -> dict:
    s: dict = {"confidence": confidence, "recommendation": rec}
    if cluster:
        s["cluster_boost"] = {"boost_amount": 1}
    return s


def _macro(buffett: float = 150.0, fg: int = 60) -> dict:
    return {"buffett_indicator": buffett, "fear_greed": fg}


# ── test 1 ────────────────────────────────────────────────────────────────

def test_confidence_below_6_returns_zero():
    """Confidence < 6 → position size must be 0 regardless of recommendation."""
    assert compute_position_size(_sig(5, "contrarian_buy"), _macro()) == 0.0
    assert compute_position_size(_sig(1, "reduce_exposure"), _macro()) == 0.0


# ── test 2 ────────────────────────────────────────────────────────────────

def test_confidence_6_reduce_exposure_no_cluster_no_macro_damp():
    """conf=6, reduce_exposure, no cluster, no dampener → 1.0 × 1.0 × 1.0 × 1.0 = 1.0%."""
    result = compute_position_size(_sig(6, "reduce_exposure"), _macro())
    assert result == pytest.approx(1.0)


# ── test 3 ────────────────────────────────────────────────────────────────

def test_confidence_9_contrarian_buy_cluster_no_macro_damp():
    """conf=9, contrarian_buy, cluster boost, no dampener → 3 × 1.2 × 1.25 × 1.0 = 4.5%."""
    result = compute_position_size(_sig(9, "contrarian_buy", cluster=True), _macro())
    assert result == pytest.approx(4.5)


# ── test 4 ────────────────────────────────────────────────────────────────

def test_confidence_8_reduce_exposure_no_cluster_with_macro_damp():
    """conf=8, reduce_exposure, no cluster, buffett=231 → 2 × 1.0 × 1.0 × 0.7 = 1.4%."""
    result = compute_position_size(_sig(8, "reduce_exposure"), _macro(buffett=231))
    assert result == pytest.approx(1.4)


# ── test 5 ────────────────────────────────────────────────────────────────

def test_macro_dampener_triggers_on_buffett_alone():
    """Buffett > 220 alone (F&G normal at 60) → dampener fires → 0.7 multiplier."""
    macro = _macro(buffett=221, fg=60)
    result = compute_position_size(_sig(7, "contrarian_buy"), macro)
    assert result == pytest.approx(2.0 * 1.2 * 1.0 * 0.7)


# ── test 6 ────────────────────────────────────────────────────────────────

def test_macro_dampener_triggers_on_fear_greed_alone():
    """F&G < 40 alone (Buffett normal at 150) → dampener fires → 0.7 multiplier."""
    macro = _macro(buffett=150, fg=39)
    result = compute_position_size(_sig(7, "contrarian_buy"), macro)
    assert result == pytest.approx(2.0 * 1.2 * 1.0 * 0.7)


# ── test 7 ────────────────────────────────────────────────────────────────

def test_macro_dampener_does_not_trigger_at_boundary():
    """Buffett = 220 (not > 220) AND F&G = 40 (not < 40) → dampener does NOT fire."""
    macro = _macro(buffett=220, fg=40)
    result = compute_position_size(_sig(7, "contrarian_buy"), macro)
    assert result == pytest.approx(2.0 * 1.2 * 1.0 * 1.0)


# ── test 8 ────────────────────────────────────────────────────────────────

def test_recommendation_wait_returns_zero():
    """Non-directional recommendations (wait, no_action) always return 0."""
    assert compute_position_size(_sig(9, "wait"),      _macro()) == 0.0
    assert compute_position_size(_sig(9, "no_action"), _macro()) == 0.0


# ── test 9 ────────────────────────────────────────────────────────────────

def test_price_target_reversion_math():
    """P=100, Z=+2, returns_std=0.05 → S=5, M=90; reduce_exposure targets: 95/90/85."""
    targets = compute_price_targets(
        current_price=100.0,
        z_score_30d=2.0,
        returns_std_30d=0.05,
        recommendation="reduce_exposure",
    )
    assert targets["conservative"] == pytest.approx(95.0)  # M + S = 90 + 5
    assert targets["medium"]       == pytest.approx(90.0)  # M     = 90
    assert targets["aggressive"]   == pytest.approx(85.0)  # M - S = 90 - 5
    assert targets["is_bearish"] is True


# ── test 10 ───────────────────────────────────────────────────────────────

def test_option_strikes_short_signal():
    """Short (reduce_exposure) at $100 → ATM=$100, OTM5%=$95, OTM10%=$90."""
    strikes = compute_option_strikes(
        current_price=100.0,
        recommendation="reduce_exposure",
    )
    assert strikes["atm"]       == 100
    assert strikes["otm_5pct"]  == 95
    assert strikes["otm_10pct"] == 90


# ── extras: sanity checks for contrarian_buy direction ────────────────────

def test_price_target_bullish_direction():
    """Bullish targets are symmetric mirror of bearish: P=100, Z=-2, std=0.05."""
    targets = compute_price_targets(
        current_price=100.0,
        z_score_30d=-2.0,
        returns_std_30d=0.05,
        recommendation="contrarian_buy",
    )
    # S=5, M = 100 - (-2)*5 = 110
    assert targets["conservative"] == pytest.approx(105.0)  # M - S = 110 - 5
    assert targets["medium"]       == pytest.approx(110.0)  # M     = 110
    assert targets["aggressive"]   == pytest.approx(115.0)  # M + S = 110 + 5
    assert targets["is_bearish"] is False


def test_option_strikes_long_signal():
    """Long (contrarian_buy) at $100 → OTM strikes above price."""
    strikes = compute_option_strikes(100.0, "contrarian_buy")
    assert strikes["atm"]       == 100
    assert strikes["otm_5pct"]  == 105
    assert strikes["otm_10pct"] == 110


def test_compute_sizing_block_returns_none_for_low_confidence():
    """compute_sizing_block returns None when position_size=0."""
    classified = {"confidence": 4, "recommendation": "contrarian_buy", "ticker": "NVDA"}
    market     = {"current_price": 100.0, "returns_std_30d": 0.02}
    velocity   = {"z_score_30d": 1.5}
    macro      = {"buffett_indicator": 150, "fear_greed": 60}
    assert compute_sizing_block(classified, market, velocity, macro) is None


def test_compute_sizing_block_full_output():
    """compute_sizing_block returns a well-formed dict for an actionable signal."""
    classified = {"confidence": 7, "recommendation": "contrarian_buy", "ticker": "NVDA"}
    market     = {"current_price": 200.0, "returns_std_30d": 0.025}
    velocity   = {"z_score_30d": -1.5}
    macro      = {"buffett_indicator": 150, "fear_greed": 60}
    today      = datetime.date(2026, 5, 10)

    block = compute_sizing_block(classified, market, velocity, macro, today=today)
    assert block is not None
    assert block["position_size_pct"] == pytest.approx(2.0 * 1.2 * 1.0 * 1.0)
    assert "targets"  in block
    assert "strikes"  in block
    assert "windows"  in block
    assert block["windows"]["d10"] == "2026-05-20"  # 10 days from 2026-05-10 = 2026-05-20 (Wed)
    assert block["windows"]["d30"] == "2026-06-09"


def test_time_windows_skips_weekend():
    """d+10 from a Thursday that lands on Saturday → bumped to Monday."""
    # 2026-05-07 (Thursday) + 10 = 2026-05-17 (Sunday) → bumped to 2026-05-18 (Monday)
    windows = compute_time_windows(datetime.date(2026, 5, 7))
    assert windows["d10"] == "2026-05-18"
    assert windows["d30"] == "2026-06-06"
