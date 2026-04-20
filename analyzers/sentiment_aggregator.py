"""Social-heat z-score aggregator.

Instead of a raw 0-100 score, this module computes a z-score of today's
mention count against each ticker's 30-day rolling baseline.  A 3-sigma spike
is a much stronger signal than an absolute headline number.

Baseline is persisted in logs/sentiment_baseline.json (last 30 entries per
ticker, appended daily).

Usage
-----
    from analyzers.sentiment_aggregator import aggregate_sentiment

    # In main.py, after social collectors provide a count (or None):
    sentiment = aggregate_sentiment(ticker, mention_count=reddit_count)

    # If no collectors are wired yet, pass nothing — returns gracefully:
    sentiment = aggregate_sentiment(ticker)   # mention_count defaults to None

Return shape
------------
    {
        "social_heat_zscore": float | None,  # None when < 7 days of history
        "mention_count":      int   | None,  # raw count from collectors
    }
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import statistics

logger = logging.getLogger(__name__)

BASELINE_FILE = os.path.join("logs", "sentiment_baseline.json")
MIN_HISTORY_DAYS = 7   # need at least this many days before z-score is meaningful
MAX_HISTORY_DAYS = 30  # keep at most this many entries per ticker


def _load_baseline() -> dict:
    if not os.path.exists(BASELINE_FILE):
        return {}
    try:
        with open(BASELINE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"sentiment baseline load failed: {e}; starting fresh")
        return {}


def _save_baseline(baseline: dict) -> None:
    os.makedirs(os.path.dirname(BASELINE_FILE), exist_ok=True)
    try:
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)
    except Exception as e:
        logger.warning(f"sentiment baseline save failed: {e}")


def aggregate_sentiment(ticker: str, mention_count: int | None = None) -> dict:
    """Compute social_heat_zscore from a raw mention count vs 30-day baseline.

    If mention_count is None (no social collectors wired yet), the baseline is
    not updated and both fields return None — the pipeline degrades gracefully.

    When real collectors are added, pass the total daily mention count from
    whatever sources are available (Reddit + Twitter + YouTube sum, or any
    subset).
    """
    if mention_count is None:
        return {"social_heat_zscore": None, "mention_count": None}

    baseline = _load_baseline()
    history: list[dict] = baseline.get(ticker, [])

    # Calculate z-score if we have enough history
    zscore: float | None = None
    if len(history) >= MIN_HISTORY_DAYS:
        counts = [e["count"] for e in history[-MAX_HISTORY_DAYS:]]
        mean = statistics.mean(counts)
        std = statistics.pstdev(counts)  # population stdev over the window
        if std > 0:
            zscore = (mention_count - mean) / std
        else:
            # All baseline values identical; treat any difference as extreme
            zscore = 0.0 if mention_count == mean else float("inf")

    # Update baseline: replace today's entry if already present, then trim
    today_str = dt.date.today().isoformat()
    history = [e for e in history if e.get("date") != today_str]
    history.append({"date": today_str, "count": mention_count})
    history = history[-MAX_HISTORY_DAYS:]
    baseline[ticker] = history
    _save_baseline(baseline)

    return {
        "social_heat_zscore": round(zscore, 2) if zscore is not None else None,
        "mention_count":      mention_count,
    }
