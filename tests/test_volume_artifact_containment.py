"""Tests for the 2026-06-09 fixes: buy-confidence floor (Fix A), volume-artifact
containment (Fix B), and null-data SKIP (Fix C).

Real-data context (logs/2026-06-09.txt, logs/signals_2026-06-09.json):
  - SI=F was emitted as actionable contrarian_buy at confidence 5/10, citing
    "Volume 43.2x (possible artifact, but directional)" and vol_dist 58.84.
  - GC=F 11.81x / SI=F 43.22x / HG=F 25.4x all carried the suspicious_volume
    flag; GC=F vol_dist 11.00 and SI=F vol_dist 58.84 were pure roll artifacts.
  - SPCX rendered RED with vol=nanx, z30=0, z200=0, RSI=n/a, no 200d history.
"""

from __future__ import annotations

import datetime as dt

from analyzers.volume_quality import (
    log_artifact_summary,
    sanitize_volume_artifacts,
)
from claude_advisor.prompts import SYSTEM_PROMPT
from claude_advisor.signal_gates import apply_short_gates, gate_signal
from output.document_builder import get_alert_tier, get_tier_reason, is_null_data
from utils.token_optimizer import compress_signals

_DATE = dt.date(2026, 6, 9)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _signals(
    vol_ratio=2.0,
    vol_class="elevated",
    data_quality="ok",
    z30=0.5,
    z200=0.5,
    rsi=50.0,
    vol_dist=0.8,
    ext=0.1,
    sustained=0,
) -> dict:
    return {
        "market": {
            "current_price": 100.0,
            "daily_return_pct": 1.0,
            "recent_news": [],
            "long_horizon": {
                "price_extension_200d": ext,
                "sustained_days_60": sustained,
                "return_6m": 0.1,
                "acceleration_ratio": 0.2,
                "volume_dist_ratio": vol_dist,
                "drawdown_from_peak_2y": -0.05,
                "days_since_peak_2y": 10,
            },
        },
        "volume": {
            "classification": vol_class,
            "ratio": vol_ratio,
            "data_quality": data_quality,
        },
        "velocity": {
            "classification": "normal",
            "z_score_30d": z30,
            "z_score_200d": z200,
            "direction": "up",
            "macro_extreme": False,
        },
        "rsi": {"rsi": rsi, "classification": "normal"},
        "sentiment": None,
    }


def _buy(ticker="SI=F", conf=5):
    return {
        "ticker": ticker,
        "classification": "irrational_panic",
        "recommendation": "contrarian_buy",
        "reasoning": "test",
        "confidence": conf,
    }


def _short(ticker="GC=F", conf=8):
    return {
        "ticker": ticker,
        "classification": "bubble_forming",
        "recommendation": "reduce_exposure",
        "reasoning": "test",
        "confidence": conf,
    }


# ── 1. Fix A: buy-confidence floor ────────────────────────────────────────────

def test_buy_below_floor_downgraded_to_wait():
    sig = _buy(conf=5)
    gate_signal(sig, {}, {}, {"fear_greed": 10, "buffett": 200.0}, sector=None)
    assert sig["recommendation"] == "wait"
    assert sig["classification"] == "irrational_panic"   # observation survives
    assert sig["v2_gate"]["rule"] == "buy_conf_floor"
    assert sig["v2_gate"]["original_confidence"] == 5


def test_buy_at_floor_stays_actionable():
    sig = _buy(conf=7)
    gate_signal(sig, {}, {}, {"fear_greed": 10, "buffett": 200.0}, sector=None)
    assert sig["recommendation"] == "contrarian_buy"
    assert "v2_gate" not in sig


def test_buy_floor_applies_through_batch_path():
    """apply_short_gates (the function main.py calls) enforces the floor."""
    signals = [_buy("SI=F", 5), _buy("SOFI", 8)]
    apply_short_gates(signals, [], {"fear_greed": 10})
    by = {s["ticker"]: s for s in signals}
    assert by["SI=F"]["recommendation"] == "wait"
    assert by["SOFI"]["recommendation"] == "contrarian_buy"


# ── 2. Fix B: artifact nulling ────────────────────────────────────────────────

def test_artifact_nulls_vol_dist_and_preserves_raw(tmp_path):
    s = _signals(vol_ratio=43.22, vol_class="extreme",
                 data_quality="suspicious_volume", vol_dist=58.84)
    flagged = sanitize_volume_artifacts("SI=F", s, _DATE, logs_dir=str(tmp_path))
    assert flagged is True
    lh = s["market"]["long_horizon"]
    assert lh["volume_dist_ratio"] is None          # gate payload nulled
    assert lh["raw_volume_dist_ratio"] == 58.84     # raw kept for the log/human
    assert s["volume"]["artifact"] is True
    assert s["volume"]["raw_ratio"] == 43.22


def test_clean_ticker_untouched(tmp_path):
    s = _signals(vol_ratio=2.0, data_quality="ok", vol_dist=1.4)
    flagged = sanitize_volume_artifacts("NVDA", s, _DATE, logs_dir=str(tmp_path))
    assert flagged is False
    assert s["market"]["long_horizon"]["volume_dist_ratio"] == 1.4
    assert "artifact" not in s["volume"]


# ── 3. Fix B: artifact-poisoned vol_dist cannot pass the short gate ───────────

def test_poisoned_vol_dist_cannot_pass_short_gate(tmp_path):
    """A commodity with raw vol_dist 58.84 (pure artifact) + suspicious flag:
    after containment the bubble short is reclassified to wait — the 58.84
    can no longer wave it through the distribution gate."""
    s = _signals(vol_ratio=43.22, vol_class="extreme",
                 data_quality="suspicious_volume",
                 vol_dist=58.84, ext=0.9, sustained=45, z200=3.0)
    sanitize_volume_artifacts("SI=F", s, _DATE, logs_dir=str(tmp_path))

    short = _short("SI=F", conf=8)
    results = [{"ticker": "SI=F", "signals": s}]
    apply_short_gates([short], results, {"fear_greed": 60, "buffett": 150.0})
    assert short["recommendation"] == "wait"
    assert short["classification"] == "institutional_rebalancing"
    assert short["v2_gate"]["rule"] == "vol_dist"


def test_unpoisoned_vol_dist_still_passes_short_gate():
    """Control: the same setup WITHOUT the artifact flag still passes — the
    gate itself is unchanged; only the data feeding it is sanitized."""
    s = _signals(vol_ratio=3.0, vol_class="anomalous", data_quality="ok",
                 vol_dist=1.4, ext=0.9, sustained=45, z200=3.0)
    short = _short("XYZ", conf=8)
    results = [{"ticker": "XYZ", "signals": s}]
    apply_short_gates([short], results, {"fear_greed": 60, "buffett": 150.0})
    assert short["recommendation"] == "reduce_exposure"


# ── 4. Fix B: prompt instruction ──────────────────────────────────────────────

def test_prompt_forbids_citing_nulled_volume():
    assert "suspected data artifact" in SYSTEM_PROMPT
    assert "UNRELIABLE and set to null" in SYSTEM_PROMPT
    assert "Do not use them as evidence for any directional call" in SYSTEM_PROMPT
    assert "price velocity (z-scores), RSI, long-horizon extension, and social signals only" in SYSTEM_PROMPT


# ── 5. Fix B: artifact logging ────────────────────────────────────────────────

def test_artifact_log_written(tmp_path):
    s = _signals(vol_ratio=43.22, vol_class="extreme",
                 data_quality="suspicious_volume", vol_dist=58.84)
    sanitize_volume_artifacts("SI=F", s, _DATE, logs_dir=str(tmp_path))
    log_artifact_summary(_DATE, ["SI=F"], logs_dir=str(tmp_path))

    content = (tmp_path / "volume_artifacts.log").read_text()
    assert "2026-06-09 | SI=F | raw_vol_multiple=43.22x | raw_vol_dist=58.84" in content
    assert "2026-06-09 | SUMMARY | count=1 | tickers=SI=F" in content


def test_artifact_log_suppressed_in_debug_mode(tmp_path):
    s = _signals(vol_ratio=43.22, vol_class="extreme",
                 data_quality="suspicious_volume", vol_dist=58.84)
    flagged = sanitize_volume_artifacts(
        "SI=F", s, _DATE, logs_dir=str(tmp_path), write_log=False
    )
    assert flagged is True                                  # nulling still applies
    assert not (tmp_path / "volume_artifacts.log").exists() # but no state write


# ── 6. Fix B: report rendering ────────────────────────────────────────────────

def test_report_renders_investigation_flag(tmp_path):
    s = _signals(vol_ratio=43.22, vol_class="extreme",
                 data_quality="suspicious_volume", vol_dist=58.84)
    sanitize_volume_artifacts("SI=F", s, _DATE, logs_dir=str(tmp_path))
    body = compress_signals("SI=F", "Silver", s)

    assert "VOLUME DATA UNRELIABLE" in body
    assert "NEEDS INVESTIGATION" in body
    assert "contract-roll artifact suspected" in body
    # Volume line nulled in the classifier payload — no multiple to cite
    assert "- Volume: n/a (suspected data artifact — excluded from analysis)" in body
    assert "extreme (43.22x 30d avg)" not in body
    # vol_dist line nulled too
    assert "58.84" not in body
    # The pre-existing DATA QUALITY badge is kept (raw value, human context)
    assert "DATA QUALITY FLAG" in body


def test_report_clean_ticker_renders_volume_normally():
    s = _signals(vol_ratio=3.1, vol_class="anomalous", data_quality="ok")
    body = compress_signals("NVDA", "Nvidia", s)
    assert "- Volume: anomalous (3.1x 30d avg)" in body
    assert "VOLUME DATA UNRELIABLE" not in body


# ── 7. Fix C: null-data SKIP ──────────────────────────────────────────────────

def _spcx_signals():
    s = _signals(vol_ratio=float("nan"), vol_class="extreme", data_quality="ok",
                 z30=0.0, z200=0.0, rsi=None, vol_dist=None)
    s["market"]["long_horizon"]["price_extension_200d"] = None
    return s


def test_null_data_ticker_is_skip_not_red():
    s = _spcx_signals()
    assert is_null_data(s) is True
    assert get_alert_tier(s) is None
    assert "null data" in get_tier_reason(s)


def test_real_extreme_volume_still_red():
    """Control: a genuine extreme-volume ticker still triggers RED."""
    s = _signals(vol_ratio=6.0, vol_class="extreme", data_quality="ok")
    assert is_null_data(s) is False
    assert get_alert_tier(s) == "red"


def test_zero_z_with_real_volume_not_null_data():
    s = _signals(vol_ratio=1.2, vol_class="normal", z30=0.0, z200=0.0)
    assert is_null_data(s) is False


# ── 8. Replay 2026-06-09 ──────────────────────────────────────────────────────

def _replay_results(tmp_path):
    """Reconstruct the five 2026-06-09 tickers with real logged values and run
    them through the containment exactly as run_pipeline does."""
    data = {
        # ticker: (ratio, class, dq, z30, z200, rsi, vol_dist, ext, sustained)
        "AAPL": (1.3, "normal", "ok", -2.6, -1.0, 35.0, 0.9, -0.05, 0),
        "SPCX": (float("nan"), "extreme", "ok", 0.0, 0.0, None, None, None, None),
        "GC=F": (11.81, "extreme", "suspicious_volume", -0.69, -0.72, 31.1, 11.00, -0.028, 0),
        "SI=F": (43.22, "extreme", "suspicious_volume", -1.17, -1.06, 29.5, 58.84, -0.020, 3),
        "HG=F": (25.4, "extreme", "suspicious_volume", 0.08, 0.09, 52.0, 0.15, 0.154, 0),
    }
    results = []
    artifact_tickers = []
    for ticker, (ratio, vc, dq, z30, z200, rsi, vd, ext, sus) in data.items():
        s = _signals(vol_ratio=ratio, vol_class=vc, data_quality=dq,
                     z30=z30, z200=z200, rsi=rsi, vol_dist=vd,
                     ext=ext, sustained=sus)
        if ext is None:
            s["market"]["long_horizon"]["price_extension_200d"] = None
        if sanitize_volume_artifacts(ticker, s, _DATE, logs_dir=str(tmp_path)):
            artifact_tickers.append(ticker)
        results.append({"ticker": ticker, "signals": s})
    if artifact_tickers:
        log_artifact_summary(_DATE, artifact_tickers, logs_dir=str(tmp_path))
    return results, artifact_tickers


def _replay_signals():
    """The actual classified signals from logs/signals_2026-06-09.json."""
    return [
        {"ticker": "AAPL", "classification": "ambiguous",
         "recommendation": "wait", "confidence": 3},
        {"ticker": "SPCX", "classification": "ambiguous",
         "recommendation": "wait", "confidence": 1},
        {"ticker": "GC=F", "classification": "institutional_rebalancing",
         "recommendation": "wait", "confidence": 4},
        _buy("SI=F", 5),
        {"ticker": "HG=F", "classification": "institutional_rebalancing",
         "recommendation": "wait", "confidence": 4},
    ]


def test_replay_20260609_zero_actionable(tmp_path):
    results, artifact_tickers = _replay_results(tmp_path)
    signals = _replay_signals()

    # Macro on 2026-06-09: Fear & Greed 10 (extreme fear).
    apply_short_gates(signals, results, {"fear_greed": 10, "buffett": 200.0})

    by = {s["ticker"]: s for s in signals}
    # SI=F conf-5 buy is downgraded — no longer actionable.
    assert by["SI=F"]["recommendation"] == "wait"
    assert by["SI=F"]["v2_gate"]["rule"] == "buy_conf_floor"

    actionable = [s for s in signals
                  if s["recommendation"] in ("contrarian_buy", "reduce_exposure")]
    assert actionable == []          # 0 actionable for the day

    # All three metals flagged + logged.
    assert artifact_tickers == ["GC=F", "SI=F", "HG=F"]
    log = (tmp_path / "volume_artifacts.log").read_text()
    for t in ("GC=F", "SI=F", "HG=F"):
        assert f"| {t} |" in log
    assert "SUMMARY | count=3" in log

    # SPCX is SKIP, not RED.
    spcx = next(r for r in results if r["ticker"] == "SPCX")
    assert get_alert_tier(spcx["signals"]) is None

    # Metals keep their AMBER tier (tier-suppression path unchanged) but their
    # vol_dist is nulled so no poisoned value can reach the short gate.
    for t in ("GC=F", "SI=F", "HG=F"):
        r = next(x for x in results if x["ticker"] == t)
        assert get_alert_tier(r["signals"]) == "amber"
        assert r["signals"]["market"]["long_horizon"]["volume_dist_ratio"] is None


def test_replay_20260609_hypothetical_poisoned_short_blocked(tmp_path):
    """Even if the classifier HAD issued a bubble short on SI=F (vol_dist
    58.84 would sail through > 1.0), containment blocks it."""
    results, _ = _replay_results(tmp_path)
    short = _short("SI=F", conf=8)
    apply_short_gates([short], results, {"fear_greed": 60, "buffett": 150.0})
    assert short["recommendation"] == "wait"
    assert short["v2_gate"]["rule"] == "vol_dist"
