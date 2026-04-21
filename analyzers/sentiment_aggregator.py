"""Social-heat aggregator.

Combines signals from all available sentiment sources into a single
`social_heat_zscore` and a formatted `source_breakdown` dict.

Source weights (planned):
    Reddit   — 40 %   (live)
    X        — 30 %   (Phase 5)
    YouTube  — 20 %   (Phase 5)
    Fear & Greed — 10 %  (Phase 5)

Currently only Reddit is wired.  The z-score is computed on Reddit mention
counts against a 30-day rolling baseline stored in logs/sentiment_baseline.json.
A 3-sigma spike is more actionable than an absolute headline count.

Usage
-----
    from analyzers.sentiment_aggregator import aggregate_sentiment

    reddit_data = fetch_reddit_signals(ticker, name)   # from collectors
    sentiment   = aggregate_sentiment(ticker, reddit=reddit_data)

    # Without any collectors wired:
    sentiment = aggregate_sentiment(ticker)   # all fields → None

Return shape
------------
    {
        "social_heat_zscore": float | None,
        "mention_count":      int   | None,
        "source_breakdown": {
            "reddit":   str,   # e.g. "Reddit (24h): 47 mentions, avg_score=89, ..."
            "twitter":  str,   # "n/a" until Phase 5
            "youtube":  str,   # "n/a" until Phase 5
        },
    }
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import statistics

logger = logging.getLogger(__name__)

BASELINE_FILE    = os.path.join("logs", "sentiment_baseline.json")
MIN_HISTORY_DAYS = 7    # z-score only computed once we have ≥7 days
MAX_HISTORY_DAYS = 30


# ---------------------------------------------------------------------------
# Baseline persistence
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_reddit(reddit: dict | None) -> str:
    """One-line summary for the compressed prompt output."""
    if reddit is None or reddit.get("mention_count") is None:
        return "n/a"

    count   = reddit["mention_count"]
    avg     = reddit.get("avg_score")
    trend   = reddit.get("trending")
    tone    = reddit.get("sentiment_tone")

    parts: list[str] = [f"{count} mentions"]
    if avg is not None:
        parts.append(f"avg_score={avg:.0f}")
    if trend is not None:
        parts.append(f"trending={'YES' if trend else 'NO'}")
    if tone:
        parts.append(f"tone={tone}")

    return "Reddit (24h): " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aggregate_sentiment(ticker: str, reddit: dict | None = None) -> dict:
    """Compute social_heat_zscore and assemble source_breakdown.

    Parameters
    ----------
    ticker  : asset symbol (used as the baseline key)
    reddit  : return value of fetch_reddit_signals(), or None when the
              collector is unavailable

    The z-score baseline is updated only when `reddit` contains a live
    mention_count.  When all sources are None the function returns quickly
    with all-None fields so the pipeline never stalls.
    """
    empty_breakdown = {
        "reddit":  _format_reddit(reddit),
        "twitter": "n/a",
        "youtube": "n/a",
    }

    mention_count: int | None = (reddit or {}).get("mention_count")

    if mention_count is None:
        return {
            "social_heat_zscore": None,
            "mention_count":      None,
            "source_breakdown":   empty_breakdown,
        }

    # --- Z-score against 30-day rolling baseline ---
    baseline = _load_baseline()
    history: list[dict] = baseline.get(ticker, [])

    zscore: float | None = None
    if len(history) >= MIN_HISTORY_DAYS:
        counts = [e["count"] for e in history[-MAX_HISTORY_DAYS:]]
        mean   = statistics.mean(counts)
        std    = statistics.pstdev(counts)
        if std > 0:
            zscore = (mention_count - mean) / std
        else:
            # Flat baseline — any non-zero difference is noteworthy
            zscore = 0.0 if mention_count == mean else float("inf")

    # Persist today's count (replace if already written today)
    today_str = dt.date.today().isoformat()
    history   = [e for e in history if e.get("date") != today_str]
    history.append({"date": today_str, "count": mention_count})
    history   = history[-MAX_HISTORY_DAYS:]
    baseline[ticker] = history
    _save_baseline(baseline)

    return {
        "social_heat_zscore": round(zscore, 2) if zscore is not None else None,
        "mention_count":      mention_count,
        "source_breakdown":   empty_breakdown,
    }
