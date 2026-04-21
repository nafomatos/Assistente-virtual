"""Discover trending US equity tickers from ApeWisdom and Yahoo Finance.

Both sources are public and require no API key.
ApeWisdom ranks tickers by social-media mention velocity on Reddit/StockTwits.
Yahoo Finance returns its own trending list.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"
_TIMEOUT = 10

_BLOCKLIST: frozenset[str] = frozenset([
    "BTC-USD", "ETH-USD", "BTC", "ETH", "DOGE", "SHIB", "SOL",
    "XRP", "ADA", "AVAX", "MATIC", "DOT", "LUNA", "UST",
])


def _is_valid_stock_ticker(ticker: str) -> bool:
    """Return True only for clean US equity ticker symbols."""
    if not ticker or not isinstance(ticker, str):
        return False
    t = ticker.strip()
    if t in _BLOCKLIST:
        return False
    if "=" in t:        # futures notation (GC=F, CL=F …)
        return False
    if "^" in t:        # index symbols (^GSPC …)
        return False
    if "-" in t:        # crypto pairs, preferred shares (BTC-USD …)
        return False
    if len(t) > 5:      # ADRs and foreign listings often exceed 5 chars
        return False
    if not t.isalpha():  # must be pure letters after the above checks
        return False
    return True


def fetch_apewisdom_trending(max_results: int = 10) -> list[str]:
    """Return up to `max_results` tickers from ApeWisdom's all-stocks feed."""
    try:
        resp = requests.get(_APEWISDOM_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        tickers = [r["ticker"] for r in results if r.get("ticker")]
        logger.info(f"ApeWisdom returned {len(tickers)} tickers")
        return tickers[:max_results]
    except Exception as e:
        logger.warning(f"ApeWisdom fetch failed: {e}")
        return []


def fetch_yahoo_trending(max_results: int = 10) -> list[str]:
    """Return up to `max_results` tickers from Yahoo Finance trending."""
    try:
        import yfinance as yf
        trending = yf.get_trending_tickers(count=max_results)
        tickers = [t for t in (trending or []) if t]
        logger.info(f"Yahoo Finance trending returned {len(tickers)} tickers")
        return tickers[:max_results]
    except Exception as e:
        logger.warning(f"Yahoo trending fetch failed: {e}")
        return []


def fetch_trending_tickers(max_results: int = 15) -> tuple[list[str], dict]:
    """Merge both sources, deduplicate, filter non-equity noise.

    Returns (clean_tickers, stats) where stats contains counts for logging:
        {"apewisdom": N, "yahoo": N, "merged": N, "added": N, "filtered": N}

    ApeWisdom order is preserved (higher social-signal quality); Yahoo fills in
    any remaining slots.
    """
    ape   = fetch_apewisdom_trending(max_results=max_results)
    yahoo = fetch_yahoo_trending(max_results=max_results)

    n_ape   = len(ape)
    n_yahoo = len(yahoo)

    seen:   set[str]  = set()
    merged: list[str] = []
    for ticker in ape + yahoo:
        if ticker not in seen:
            seen.add(ticker)
            merged.append(ticker)

    n_merged = len(merged)
    clean = [t for t in merged if _is_valid_stock_ticker(t)][:max_results]

    stats = {
        "apewisdom": n_ape,
        "yahoo":     n_yahoo,
        "merged":    n_merged,
        "added":     len(clean),
        "filtered":  n_merged - len(clean),
    }
    logger.info(
        f"trending_tickers: ApeWisdom={n_ape}, Yahoo={n_yahoo}, "
        f"merged={n_merged}, clean={len(clean)}, filtered={n_merged - len(clean)}"
    )
    return clean, stats
