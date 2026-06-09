"""Market data collector using yfinance.

Returns a compact dict of scalars plus a small closes tail (for RSI)
and the 3 most recent news headlines. Never the full OHLC series.

v2 addition: a ``long_horizon`` sub-dict is included in the returned
market dict. It contains observation-mode metrics for the bubble-detection
strategy redesign (price_extension_200d, sustained_days_60, return_6m,
acceleration_ratio, volume_dist_ratio, drawdown_from_peak_2y,
days_since_peak_2y). These are display-only in v1 of this change; they
do not affect the alert-tier gates.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# "2y" gives ~504 trading days — enough for the 200d rolling SMA plus the
# 60-day sustained-extension window (260d needed) and the 2-year peak
# drawdown calculation. Existing calcs use .tail() / .iloc[-N:] so they
# are unaffected by the extra rows.
HISTORY_PERIOD = "2y"
LONG_LOOKBACK_DAYS = 200
CLOSES_TAIL_FOR_RSI = 60  # >> 14 so Wilder's smoothing stabilizes
VOLUME_SHORT_WINDOW = 10  # trailing days used as post-roll floor (Fix 2)

# Long-horizon extension threshold used for sustained_days_60.
# A price >40 % above its 200d SMA for 30+ of the last 60 trading days
# is a candidate for bubble-watch in v2 gate logic (not yet active).
_EXTENSION_THRESHOLD_40PCT = 0.40


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


def _compute_long_horizon(closes, returns, volumes, current_price: float) -> dict:
    """Compute long-horizon momentum and bubble-watch metrics.

    All values are rounded scalars or None when insufficient data is available.
    Errors are caught and logged so they never break the main pipeline.

    Returned keys
    -------------
    price_extension_200d  : float | None
        (current_price / 200d_SMA) - 1.  E.g. 0.82 → price is 82 % above 200d MA.
    sustained_days_60     : int | None
        Number of trading days in the last 60 where daily close was >40 %
        above the rolling 200d SMA.  Requires ≥ 260 rows of history.
    return_6m             : float | None
        Return over the last ~126 trading days (≈ 6 calendar months).
    acceleration_ratio    : float | None
        Fraction of the 6m gain captured in the last 30 trading days.
        0.5 → the last 30d accounted for 50 % of the 6-month gain.
        Only computed when return_6m > 0.
    volume_dist_ratio     : float | None
        (total volume on down-days) / (total volume on up-days) over the
        last 20 trading days.  > 1.0 signals distribution (more selling
        pressure than buying pressure).  Zero-volume rows (futures contract
        rolls) and flat days (return exactly 0) are excluded — this ratio is
        the PRIMARY v2 short gate, so roll artifacts must not skew it.
    drawdown_from_peak_2y : float | None
        (current_price / 2y_rolling_peak) - 1.  Always ≤ 0.
        E.g. -0.65 → price is 65 % below its 2-year high.
    days_since_peak_2y    : int | None
        Number of trading days between the 2-year rolling high and today.
    """
    out: dict = {
        "price_extension_200d":   None,
        "sustained_days_60":      None,
        "return_6m":              None,
        "acceleration_ratio":     None,
        "volume_dist_ratio":      None,
        "drawdown_from_peak_2y":  None,
        "days_since_peak_2y":     None,
    }

    # Each metric is guarded independently so a failure in one cannot blank
    # out the others — volume_dist_ratio in particular is the PRIMARY v2
    # short gate and must survive an error in an unrelated metric.
    n = len(closes)

    # ── 200d SMA and price extension ──────────────────────────────────────────
    try:
        if n >= 200:
            sma_200 = float(closes.iloc[-200:].mean())
            if sma_200 > 0:
                out["price_extension_200d"] = round(
                    (current_price / sma_200) - 1.0, 4
                )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"long_horizon: price_extension_200d error: {exc}")

    # ── Sustained extension: days in last 60 where close > 40 % above SMA ─────
    try:
        if n >= 260:
            rolling_sma = closes.rolling(window=200, min_periods=200).mean()
            ext_series = (closes / rolling_sma) - 1.0
            ext_tail = ext_series.tail(60).dropna()
            out["sustained_days_60"] = int((ext_tail > _EXTENSION_THRESHOLD_40PCT).sum())
        elif n >= 200:
            # Enough for a single SMA reading but not a rolling window of 60.
            # Report 0; the field is valid but the sustained window is incomplete.
            out["sustained_days_60"] = 0
    except Exception as exc:  # pragma: no cover
        logger.warning(f"long_horizon: sustained_days_60 error: {exc}")

    # ── 6-month return (~126 trading days) + acceleration ratio ───────────────
    try:
        if n >= 127:
            price_6m_ago = float(closes.iloc[-127])
            if price_6m_ago > 0:
                out["return_6m"] = round(
                    (current_price / price_6m_ago) - 1.0, 4
                )

        ret_6m = out["return_6m"]
        if ret_6m is not None and n >= 31:
            price_30d_ago = float(closes.iloc[-31])
            if price_30d_ago > 0:
                gain_30d = (current_price / price_30d_ago) - 1.0
                if ret_6m > 0:
                    out["acceleration_ratio"] = round(gain_30d / ret_6m, 3)
                else:
                    # 6m return is zero or negative — no positive gains to accelerate
                    out["acceleration_ratio"] = 0.0
    except Exception as exc:  # pragma: no cover
        logger.warning(f"long_horizon: return_6m/acceleration error: {exc}")

    # ── Volume distribution (last 20 trading days) ─────────────────────────────
    # Zero-volume rows are contract-roll artifacts in yfinance futures data
    # (same issue as Fix 1 on avg_volume_30d); flat days carry no directional
    # information. Both are excluded from the up/down sums.
    try:
        if len(returns) >= 20:
            rets_20 = returns.tail(20)
            vols_20 = volumes.loc[rets_20.index]
            valid     = vols_20.values > 0
            up_mask   = (rets_20.values > 0) & valid
            down_mask = (rets_20.values < 0) & valid
            up_vol   = float(vols_20.values[up_mask].sum())
            down_vol = float(vols_20.values[down_mask].sum())
            if up_vol > 0:
                out["volume_dist_ratio"] = round(down_vol / up_vol, 3)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"long_horizon: volume_dist_ratio error: {exc}")

    # ── 2-year peak drawdown ───────────────────────────────────────────────────
    try:
        if n >= 1:
            peak_price = float(closes.max())
            if peak_price > 0:
                out["drawdown_from_peak_2y"] = round(
                    (current_price / peak_price) - 1.0, 4
                )
                peak_pos = int(closes.values.argmax())
                out["days_since_peak_2y"] = n - 1 - peak_pos
    except Exception as exc:  # pragma: no cover
        logger.warning(f"long_horizon: peak drawdown error: {exc}")

    return out


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

    long_horizon = _compute_long_horizon(closes, returns, volumes, current_price)

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
        "long_horizon":         long_horizon,
    }
