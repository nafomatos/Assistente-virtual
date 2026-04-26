"""Synthetic sentiment proxy for historical backtests.

Real social data (Reddit, StockTwits, YouTube) is not available for historical
periods. This module derives a proxy from VIX + price velocity + RSI so the
Divergence Rules in the system prompt can still fire during backtests.
"""

from __future__ import annotations


def get_synthetic_sentiment(
    ticker: str,
    date: object,
    vix_value: float,
    z_30d: float,
    z_200d: float,
    volume_ratio: float,
    rsi: float | None,
) -> dict:
    """Return a synthetic sentiment dict compatible with real sentiment format.

    Parameters
    ----------
    ticker       : Asset ticker (reserved for future per-asset overrides).
    date         : Signal date (reserved for future per-date overrides).
    vix_value    : VIX close on this date; use 20.0 if unavailable.
    z_30d        : 30-day price velocity z-score.
    z_200d       : 200-day price velocity z-score (kept for interface symmetry).
    volume_ratio : Current volume / 30d average (kept for interface symmetry).
    rsi          : RSI-14 value, or None if history is too short.

    Returns
    -------
    dict with keys: heat, tone, source, confidence_penalty
    """
    # VIX-based heat (primary signal)
    if vix_value >= 50:
        heat = "explosive"
    elif vix_value >= 35:
        heat = "elevated"
    elif vix_value >= 25:
        heat = "stable"
    else:
        heat = "low"

    # Tone from price velocity + RSI
    rsi_val = rsi if rsi is not None else 50.0
    if z_30d < -1.5 and rsi_val < 40:
        tone = "bearish"
    elif z_30d > 1.5 and rsi_val > 60:
        tone = "bullish"
    else:
        tone = "neutral"

    return {
        "heat":               heat,
        "tone":               tone,
        "source":             "synthetic_proxy",
        "confidence_penalty": 2,
    }


def vix_to_fear_greed(vix: float) -> int:
    """Derive a Fear & Greed index proxy from VIX (inverse relationship).

    High VIX = extreme fear = low score.
    """
    if vix >= 50:
        return 10   # Extreme Fear
    elif vix >= 35:
        return 25   # Fear
    elif vix >= 25:
        return 45   # Neutral
    elif vix >= 18:
        return 65   # Greed
    else:
        return 80   # Extreme Greed
