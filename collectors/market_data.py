"""Market data collector using yfinance.

Returns a compact dict of scalars plus a small closes tail (for RSI)
and the 3 most recent news headlines. Never the full OHLC series.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# We need at least 200 trading days for the long-window z-score and
# enough headroom for RSI smoothing. "1y" is comfortably more than 200d.
HISTORY_PERIOD = "1y"
LONG_LOOKBACK_DAYS = 200
CLOSES_TAIL_FOR_RSI = 60  # >> 14 so Wilder's smoothing stabilizes
VOLUME_SHORT_WINDOW = 10  # trailing days used as post-roll floor (Fix 2)


def _returns_stats(returns, lookback: int) -> tuple[float, float]:
    """(mean, std) of the trailing `lookback` daily returns."""
    tail = returns.tail(lookback)
    if len(tail) < 2:
        return 0.0, 0.0
    return float(tail.mean()), float(tail.std())


def _extract_news_item(item: dict) -> dict | None:
    """Normalize yfinance news items across SDK versions.

    Returns {title, publisher, age_hours} or None if unusable.
    yfinance historically exposed flat keys (title, publisher,
    providerPublishTime); recent versions wrap them in `content`.
    """
    title = item.get("title")
    publisher = item.get("publisher")
    ts = item.get("providerPublishTime")

    content = item.get("content") or {}
    if not title:
        title = content.get("title")
    if not publisher:
        provider = content.get("provider") or {}
        publisher = provider.get("displayName") or content.get("publisher")
    if ts is None:
        # newer shape: pubDate is ISO string
        pub_date = content.get("pubDate")
        if pub_date:
            try:
                # support both "...Z" and with offset
                from datetime import datetime
                s = pub_date.replace("Z", "+00:00")
                ts = int(datetime.fromisoformat(s).timestamp())
            except Exception:
                ts = None

    if not title:
        return None

    age_hours: float | None = None
    if isinstance(ts, (int, float)) and ts > 0:
        age_hours = max(0.0, round((time.time() - ts) / 3600.0, 1))

    return {
        "title":     title.strip(),
        "publisher": (publisher or "").strip() or "unknown",
        "age_hours": age_hours,
    }


def _fetch_news(tk: yf.Ticker, max_items: int = 3) -> list[dict]:
    try:
        raw = tk.news or []
    except Exception as e:
        logger.warning(f"news fetch failed: {e}")
        return []

    items: list[dict] = []
    for entry in raw:
        norm = _extract_news_item(entry)
        if norm:
            items.append(norm)
        if len(items) >= max_items:
            break
    return items


def fetch_market_data(ticker: str, lookback_days: int = 30) -> dict:
    """Fetch a compact snapshot of recent price/volume behavior plus news.

    `lookback_days` controls the short-window baseline (default 30). The
    long window is fixed at 200 trading days. Raises ValueError if
    yfinance returns no rows for the ticker.
    """
    logger.info(f"fetching market data: {ticker} (short={lookback_days}d, long={LONG_LOOKBACK_DAYS}d)")

    tk = yf.Ticker(ticker)
    hist = tk.history(period=HISTORY_PERIOD, auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"no history returned for {ticker}")

    closes = hist["Close"]
    volumes = hist["Volume"]

    current_price  = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else current_price
    current_volume = float(volumes.iloc[-1])

    # Short-window volume average (exclude today).
    # Fix 1: filter exact-zero days — contract rolls in yfinance futures data
    # produce zero-volume rows that collapse the denominator.
    # Fix 2: use the 10-day trailing window as a floor. After a roll, the 30-day
    # slice still contains deferred-contract rows with non-zero but tiny volumes
    # (1–10,000 contracts vs 200,000+ on active days). The 10-day window is
    # always post-roll and clean; max() is neutral for equities (avg_10d ≈ avg_30d).
    vol_slice    = volumes.iloc[-(lookback_days + 1):-1]
    vol_nonzero  = vol_slice[vol_slice > 0]
    avg_volume_30d = float(vol_nonzero.mean()) if len(vol_nonzero) > 0 else float(vol_slice.mean())

    vol_short    = volumes.iloc[-(VOLUME_SHORT_WINDOW + 1):-1]
    vol_short_nz = vol_short[vol_short > 0]
    avg_volume_10d = float(vol_short_nz.mean()) if len(vol_short_nz) > 0 else 0.0
    avg_volume_30d = max(avg_volume_30d, avg_volume_10d)

    returns = closes.pct_change().dropna()
    returns_mean_30d,  returns_std_30d  = _returns_stats(returns, lookback_days)
    returns_mean_200d, returns_std_200d = _returns_stats(returns, LONG_LOOKBACK_DAYS)

    daily_return_pct = (
        float((current_price / previous_close - 1.0) * 100.0) if previous_close else 0.0
    )

    window = closes.tail(lookback_days)
    price_series_summary = {
        "first": float(window.iloc[0]),
        "last":  float(window.iloc[-1]),
        "min":   float(window.min()),
        "max":   float(window.max()),
    }

    closes_recent = [float(x) for x in closes.tail(CLOSES_TAIL_FOR_RSI).tolist()]
    recent_news = _fetch_news(tk, max_items=3)

    return {
        "ticker":               ticker,
        "current_price":        current_price,
        "previous_close":       previous_close,
        "current_volume":       current_volume,
        "avg_volume_30d":       avg_volume_30d,
        "daily_return_pct":     daily_return_pct,
        "returns_mean_30d":     returns_mean_30d,
        "returns_std_30d":      returns_std_30d,
        "returns_mean_200d":    returns_mean_200d,
        "returns_std_200d":     returns_std_200d,
        "price_series_summary": price_series_summary,
        "closes_recent":        closes_recent,
        "recent_news":          recent_news,
    }
