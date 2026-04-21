"""StockTwits sentiment collector.

Uses the public StockTwits API — no API key or environment variable required.
Commodity tickers use a static symbol mapping since StockTwits does not accept
yfinance futures notation (GC=F → GOLD, etc.).

All errors are caught internally; the function always returns a valid dict.
"""

from __future__ import annotations

import logging
import time
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

_NULL = {
    "heat":  "unknown",
    "tone":  "neutral",
    "count": 0,
    "bulls": 0,
    "bears": 0,
}


def _get(url: str, ticker: str) -> requests.Response | None:
    """Single HTTP GET with status-code logging.  Returns None on network error."""
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except Exception as e:
        logger.warning(f"StockTwits {ticker}: network error — {e}")
        return None

    logger.info(
        f"StockTwits {ticker}: HTTP {resp.status_code} | "
        f"body[:200]={resp.text[:200]!r}"
    )
    return resp


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
            "seconds_span": float,
        }

    On API error:
        {
            "heat":  "unknown",
            "tone":  "neutral",
            "count": 0,
            "bulls": 0,
            "bears": 0,
            "error": str,
        }
    """
    st_ticker = COMMODITY_MAPPING.get(ticker, ticker)
    url = _API_URL.format(symbol=st_ticker)

    resp = _get(url, ticker)
    if resp is None:
        return {**_NULL, "error": "network_error"}

    # --- Rate limit: sleep 2 s and retry once ---
    if resp.status_code == 429:
        logger.warning(
            f"StockTwits {ticker}: 429 rate-limited — sleeping 2 s then retrying"
        )
        time.sleep(2)
        resp = _get(url, ticker)
        if resp is None:
            return {**_NULL, "error": "network_error_after_retry"}

    # --- Auth / IP block ---
    if resp.status_code in (401, 403):
        logger.error(
            f"StockTwits {ticker}: HTTP {resp.status_code} — "
            f"StockTwits is blocking this IP (GitHub Actions IPs are commonly "
            f"blocked by StockTwits). "
            f"Response body: {resp.text[:200]!r}"
        )
        return {**_NULL, "error": f"blocked_http_{resp.status_code}"}

    # --- Any other non-200 ---
    if resp.status_code != 200:
        logger.warning(
            f"StockTwits {ticker}: unexpected HTTP {resp.status_code} | "
            f"body: {resp.text[:200]!r}"
        )
        return {**_NULL, "error": f"http_{resp.status_code}"}

    # --- Parse JSON ---
    try:
        payload = resp.json()
    except Exception as e:
        logger.warning(
            f"StockTwits {ticker}: JSON parse error — {e} | "
            f"raw: {resp.text[:200]!r}"
        )
        return {**_NULL, "error": f"json_parse: {e}"}

    messages = payload.get("messages", [])

    # 200 OK but empty messages — log full structure to diagnose API changes
    if not messages:
        logger.warning(
            f"StockTwits {ticker}: 200 OK but no messages. "
            f"Top-level keys: {list(payload.keys())} | "
            f"errors field: {payload.get('errors')} | "
            f"body[:200]: {resp.text[:200]!r}"
        )
        return {"heat": "low", "tone": "neutral", "count": 0, "bulls": 0, "bears": 0}

    if len(messages) < 30:
        logger.info(
            f"StockTwits {ticker}: only {len(messages)} messages (< 30) — heat=low"
        )
        return {"heat": "low", "tone": "neutral", "count": len(messages), "bulls": 0, "bears": 0}

    # --- Heat: how compressed are the timestamps? ---
    try:
        newest = datetime.fromisoformat(messages[0]["created_at"].replace("Z", ""))
        oldest = datetime.fromisoformat(messages[-1]["created_at"].replace("Z", ""))
        seconds_span = (newest - oldest).total_seconds()
    except Exception as e:
        logger.warning(f"StockTwits {ticker}: timestamp parse error — {e}")
        seconds_span = 999_999

    if seconds_span < 300:
        heat = "explosive"
    elif seconds_span < 1800:
        heat = "elevated"
    else:
        heat = "stable"

    # --- Tone: bull / bear tag ratio ---
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
        f"bulls={bulls}, bears={bears}, span={seconds_span:.0f}s, "
        f"messages={len(messages)}"
    )

    return {
        "heat":         heat,
        "tone":         tone,
        "count":        len(messages),
        "bulls":        bulls,
        "bears":        bears,
        "seconds_span": seconds_span,
    }
