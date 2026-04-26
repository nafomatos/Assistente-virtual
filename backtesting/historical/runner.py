"""Historical backtest engine.

Standalone research tool — does NOT touch the daily pipeline, GitHub Actions
workflow, or any production code path.

Entry point: run_historical_backtest(start_date, end_date, tickers, period_name)

For each trading day in the range it:
  1. Computes volume/velocity/RSI signals from cached yfinance data.
  2. Applies the same pre-filter (RED/AMBER tier) used by the daily pipeline.
  3. Calls Claude Haiku for each flagged (ticker, day) pair.
  4. After all signals are collected, fetches outcome prices at d+5/d+10/d+30.
  5. Calculates per-window hit rates and saves full results to
     backtesting/historical/results/{period_name}.json.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import time

import anthropic
import numpy as np
import pandas as pd
import yfinance as yf

from analyzers.price_velocity import analyze_price_velocity
from analyzers.rsi import analyze_rsi
from analyzers.volume_analyzer import analyze_volume
from claude_advisor.prompts import SYSTEM_PROMPT
from output.document_builder import get_alert_tier
from utils.token_optimizer import compress_signals

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
MODEL = "claude-haiku-4-5-20251001"
EVAL_WINDOWS = [5, 10, 30]
BULLISH = {"contrarian_buy"}
BEARISH = {"reduce_exposure"}
MAX_CLAUDE_CALLS = 200

# Appended to every historical prompt so Claude knows macro context is absent.
_MACRO_UNAVAILABLE = (
    "\n\nMacro context for this date: unavailable — historical backtest. "
    "No live Fear & Greed, VIX structure, or Buffett Indicator data. "
    "Apply base classification logic without macro adjustments."
)

# Extra calendar days fetched before start for 200d lookback warmup
_LOOKBACK_BUFFER = 310
# Extra calendar days fetched after end so d+30 outcomes are available
_OUTCOME_BUFFER = 60

# Backtest-only ticker name fallback (tickers not in config are named by symbol)
_EXTRA_NAMES: dict[str, str] = {
    "GME": "GameStop",
    "AMC": "AMC Entertainment",
    "BB":  "BlackBerry",
}


def _ticker_name(ticker: str) -> str:
    try:
        from config import TICKER_NAMES
        if ticker in TICKER_NAMES:
            return TICKER_NAMES[ticker]
    except ImportError:
        pass
    return _EXTRA_NAMES.get(ticker, ticker)


def _trading_days(start: str, end: str) -> list[dt.date]:
    """NYSE trading days between start and end (inclusive)."""
    import pandas_market_calendars as mcal
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=start, end_date=end)
    return [pd.Timestamp(d).date() for d in schedule.index]


def _fetch_ticker_history(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Download OHLCV from yfinance.

    Fetches _LOOKBACK_BUFFER days before start (for 200d signal windows) and
    _OUTCOME_BUFFER days after end (for d+30 outcome prices).
    """
    fetch_start = (dt.date.fromisoformat(start) - dt.timedelta(days=_LOOKBACK_BUFFER)).isoformat()
    fetch_end   = (dt.date.fromisoformat(end)   + dt.timedelta(days=_OUTCOME_BUFFER)).isoformat()
    try:
        hist = yf.Ticker(ticker).history(
            start=fetch_start,
            end=fetch_end,
            auto_adjust=True,
        )
        if hist.empty:
            logger.warning("%s: no data returned from yfinance", ticker)
            return None
        return hist
    except Exception as exc:
        logger.error("%s: yfinance fetch failed — %s", ticker, exc)
        return None


def _df_date_index(df: pd.DataFrame) -> dict[dt.date, int]:
    """Map each row's date to its integer position in the DataFrame."""
    result = {}
    for pos, ts in enumerate(df.index):
        d = ts.date() if hasattr(ts, "date") else ts.to_pydatetime().date()
        result[d] = pos
    return result


def _build_market_data(
    closes: np.ndarray,
    volumes: np.ndarray,
    returns: np.ndarray,
    day_idx: int,
) -> dict | None:
    """Construct the market_data dict expected by the analyzers for one day."""
    if day_idx < 1:
        return None

    current_price  = float(closes[day_idx])
    previous_close = float(closes[day_idx - 1])
    if previous_close <= 0 or current_price <= 0:
        return None

    daily_return_pct = (current_price - previous_close) / previous_close * 100
    current_volume   = float(volumes[day_idx])

    # 30-day volume baseline (prior days, not including today)
    vol_slice    = volumes[max(0, day_idx - 30):day_idx]
    avg_vol_30d  = float(vol_slice.mean()) if len(vol_slice) > 0 else 0.0

    # return distributions (prior days, not including today's return)
    rets_30  = returns[max(1, day_idx - 30 + 1):day_idx + 1]
    rets_200 = returns[max(1, day_idx - 200 + 1):day_idx + 1]

    returns_mean_30d  = float(rets_30.mean())  if len(rets_30)  > 0 else 0.0
    returns_std_30d   = float(rets_30.std())   if len(rets_30)  > 1 else 0.0
    returns_mean_200d = float(rets_200.mean()) if len(rets_200) > 0 else 0.0
    returns_std_200d  = float(rets_200.std())  if len(rets_200) > 1 else 0.0

    # RSI needs last 60 closes (including today)
    closes_recent = [float(c) for c in closes[max(0, day_idx - 59):day_idx + 1]]

    return {
        "current_price":      current_price,
        "previous_close":     previous_close,
        "current_volume":     current_volume,
        "avg_volume_30d":     avg_vol_30d,
        "daily_return_pct":   daily_return_pct,
        "returns_mean_30d":   returns_mean_30d,
        "returns_std_30d":    returns_std_30d,
        "returns_mean_200d":  returns_mean_200d,
        "returns_std_200d":   returns_std_200d,
        "closes_recent":      closes_recent,
        "recent_news":        [],
        "price_series_summary": {},
    }


def _call_claude(
    client: anthropic.Anthropic,
    prompt_text: str,
) -> tuple[dict | None, dict]:
    """Call Claude Haiku and return (parsed_recommendation, usage_dict).

    Uses prompt caching for SYSTEM_PROMPT so repeated calls in the same
    session benefit from cache reads.
    """
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            temperature=0.3,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt_text}],
        )
    except Exception as exc:
        logger.error("Claude API error: %s", exc)
        return None, {}

    usage = {
        "input_tokens":                response.usage.input_tokens,
        "output_tokens":               response.usage.output_tokens,
        "cache_read_input_tokens":     getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }

    logger.info(
        "token usage: input=%d output=%d cached=%d cache_write=%d",
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_read_input_tokens"],
        usage["cache_creation_input_tokens"],
    )

    text = response.content[0].text if response.content else ""

    # Try to extract the JSON array from the JSON_OUTPUT section first,
    # then fall back to any JSON array in the response.
    for pattern in (r"JSON_OUTPUT:\s*(\[.*?\])", r"(\[.*?\])"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                items = json.loads(m.group(1))
                if items and isinstance(items, list):
                    return items[0], usage
            except (json.JSONDecodeError, IndexError):
                continue

    logger.warning("Could not parse JSON from Claude response: %s", text[:200])
    return None, usage


def _fetch_price_after(
    date_to_pos: dict[dt.date, int],
    closes: np.ndarray,
    signal_date: dt.date,
    days: int,
) -> float | None:
    """Return the first available close on or after signal_date + days."""
    target = signal_date + dt.timedelta(days=days)
    # Walk forward up to 10 calendar days to find a trading day
    for offset in range(11):
        candidate = target + dt.timedelta(days=offset)
        pos = date_to_pos.get(candidate)
        if pos is not None:
            return round(float(closes[pos]), 2)
    return None


def _evaluate_outcomes(
    signals: list[dict],
    ticker_arrays: dict[str, tuple[np.ndarray, dict[dt.date, int]]],
) -> list[dict]:
    """Attach d+5/d+10/d+30 outcome prices and hit flags to every signal."""
    for sig in signals:
        ticker      = sig["ticker"]
        signal_date = dt.date.fromisoformat(sig["date"])
        price0      = sig["price_at_signal"]
        recom       = sig["recommendation"]

        arr = ticker_arrays.get(ticker)
        outcomes: dict[str, dict] = {}

        for days in EVAL_WINDOWS:
            key = f"d{days}"
            if arr is None:
                outcomes[key] = {"status": "no_data"}
                continue

            closes, date_to_pos = arr
            price = _fetch_price_after(date_to_pos, closes, signal_date, days)

            if price is None or price0 <= 0:
                outcomes[key] = {"status": "no_data"}
                continue

            change_pct = round((price - price0) / price0 * 100, 2)

            if recom in BULLISH:
                hit: bool | None = change_pct > 0
            elif recom in BEARISH:
                hit = change_pct < 0
            else:
                hit = None  # wait / no_action — direction-neutral

            outcomes[key] = {
                "status":     "evaluated",
                "price":      price,
                "change_pct": change_pct,
                "hit":        hit,
            }

        sig["outcomes"] = outcomes

    return signals


def _calculate_hit_rates(signals: list[dict]) -> dict:
    """Per-window hit rates broken down by recommendation type."""
    rates: dict[str, dict[str, dict]] = {}

    for days in EVAL_WINDOWS:
        key = f"d{days}"
        by_recom: dict[str, dict] = {}

        for sig in signals:
            recom   = sig.get("recommendation", "")
            outcome = sig.get("outcomes", {}).get(key, {})
            if outcome.get("status") != "evaluated":
                continue
            hit = outcome.get("hit")
            if hit is None:
                continue  # direction-neutral

            if recom not in by_recom:
                by_recom[recom] = {"hits": 0, "total": 0}
            by_recom[recom]["total"] += 1
            if hit:
                by_recom[recom]["hits"] += 1

        for counts in by_recom.values():
            t = counts["total"]
            counts["pct"] = round(100 * counts["hits"] / t, 1) if t else 0.0

        rates[key] = by_recom

    return rates


def run_historical_backtest(
    start_date: str,
    end_date: str,
    tickers: list[str],
    period_name: str,
) -> dict:
    """Run the full historical backtest and return the results dict.

    Results are also persisted to backtesting/historical/results/{period_name}.json.
    """
    logger.info("Backtest '%s'  %s → %s  (%d tickers)",
                period_name, start_date, end_date, len(tickers))

    client = anthropic.Anthropic()

    # --- 1. Trading days -------------------------------------------------------
    trading_days = _trading_days(start_date, end_date)
    logger.info("%d trading days in range", len(trading_days))

    # --- 2. Fetch OHLCV for all tickers ----------------------------------------
    ticker_dfs: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        logger.info("Fetching %s ...", ticker)
        df = _fetch_ticker_history(ticker, start_date, end_date)
        if df is not None:
            ticker_dfs[ticker] = df
        time.sleep(0.25)  # be polite to yfinance

    # Pre-build numpy arrays + date→position maps for fast per-day lookups
    ticker_arrays: dict[str, tuple[np.ndarray, dict[dt.date, int]]] = {}
    for ticker, df in ticker_dfs.items():
        date_to_pos = _df_date_index(df)
        closes      = df["Close"].values.astype(float)
        ticker_arrays[ticker] = (closes, date_to_pos)

    # Pre-compute per-ticker daily returns (reused every day in the loop)
    ticker_returns: dict[str, np.ndarray] = {}
    for ticker, (closes, _) in ticker_arrays.items():
        rets = np.zeros(len(closes))
        prev = closes[:-1]
        mask = prev > 0
        rets[1:][mask] = (closes[1:][mask] - prev[mask]) / prev[mask]
        ticker_returns[ticker] = rets

    # --- 3. Main loop: signals + Claude calls ----------------------------------
    all_signals: list[dict] = []
    total_claude_calls = 0
    total_usage = {
        "input_tokens":                0,
        "output_tokens":               0,
        "cache_read_input_tokens":     0,
        "cache_creation_input_tokens": 0,
    }
    cap_reached = False

    for day in trading_days:
        if cap_reached:
            break

        day_signal_count = 0

        for ticker in tickers:
            if cap_reached:
                break

            arr = ticker_arrays.get(ticker)
            if arr is None:
                continue

            closes, date_to_pos = arr
            day_idx = date_to_pos.get(day)
            if day_idx is None:
                continue

            volumes = ticker_dfs[ticker]["Volume"].values.astype(float)
            returns = ticker_returns[ticker]

            market_data = _build_market_data(closes, volumes, returns, day_idx)
            if market_data is None:
                continue

            volume   = analyze_volume(market_data)
            velocity = analyze_price_velocity(market_data)
            rsi      = analyze_rsi(market_data)

            signals = {
                "market":    market_data,
                "volume":    volume,
                "velocity":  velocity,
                "rsi":       rsi,
                "sentiment": None,  # no sentiment data for historical periods
            }

            tier = get_alert_tier(signals)
            if tier is None:
                continue

            # Hard cap: stop before making the call that would exceed the limit
            if total_claude_calls >= MAX_CLAUDE_CALLS:
                logger.warning(
                    "Hard cap of %d Claude calls reached at %s/%s — "
                    "stopping early. Remaining days/tickers skipped.",
                    MAX_CLAUDE_CALLS, day, ticker,
                )
                cap_reached = True
                break

            # --- Claude call ---------------------------------------------------
            name        = _ticker_name(ticker)
            # Append macro-unavailable note so Claude skips macro adjustments.
            prompt_text = compress_signals(ticker, name, signals) + _MACRO_UNAVAILABLE
            logger.info("Calling Claude: %s %s (call %d/%d)", ticker, day,
                        total_claude_calls + 1, MAX_CLAUDE_CALLS)
            parsed, usage = _call_claude(client, prompt_text)

            total_claude_calls += 1
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

            all_signals.append({
                "ticker":          ticker,
                "date":            day.isoformat(),
                "tier":            tier,
                "classification":  parsed.get("classification", "ambiguous") if parsed else "error",
                "recommendation":  parsed.get("recommendation", "no_action")  if parsed else "error",
                "confidence":      parsed.get("confidence", 0)                if parsed else 0,
                "reasoning":       parsed.get("reasoning", "")                if parsed else "",
                "price_at_signal": market_data["current_price"],
                "volume_ratio":    volume["ratio"],
                "z_score_30d":     velocity["z_score_30d"],
                "z_score_200d":    velocity["z_score_200d"],
                "rsi":             rsi.get("rsi"),
                "macro_extreme":   velocity["macro_extreme"],
            })

            day_signal_count += 1
            time.sleep(0.3)  # stay within Claude rate limits

        if day_signal_count:
            logger.info("%s → %d signal(s) flagged", day, day_signal_count)

    if cap_reached:
        logger.warning(
            "Backtest stopped early due to %d-call cap. "
            "%d signals collected before cutoff.",
            MAX_CLAUDE_CALLS, len(all_signals),
        )
    logger.info("Total signals: %d  Claude calls: %d", len(all_signals), total_claude_calls)

    # --- 4. Outcomes -----------------------------------------------------------
    logger.info("Fetching outcome prices ...")
    all_signals = _evaluate_outcomes(all_signals, ticker_arrays)

    # --- 5. Hit rates ----------------------------------------------------------
    hit_rates = _calculate_hit_rates(all_signals)

    # --- 6. Save ---------------------------------------------------------------
    results = {
        "period_name":             period_name,
        "start_date":              start_date,
        "end_date":                end_date,
        "tickers":                 tickers,
        "trading_days_processed":  len(trading_days),
        "total_signals_generated": len(all_signals),
        "total_claude_calls":      total_claude_calls,
        "cap_reached":             cap_reached,
        "token_usage":             total_usage,
        "hit_rates":               hit_rates,
        "signals":                 all_signals,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"{period_name}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)

    logger.info("Results saved → %s", out_path)
    return results
