"""Buffett Indicator: Wilshire 5000 total market cap vs US GDP.

Wilshire 5000 (^W5000) approximates total US market cap in billions; the index
level is treated as a direct proxy (1 index point ≈ $1 billion market cap, per
the original Wilshire definition).  GDP comes from the FRED API (series "GDP",
billions of dollars, annualised quarterly).

Ratio = (Wilshire index level / GDP in billions) * 100

Classification:
  < 80   → Undervalued
  80-100 → Fair Value
  100-140→ Overvalued
  > 140  → Extreme

Requires FRED_API_KEY in the environment (free key at fred.stlouisfed.org).
Fetched once per run, not per ticker.
"""

from __future__ import annotations

import logging
import os

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

FRED_URL = (
    "https://api.stlouisfed.org/fred/series/observations"
    "?series_id=GDP&file_type=json&sort_order=desc&limit=1&api_key={key}"
)
TIMEOUT = 10


def _classify(ratio_pct: float) -> str:
    if ratio_pct < 80:
        return "Undervalued"
    if ratio_pct < 100:
        return "Fair Value"
    if ratio_pct < 140:
        return "Overvalued"
    return "Extreme"


def fetch_buffett_indicator() -> dict | None:
    """Compute Buffett Indicator from live Wilshire 5000 and FRED GDP.

    Returns:
        {
            "wilshire":       float,   # index level (proxy for market cap $B)
            "gdp_billions":   float,   # annualised GDP in billions
            "ratio_pct":      float,   # (wilshire / gdp_billions) * 100
            "classification": str,
        }
    or None on any failure (missing key, network error, bad parse).
    """
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        logger.warning("FRED_API_KEY not set; Buffett Indicator unavailable")
        return None

    # --- Wilshire 5000 ---
    try:
        hist = yf.Ticker("^W5000").history(period="5d")
    except Exception as e:
        logger.warning(f"Buffett Indicator: Wilshire 5000 fetch failed: {e}")
        return None

    if hist.empty:
        logger.warning("Buffett Indicator: ^W5000 returned empty history")
        return None

    wilshire = float(hist["Close"].iloc[-1])

    # --- FRED GDP ---
    try:
        resp = requests.get(FRED_URL.format(key=api_key), timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        observations = payload.get("observations") or []
        if not observations:
            logger.warning("Buffett Indicator: FRED returned no GDP observations")
            return None
        gdp_billions = float(observations[0]["value"])
    except Exception as e:
        logger.warning(f"Buffett Indicator: FRED GDP fetch failed: {e}")
        return None

    if gdp_billions <= 0:
        logger.warning("Buffett Indicator: GDP value is non-positive; skipping")
        return None

    ratio_pct = (wilshire / gdp_billions) * 100
    return {
        "wilshire":       round(wilshire, 0),
        "gdp_billions":   round(gdp_billions, 0),
        "ratio_pct":      round(ratio_pct, 1),
        "classification": _classify(ratio_pct),
    }


def format_summary(data: dict | None) -> str:
    """One-line summary for the macro context header."""
    if data is None:
        return "Buffett Indicator: unavailable"
    return (
        f"Buffett Indicator: {data['ratio_pct']:.0f}% — {data['classification']} "
        f"(historical avg ~120%)"
    )
