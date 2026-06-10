"""Tests for the metal ETF root-cause swap (Fix D): GC=F→GLD, SI=F→SLV,
HG=F→COPX. ETFs have no contract rolls, so their volume is real and the v2
vol_dist short gate genuinely applies to the metals again.
"""

from __future__ import annotations

import datetime as dt
import json

from analyzers.volume_analyzer import analyze_volume
from claude_advisor.prompts import SYSTEM_PROMPT
from claude_advisor.signal_gates import apply_short_gates
from config import ALL_TICKERS, COMMODITIES, TICKER_NAMES
from config.ticker_manager import ORIGINAL_18
from tracker.cluster_detector import detect_clusters
from tracker.sectors import get_sector

OLD_FUTURES = {"GC=F", "SI=F", "HG=F"}
NEW_ETFS    = {"GLD", "SLV", "COPX"}


# ── 9. Universe swap ──────────────────────────────────────────────────────────

def test_universe_contains_etfs_not_futures():
    assert NEW_ETFS <= set(COMMODITIES)
    assert not (OLD_FUTURES & set(COMMODITIES))
    assert not (OLD_FUTURES & set(ALL_TICKERS))
    assert NEW_ETFS <= ORIGINAL_18
    assert not (OLD_FUTURES & ORIGINAL_18)


def test_active_tickers_state_swapped():
    with open("config/active_tickers.json", encoding="utf-8") as fh:
        state = json.load(fh)
    permanent = set(state["permanent"])
    assert NEW_ETFS <= permanent
    assert not (OLD_FUTURES & permanent)


# ── 11. Copper decision: COPX, consistently ──────────────────────────────────

def test_copper_proxy_is_copx_everywhere():
    """COPX chosen over CPER (CPER's volume is too thin for the volume-based
    signal model). The choice must be consistent across config and sectors."""
    assert "COPX" in COMMODITIES
    assert "CPER" not in COMMODITIES
    assert "CPER" not in ALL_TICKERS
    assert "COPX" in TICKER_NAMES
    assert get_sector("COPX") == "commodities_metals"


def test_etf_display_names():
    assert TICKER_NAMES["GLD"] == "Gold (GLD)"
    assert TICKER_NAMES["SLV"] == "Silver (SLV)"
    assert "Copper" in TICKER_NAMES["COPX"]


# ── 12. Artifact flag dormant on normal ETF-like data ─────────────────────────

def test_artifact_flag_dormant_on_normal_volume():
    """GLD-like normal day (volume ≈ baseline) must not trip the flag."""
    result = analyze_volume({"current_volume": 8_000_000, "avg_volume_30d": 7_500_000})
    assert result["data_quality"] == "ok"
    assert result["classification"] == "normal"


def test_artifact_flag_dormant_on_real_news_spike():
    """A genuine 4x news-day spike stays below the artifact threshold."""
    result = analyze_volume({"current_volume": 30_000_000, "avg_volume_30d": 7_500_000})
    assert result["data_quality"] == "ok"
    assert result["classification"] == "anomalous"


def test_artifact_flag_still_arms_on_artifact_signature():
    """Safety net kept: a 40x multiple still trips suspicious_volume even on
    the new symbols — if an ETF ever shows the signature, we want to see it."""
    result = analyze_volume({"current_volume": 300_000_000, "avg_volume_30d": 7_500_000})
    assert result["data_quality"] == "suspicious_volume"


# ── 13. SECTOR_MAP: metals cluster under the new symbols ──────────────────────

def test_new_metals_map_to_commodities_metals():
    for t in NEW_ETFS:
        assert get_sector(t) == "commodities_metals", t


def test_legacy_futures_still_map_for_window_continuity():
    """Old symbols stay mapped so signals files from before the swap keep
    clustering during the rolling window and in backtests."""
    for t in OLD_FUTURES:
        assert get_sector(t) == "commodities_metals", t


def test_metals_cluster_forms_under_new_symbols(tmp_path):
    sigs = [
        {"ticker": t, "classification": "bubble_forming",
         "recommendation": "reduce_exposure", "confidence": 7}
        for t in ("GLD", "SLV", "COPX")
    ]
    path = tmp_path / "signals_2026-06-10.json"
    path.write_text(json.dumps({"date": "2026-06-10", "signals": sigs}))
    clusters = detect_clusters(
        days_window=5, logs_dir=str(tmp_path), reference_date=dt.date(2026, 6, 10)
    )
    assert len(clusters) == 1
    assert clusters[0]["sector"] == "commodities_metals"
    assert set(clusters[0]["tickers"]) == NEW_ETFS


# ── 14. No stray functional references ────────────────────────────────────────

def test_prompt_references_new_symbols():
    assert "GLD, SLV, COPX" in SYSTEM_PROMPT
    # The retired symbols must not be presented as the live commodity universe.
    assert "GC=F, SI=F, CL=F, HG=F" not in SYSTEM_PROMPT


def test_youtube_domain_keywords_cover_new_symbols():
    from collectors.youtube_sentiment import _COMMODITY_DOMAIN
    for t in NEW_ETFS:
        assert t in _COMMODITY_DOMAIN, t


# ── 15. The vol_dist short gate genuinely applies to metals again ─────────────

def test_metal_with_real_distribution_can_reach_bubble_forming():
    """A metal ETF with REAL vol_dist > 1.0 + sustained extension + non-fear
    macro passes every reclassification gate — proving metals are no longer
    auto-excluded from the short side."""
    signal = {
        "ticker": "GLD",
        "classification": "bubble_forming",
        "recommendation": "reduce_exposure",
        "reasoning": "parabolic retail gold mania",
        "confidence": 8,
    }
    results = [{
        "ticker": "GLD",
        "signals": {
            "market": {"long_horizon": {
                "volume_dist_ratio": 1.6,        # real distribution (no artifact)
                "price_extension_200d": 0.85,
                "sustained_days_60": 40,
            }},
            "velocity": {"z_score_200d": 3.2},
        },
    }]
    apply_short_gates([signal], results, {"fear_greed": 75, "buffett": 180.0})
    assert signal["classification"] == "bubble_forming"
    assert signal["recommendation"] == "reduce_exposure"
    assert signal["confidence"] == 8
    assert "v2_gate" not in signal
