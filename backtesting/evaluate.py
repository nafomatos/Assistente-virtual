"""Evaluate past recommendations against actual price movements.

Standalone utility — not part of the daily pipeline.

Usage
-----
    python -m backtesting.evaluate
    python backtesting/evaluate.py

For each recommendation in logs/recommendations.json the script fetches the
closing price 5, 10, and 30 days after the signal date and checks whether
Claude's call played out:

  contrarian_buy   → did price rise?
  reduce_exposure  → did price fall?
  wait / no_action → direction-neutral (shown but not counted in hit rate)

Output
------
Per-recommendation detail, then a hit-rate summary table.
"""

from __future__ import annotations

import datetime as dt
import sys

import yfinance as yf

EVAL_WINDOWS = [5, 10, 30]  # days after signal

# Recommendations that map to a directional expectation
BULLISH = {"contrarian_buy"}
BEARISH = {"reduce_exposure"}


def _fetch_price_after(ticker: str, signal_date_str: str, days: int) -> float | None:
    """Return the closing price `days` calendar days after `signal_date`.

    Looks for the first available trading day on or after the target date,
    searching up to 10 calendar days ahead (covers weekends + holidays).
    """
    signal_date = dt.date.fromisoformat(signal_date_str)
    target_date = signal_date + dt.timedelta(days=days)
    end_date    = target_date + dt.timedelta(days=10)

    try:
        hist = yf.Ticker(ticker).history(
            start=target_date.isoformat(),
            end=end_date.isoformat(),
        )
    except Exception:
        return None

    if hist.empty:
        return None

    # Normalise timezone-aware index to date objects
    for idx, row in hist.iterrows():
        row_date = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
        if row_date >= target_date:
            return round(float(row["Close"]), 2)

    return None


def _evaluate(rec: dict, today: dt.date) -> dict:
    """Return per-window price and hit info for one recommendation."""
    ticker = rec["ticker"]
    date   = rec["date"]
    price0 = rec.get("price_at_signal") or 0.0
    recom  = rec["recommendation"]

    days_elapsed = (today - dt.date.fromisoformat(date)).days
    result: dict = {}

    for days in EVAL_WINDOWS:
        if days_elapsed < days:
            result[days] = {"status": "pending"}
            continue

        price = _fetch_price_after(ticker, date, days)
        if price is None or price0 <= 0:
            result[days] = {"status": "no_data"}
            continue

        change_pct = (price - price0) / price0 * 100

        if recom in BULLISH:
            hit = change_pct > 0
        elif recom in BEARISH:
            hit = change_pct < 0
        else:
            hit = None  # directional-neutral; don't count

        result[days] = {
            "status":     "evaluated",
            "price":      price,
            "change_pct": round(change_pct, 2),
            "hit":        hit,
        }

    return result


def main() -> None:
    # Lazy import so this file can live standalone without circular deps
    from backtesting.tracker import load_recommendations

    recs = load_recommendations()
    if not recs:
        print("No recommendations in logs/recommendations.json yet.")
        print("Paste Claude's JSON output into backtesting/tracker.py to add some.")
        return

    today = dt.date.today()
    hit_totals: dict[int, dict] = {d: {"hits": 0, "total": 0} for d in EVAL_WINDOWS}

    print(f"\nBacktest Report — {today.isoformat()}")
    print(f"Recommendations: {len(recs)}\n")
    print("=" * 70)

    for rec in recs:
        ticker = rec["ticker"]
        date   = rec["date"]
        cls    = rec["classification"]
        recom  = rec["recommendation"]
        conf   = rec.get("confidence", "?")
        price0 = rec.get("price_at_signal", 0.0)

        print(f"[{date}] {ticker} | {cls} → {recom} (conf={conf}, px=${price0:.2f})")

        days_elapsed = (today - dt.date.fromisoformat(date)).days
        if days_elapsed < min(EVAL_WINDOWS):
            print(f"  → Too recent to evaluate ({days_elapsed}d elapsed, need {min(EVAL_WINDOWS)}d)\n")
            continue

        results = _evaluate(rec, today)

        for days in EVAL_WINDOWS:
            r = results[days]
            if r["status"] == "pending":
                print(f"  d+{days:2d}: not yet ({days - days_elapsed}d remaining)")
            elif r["status"] == "no_data":
                print(f"  d+{days:2d}: no price data")
            else:
                hit  = r["hit"]
                mark = "✓" if hit else ("✗" if hit is False else "—")
                print(
                    f"  d+{days:2d}: ${r['price']:.2f} ({r['change_pct']:+.1f}%) {mark}"
                )
                if hit is not None:
                    hit_totals[days]["total"] += 1
                    if hit:
                        hit_totals[days]["hits"] += 1
        print()

    print("=" * 70)
    print("Hit Rate Summary (contrarian_buy / reduce_exposure only):")
    for days in EVAL_WINDOWS:
        t = hit_totals[days]["total"]
        h = hit_totals[days]["hits"]
        if t:
            pct = 100 * h // t
            print(f"  d+{days:2d}: {h}/{t} ({pct}%)")
        else:
            print(f"  d+{days:2d}: n/a (no directional recs evaluated)")


if __name__ == "__main__":
    sys.exit(main())
