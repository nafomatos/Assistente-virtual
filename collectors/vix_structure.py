"""VIX term structure: compare ^VIX (1-month) vs ^VIX3M (3-month).

A ratio > 1.0 means short-term fear exceeds long-term expectations (backwardation),
which signals elevated near-term stress.  Fetched once per run.
"""

from __future__ import annotations

import logging

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_vix_structure() -> dict | None:
    """Fetch ^VIX and ^VIX3M, compute their ratio.

    Returns:
        {
            "vix":          float,   # 1-month implied vol
            "vix3m":        float,   # 3-month implied vol
            "ratio":        float,   # vix / vix3m
            "vix_inverted": bool,    # True when ratio > 1.0 (backwardation)
        }
    or None on any failure.
    """
    try:
        vix_hist  = yf.Ticker("^VIX").history(period="5d")
        vix3m_hist = yf.Ticker("^VIX3M").history(period="5d")
    except Exception as e:
        logger.warning(f"VIX structure fetch failed: {e}")
        return None

    if vix_hist.empty or vix3m_hist.empty:
        logger.warning("VIX structure: empty history returned by yfinance")
        return None

    try:
        vix  = float(vix_hist["Close"].iloc[-1])
        vix3m = float(vix3m_hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"VIX structure: could not parse close prices: {e}")
        return None

    if vix3m == 0:
        logger.warning("VIX3M is zero; skipping ratio calculation")
        return None

    ratio = vix / vix3m
    return {
        "vix":          round(vix, 2),
        "vix3m":        round(vix3m, 2),
        "ratio":        round(ratio, 2),
        "vix_inverted": ratio > 1.0,
    }


def format_summary(data: dict | None) -> str:
    """One-line summary for the macro context header."""
    if data is None:
        return "VIX Structure: unavailable"

    ratio = data["ratio"]
    if data["vix_inverted"]:
        return (
            f"VIX Structure: Backwardation ({ratio:.2f}) — short-term stress elevated"
        )
    return f"VIX Structure: Contango ({ratio:.2f}) — normal term structure"
