"""StockTwits sentiment collector.

Uses the public StockTwits API — no API key or environment variable required.
Commodity tickers use a static symbol mapping since StockTwits does not accept
yfinance futures notation (GC=F → GOLD, etc.).

All errors are caught internally; the function always returns a valid dict.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

COMMODITY_MAPPING: dict[str, str] = {
    "GC=F": "GOLD",
    "SI=F": "SILVER",
    "CL=F": "OIL",
    "HG=F": "COPPER",
    "NG=F": "NATGAS",
    "ZS=F": "SOYB",
}

_API_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_TIMEOUT = 10


def fetch_stocktwits_sentiment(ticker: str) -> dict:
    """Fetch the latest ~30 messages for *ticker* from StockTwits.

    Returns
    -------
    On success:
        {
            "heat":         str,   # "explosive"|"elevated"|"stable"|"low"
            "tone":         str,   # "bullish"|"bearish"|"neutral"
            "count":        int,   # messages returned (≤30)
            "bulls":        int,
            "bears":        int,
            "seconds_span": float, # time window covered by the messages
        }

    On API error / low message count:
        {
            "heat":  "low" | "unknown",
            "tone":  "neutral",
            "count": int,
            "bulls": 0,
            "bears": 0,
            ["error": str],
        }
    """
    st_ticker = COMMODITY_MAPPING.get(ticker, ticker)
    url = _API_URL.format(symbol=st_ticker)

    try:
        response = requests.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        logger.warning(f"StockTwits fetch failed for {ticker} ({st_ticker}): {e}")
        return {
            "heat":  "unknown",
            "tone":  "neutral",
            "count": 0,
            "bulls": 0,
            "bears": 0,
            "error": str(e),
        }

    messages = payload.get("messages", [])

    if len(messages) < 30:
        logger.info(f"StockTwits {ticker}: only {len(messages)} messages — heat=low")
        return {
            "heat":  "low",
            "tone":  "neutral",
            "count": len(messages),
            "bulls": 0,
            "bears": 0,
        }

    # --- Heat: measured by how compressed the message timestamps are ---
    try:
        newest = datetime.fromisoformat(messages[0]["created_at"].replace("Z", ""))
        oldest = datetime.fromisoformat(messages[-1]["created_at"].replace("Z", ""))
        seconds_span = (newest - oldest).total_seconds()
    except Exception as e:
        logger.warning(f"StockTwits {ticker}: timestamp parse error: {e}")
        seconds_span = 999_999  # assume cold / stable

    if seconds_span < 300:
        heat = "explosive"
    elif seconds_span < 1800:
        heat = "elevated"
    else:
        heat = "stable"

    # --- Tone: bull/bear split from StockTwits sentiment tags ---
    bulls = sum(
        1 for m in messages
        if m.get("entities", {}).get("sentiment") == {"basic": "Bullish"}
    )
    bears = sum(
        1 for m in messages
        if m.get("entities", {}).get("sentiment") == {"basic": "Bearish"}
    )

    if bears > bulls * 1.5:
        tone = "bearish"
    elif bulls > bears * 1.5:
        tone = "bullish"
    else:
        tone = "neutral"

    logger.info(
        f"StockTwits {ticker}: heat={heat}, tone={tone}, "
        f"bulls={bulls}, bears={bears}, span={seconds_span:.0f}s"
    )

    return {
        "heat":         heat,
        "tone":         tone,
        "count":        len(messages),
        "bulls":        bulls,
        "bears":        bears,
        "seconds_span": seconds_span,
    }
