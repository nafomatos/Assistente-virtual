"""Tests for strategy v2 short gates (claude_advisor/signal_gates.py) and the
v2 close-logic / aggregate changes (tracker/position_tracker.py).

Covers the spec's required test groups:
  1. Close logic: build_closed_record + aggregate correct = pnl > 0.
  2. vol_dist gate: bubble short with vol_dist<=1.0 → institutional_rebalancing/wait.
  3. Macro cap: bubble short at F&G=26 → confidence capped <=5; long uncapped.
  4. AI-hardware rule: semis + Buffett>200 + z200 elevated + vol_dist<1.0 → wait.
  5. Retrospective replay: 4 AI shorts blocked, 2 longs preserved.
"""

from __future__ import annotations

import pytest

from claude_advisor.signal_gates import (
    MACRO_BUBBLE_CONF_CAP,
    apply_short_gates,
    gate_signal,
)
from tracker.position_tracker import (
    _is_correct,
    build_closed_record,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

def _short(ticker="XYZ", conf=8):
    return {
        "ticker": ticker,
        "classification": "bubble_forming",
        "recommendation": "reduce_exposure",
        "reasoning": "high z, vol elevated",
        "confidence": conf,
    }


def _long(ticker="SOFI", conf=7):
    return {
        "ticker": ticker,
        "classification": "irrational_panic",
        "recommendation": "contrarian_buy",
        "reasoning": "capitulation",
        "confidence": conf,
    }


def _lh(vol_dist=None, ext=None, sustained=None):
    return {
        "volume_dist_ratio": vol_dist,
        "price_extension_200d": ext,
        "sustained_days_60": sustained,
    }


# A "clean" sustained bubble with real distribution — passes every reclassification
# gate, so only the macro cap can touch it.
_CLEAN_BUBBLE_LH = _lh(vol_dist=1.4, ext=0.90, sustained=45)
_BULL_MACRO = {"fear_greed": 60, "buffett": 150.0}
_FEAR_MACRO = {"fear_greed": 26, "buffett": 226.0}


# ── 2. vol_dist gate (PRIMARY) ───────────────────────────────────────────────

def test_vol_dist_below_one_reclassifies_to_wait():
    sig = _short()
    gate_signal(sig, _lh(vol_dist=0.6, ext=0.9, sustained=45), {"z_score_200d": 3.0}, _BULL_MACRO,
                sector="mega_tech")
    assert sig["classification"] == "institutional_rebalancing"
    assert sig["recommendation"] == "wait"
    assert sig["v2_gate"]["rule"] == "vol_dist"


def test_vol_dist_above_one_preserves_bubble():
    sig = _short()
    gate_signal(sig, _lh(vol_dist=1.4, ext=0.9, sustained=45), {"z_score_200d": 3.0}, _BULL_MACRO,
                sector="mega_tech")
    assert sig["classification"] == "bubble_forming"
    assert sig["recommendation"] == "reduce_exposure"
    assert "v2_gate" not in sig


def test_vol_dist_missing_treated_as_unconfirmed():
    sig = _short()
    gate_signal(sig, _lh(vol_dist=None, ext=0.9, sustained=45), {"z_score_200d": 3.0}, _BULL_MACRO,
                sector="mega_tech")
    assert sig["recommendation"] == "wait"


# ── 3. Macro fear cap ────────────────────────────────────────────────────────

def test_macro_cap_at_fear_caps_confidence():
    sig = _short(conf=9)
    gate_signal(sig, _CLEAN_BUBBLE_LH, {"z_score_200d": 3.0}, _FEAR_MACRO, sector="mega_tech")
    # Survives reclassification (clean bubble) but confidence is capped.
    assert sig["classification"] == "bubble_forming"
    assert sig["confidence"] == MACRO_BUBBLE_CONF_CAP
    assert sig["confidence"] <= 5
    assert sig["v2_gate"]["rule"] == "macro_fear_cap"


def test_macro_cap_does_not_touch_longs():
    sig = _long(conf=9)
    gate_signal(sig, _lh(), {}, _FEAR_MACRO, sector="fintech")
    assert sig["recommendation"] == "contrarian_buy"
    assert sig["confidence"] == 9      # uncapped
    assert "v2_gate" not in sig


def test_macro_cap_not_applied_in_greed_regime():
    sig = _short(conf=8)
    gate_signal(sig, _CLEAN_BUBBLE_LH, {"z_score_200d": 3.0}, _BULL_MACRO, sector="mega_tech")
    assert sig["confidence"] == 8      # F&G 60 ≥ 35 → no cap


# ── 4. AI-hardware-in-bull rule ──────────────────────────────────────────────

def test_ai_hardware_reclassifies_to_wait():
    sig = _short(ticker="SMCI", conf=9)
    gate_signal(sig, _lh(vol_dist=0.6, ext=0.28, sustained=0), {"z_score_200d": 4.8},
                {"fear_greed": 46, "buffett": 228.0}, sector="semis")
    assert sig["classification"] == "institutional_rebalancing"
    assert sig["recommendation"] == "wait"
    assert sig["v2_gate"]["rule"] == "ai_hardware_bull"


def test_ai_hardware_rule_requires_buffett_over_200():
    # Same signal but Buffett < 200 → AI-hw rule does not arm; falls through to
    # the vol_dist gate (still reclassifies, but via a different rule).
    sig = _short(ticker="SMCI", conf=9)
    gate_signal(sig, _lh(vol_dist=0.6, ext=0.28, sustained=0), {"z_score_200d": 4.8},
                {"fear_greed": 46, "buffett": 150.0}, sector="semis")
    assert sig["recommendation"] == "wait"
    assert sig["v2_gate"]["rule"] == "vol_dist"


# ── sustained-extension gate ─────────────────────────────────────────────────

def test_sustained_gate_blocks_fresh_breakout():
    # vol_dist passes (>1.0) but the name is a fresh breakout (low ext, 0 sustained).
    sig = _short()
    gate_signal(sig, _lh(vol_dist=1.6, ext=0.20, sustained=2), {"z_score_200d": 5.0}, _BULL_MACRO,
                sector="mega_tech")
    assert sig["recommendation"] == "wait"
    assert sig["v2_gate"]["rule"] == "sustained_extension"


def test_sustained_gate_passes_real_sustained_bubble():
    sig = _short()
    gate_signal(sig, _lh(vol_dist=1.6, ext=0.90, sustained=45), {"z_score_200d": 5.0}, _BULL_MACRO,
                sector="mega_tech")
    assert sig["classification"] == "bubble_forming"


def test_index_uses_lower_extension_threshold():
    # An ETF at +50% extension passes (index threshold 0.40), where a single
    # name would fail (single threshold 0.60).
    sig = _short(ticker="QQQ")
    gate_signal(sig, _lh(vol_dist=1.6, ext=0.50, sustained=45), {"z_score_200d": 5.0}, _BULL_MACRO,
                sector="etfs_broad")
    assert sig["classification"] == "bubble_forming"


# ── 5. Retrospective replay ──────────────────────────────────────────────────

def _result(ticker, lh, z200):
    return {"ticker": ticker, "signals": {"market": {"long_horizon": lh},
                                          "velocity": {"z_score_200d": z200}}}


def test_retrospective_replay_blocks_ai_shorts_preserves_longs():
    """Replay the May-2026 cohort through the gates with retrospective-derived
    long-horizon values. The 4 AI-hardware shorts must be blocked; the 2 longs
    must survive untouched.
    """
    signals = [
        _short("MU", 6),
        _short("AMD", 8),
        _short("SMCI", 9),
        _short("NBIS", 8),
        _long("SOFI", 7),
        _long("HOOD", 7),
    ]
    results = [
        # vol_dist all < 1.0 (buying pressure) per the retrospective.
        _result("MU",   _lh(vol_dist=0.47, ext=0.96, sustained=45), 2.5),
        _result("AMD",  _lh(vol_dist=0.55, ext=0.81, sustained=24), 4.2),
        _result("SMCI", _lh(vol_dist=0.62, ext=0.28, sustained=0),  4.8),
        _result("NBIS", _lh(vol_dist=0.80, ext=0.18, sustained=3),  2.0),
        _result("SOFI", _lh(vol_dist=0.77, ext=-0.21, sustained=0), -4.3),
        _result("HOOD", _lh(vol_dist=0.30, ext=-0.09, sustained=0), -3.0),
    ]
    # AI-hardware shorts entered at F&G 40-50 (≥35) → blocked by vol_dist /
    # AI-hardware / sustained gates, not the macro cap.
    macro = {"fear_greed": 46, "buffett": 226.0}

    gated = apply_short_gates(signals, results, macro)
    by_ticker = {s["ticker"]: s for s in gated}

    # The 4 AI-hardware shorts are all reclassified to a non-actionable wait.
    for t in ("MU", "AMD", "SMCI", "NBIS"):
        assert by_ticker[t]["recommendation"] == "wait", t
        assert by_ticker[t]["classification"] == "institutional_rebalancing", t

    # The 2 longs are preserved exactly.
    for t in ("SOFI", "HOOD"):
        assert by_ticker[t]["recommendation"] == "contrarian_buy", t
        assert by_ticker[t]["classification"] == "irrational_panic", t
        assert "v2_gate" not in by_ticker[t], t


def test_replay_new_hit_rate_is_longs_only():
    """After gating, the only actionable positions are the 2 winning longs →
    hypothetical hit rate 2/2 = 100%, versus the V1 actual that included 5+ losers.
    """
    signals = [_short("MU", 6), _short("AMD", 8), _short("SMCI", 9), _short("NBIS", 8),
               _long("SOFI", 7), _long("HOOD", 7)]
    results = [
        _result("MU",   _lh(vol_dist=0.47, ext=0.96, sustained=45), 2.5),
        _result("AMD",  _lh(vol_dist=0.55, ext=0.81, sustained=24), 4.2),
        _result("SMCI", _lh(vol_dist=0.62, ext=0.28, sustained=0),  4.8),
        _result("NBIS", _lh(vol_dist=0.80, ext=0.18, sustained=3),  2.0),
        _result("SOFI", _lh(vol_dist=0.77, ext=-0.21, sustained=0), -4.3),
        _result("HOOD", _lh(vol_dist=0.30, ext=-0.09, sustained=0), -3.0),
    ]
    gated = apply_short_gates(signals, results, {"fear_greed": 46, "buffett": 226.0})
    actionable = [s for s in gated
                  if s["recommendation"] in ("contrarian_buy", "reduce_exposure")]
    assert {s["ticker"] for s in actionable} == {"SOFI", "HOOD"}


# ── 1. Close logic + aggregate correct = pnl > 0 ─────────────────────────────

def _open_pos(ticker, direction, entry, entry_date="2026-05-05"):
    return {
        "id": f"id-{ticker}",
        "ticker": ticker,
        "direction": direction,
        "recommendation": "reduce_exposure" if direction == "short" else "contrarian_buy",
        "confidence": 7,
        "reasoning": "x",
        "entry_date": entry_date,
        "entry_price": entry,
        "macro_context": {},
    }


def test_build_closed_record_short_stop():
    pos = _open_pos("MU", "short", 640.20)
    rec = build_closed_record(pos, exit_price=800.25, exit_date="2026-05-13",
                              exit_reason="STOPPED_OUT")
    assert rec["exit_reason"] == "STOPPED_OUT"
    assert rec["exit_price"] == 800.25
    assert rec["realized_pnl_pct"] == pytest.approx(-25.0, abs=0.1)
    assert rec["days_held"] == 8
    assert _is_correct(rec) is False


def test_build_closed_record_long_winner():
    pos = _open_pos("HOOD", "long", 71.20, entry_date="2026-04-29")
    rec = build_closed_record(pos, exit_price=94.30, exit_date="2026-05-29",
                              exit_reason="CLOSED_D30")
    assert rec["realized_pnl_pct"] == pytest.approx(32.44, abs=0.1)
    assert _is_correct(rec) is True


def test_build_closed_record_unknown_when_no_price():
    pos = _open_pos("RDDT", "short", 166.48, entry_date="2026-05-01")
    rec = build_closed_record(pos, exit_price=None, exit_date="2026-05-31",
                              exit_reason="CLOSED_D30")
    assert rec["realized_pnl_pct"] is None
    assert rec["outcome"] == "unknown"
    assert _is_correct(rec) is False


def test_aggregate_correct_uses_pnl_sign(tmp_path, monkeypatch):
    """get_aggregate_stats counts correct = realized_pnl > 0, reading the
    persisted closed list (a +1.5% short is 'correct' under v2 even though the
    old ±2% band would have called it 'neutral')."""
    import json
    import tracker.position_tracker as pt

    state = {
        "open": [],
        "closed": [
            {"ticker": "A", "recommendation": "reduce_exposure", "confidence": 7,
             "realized_pnl_pct": 1.5, "pnl_pct": 1.5, "outcome": "neutral"},
            {"ticker": "B", "recommendation": "reduce_exposure", "confidence": 7,
             "realized_pnl_pct": -25.0, "pnl_pct": -25.0, "outcome": "incorrect"},
            {"ticker": "C", "recommendation": "contrarian_buy", "confidence": 7,
             "realized_pnl_pct": 32.0, "pnl_pct": 32.0, "outcome": "correct"},
            {"ticker": "D", "recommendation": "reduce_exposure", "confidence": 7,
             "realized_pnl_pct": None, "pnl_pct": None, "outcome": "unknown"},
        ],
    }
    pfile = tmp_path / "positions.json"
    pfile.write_text(json.dumps(state))
    monkeypatch.setattr(pt, "POSITIONS_FILE", pfile)

    stats = pt.get_aggregate_stats()
    assert stats["total"] == 4
    assert stats["correct"] == 2          # A (+1.5) and C (+32)
    assert stats["incorrect"] == 1        # B
    assert stats["neutral"] == 1          # D (no determinable price)
    # win rate over determined outcomes: 2 of 3
    assert stats["win_rate"] == pytest.approx(66.7, abs=0.1)
