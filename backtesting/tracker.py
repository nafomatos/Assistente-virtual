"""Save Claude's recommendations to logs/recommendations.json for backtesting.

Usage
-----
After Claude returns a JSON recommendation, paste it here via the CLI or call
this module directly:

    from backtesting.tracker import save_recommendation

    save_recommendation(
        ticker="NVDA",
        date="2026-04-20",
        classification="bubble_forming",
        recommendation="reduce_exposure",
        confidence=8,
        price_at_signal=875.50,
    )

The JSON file at logs/recommendations.json is append-only: each run adds a new
entry.  Run backtesting/evaluate.py to see how past signals played out.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

RECS_FILE = os.path.join("logs", "recommendations.json")


def load_recommendations() -> list[dict]:
    """Return all saved recommendations, or [] if the file does not exist."""
    if not os.path.exists(RECS_FILE):
        return []
    with open(RECS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_recommendation(
    ticker: str,
    classification: str,
    recommendation: str,
    confidence: int,
    price_at_signal: float,
    date: str | None = None,
) -> dict:
    """Append one recommendation entry to logs/recommendations.json.

    Parameters
    ----------
    ticker:           e.g. "NVDA"
    classification:   one of bubble_forming | irrational_panic |
                      silent_accumulation | ambiguous | no_signal
    recommendation:   one of contrarian_buy | reduce_exposure | wait | no_action
    confidence:       integer 1-10 as returned by Claude
    price_at_signal:  closing price on the signal date (for % return calc later)
    date:             YYYY-MM-DD string; defaults to today
    """
    entry = {
        "ticker":          ticker,
        "date":            date or dt.date.today().isoformat(),
        "classification":  classification,
        "recommendation":  recommendation,
        "confidence":      confidence,
        "price_at_signal": price_at_signal,
    }

    os.makedirs(os.path.dirname(RECS_FILE), exist_ok=True)
    recs = load_recommendations()
    recs.append(entry)

    with open(RECS_FILE, "w", encoding="utf-8") as f:
        json.dump(recs, f, indent=2)

    print(f"Saved: {entry}")
    return entry


def _parse_and_save_from_stdin() -> None:
    """CLI helper: read a JSON array from stdin and save each element."""
    raw = sys.stdin.read().strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        raise SystemExit(1)

    if not isinstance(items, list):
        items = [items]

    price_at_signal = None
    # Prompt for the price if not embedded
    for item in items:
        ticker = item.get("ticker", "?")
        price = item.get("price_at_signal") or price_at_signal
        if price is None:
            try:
                price = float(input(f"Price at signal for {ticker}: "))
            except (ValueError, EOFError):
                price = 0.0
        save_recommendation(
            ticker=ticker,
            classification=item.get("classification", "ambiguous"),
            recommendation=item.get("recommendation", "no_action"),
            confidence=int(item.get("confidence", 5)),
            price_at_signal=price,
        )


if __name__ == "__main__":
    # Usage: python -m backtesting.tracker < recommendations.json
    _parse_and_save_from_stdin()
