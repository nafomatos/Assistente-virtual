"""Market data collector using yfinance.

Returns a small dict of scalars — NOT the raw OHLC series —
so the downstream Claude prompt stays token-efficient.
"""

from __future__ import annotations

import logging

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_market_data(ticker: str, lookback_days: int = 30) -> dict:
    """Fetch a compact snapshot of recent price/volume behavior.

    Raises ValueError if yfinance returns no rows for the ticker.
    """
    logger.info(f"fetching market data: {ticker} ({lookback_days}d)")

    hist = yf.Ticker(ticker).history(period=f"{lookback_days + 5}d", auto_adjust=False)
    if hist is None or hist.empty:
        raise ValueError(f"no history returned for {ticker}")

    hist = hist.tail(lookback_days + 1)  # need one extra row for previous_close
    closes = hist["Close"]
    volumes = hist["Volume"]

    current_price   = float(closes.iloc[-1])
    previous_close  = float(closes.iloc[-2]) if len(closes) >= 2 else current_price
    current_volume  = float(volumes.iloc[-1])
    avg_volume_30d  = float(volumes.iloc[-(lookback_days + 1):-1].mean())

    # Daily returns over the lookback window
    returns = closes.pct_change().dropna()
    returns_tail = returns.tail(lookback_days)
    returns_std_30d  = float(returns_tail.std()) if len(returns_tail) > 1 else 0.0
    returns_mean_30d = float(returns_tail.mean()) if len(returns_tail) > 0 else 0.0
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

    return {
        "ticker":               ticker,
        "current_price":        current_price,
        "previous_close":       previous_close,
        "current_volume":       current_volume,
        "avg_volume_30d":       avg_volume_30d,
        "daily_return_pct":     daily_return_pct,
        "returns_mean_30d":     returns_mean_30d,
        "returns_std_30d":      returns_std_30d,
        "price_series_summary": price_series_summary,
    }
