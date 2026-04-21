"""Social-heat aggregator.

Combines signals from all available sentiment sources into a single
`social_heat_zscore` and a formatted `source_breakdown` dict.

Source weights (planned):
    Reddit      — 40 %   (live)
    StockTwits  — 30 %   (live)
    X           — 20 %   (Phase 5)
    YouTube     — 10 %   (Phase 5)

The z-score is computed on Reddit mention counts against a 30-day rolling
baseline stored in logs/sentiment_baseline.json.

StockTwits heat is mapped to a numeric score (explosive=100, elevated=70,
stable=30, low=10) and exposed as `stocktwits_heat` for the pre-filter in
document_builder.py.

Usage
-----
    reddit_data     = fetch_reddit_signals(ticker, name)
    stocktwits_data = fetch_stocktwits_sentiment(ticker)
    sentiment       = aggregate_sentiment(ticker,
                                          reddit=reddit_data,
                                          stocktwits=stocktwits_data)

Return shape
------------
    {
        "social_heat_zscore": float | None,
        "mention_count":      int   | None,
        "stocktwits_heat":    str   | None,  # "explosive"|"elevated"|"stable"|"low"|None
        "stocktwits_score":   int   | None,  # 100|70|30|10|None
        "source_breakdown": {
            "reddit":      str,   # "Reddit (24h): 47 mentions, …" or "n/a"
            "stocktwits":  str,   # "heat=elevated, tone=bearish, bulls=3, bears=12" or "n/a"
            "twitter":     str,   # "n/a" until Phase 5
            "youtube":     str,   # "n/a" until Phase 5
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
MIN_HISTORY_DAYS = 7
MAX_HISTORY_DAYS = 30

_ST_HEAT_SCORE: dict[str, int] = {
    "explosive": 100,
    "elevated":   70,
    "stable":     30,
    "low":        10,
}


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
# Per-source formatters
# ---------------------------------------------------------------------------

def _format_reddit(reddit: dict | None) -> str:
    if reddit is None or reddit.get("mention_count") is None:
        return "n/a"
    count = reddit["mention_count"]
    avg   = reddit.get("avg_score")
    trend = reddit.get("trending")
    tone  = reddit.get("sentiment_tone")
    parts: list[str] = [f"{count} mentions"]
    if avg is not None:
        parts.append(f"avg_score={avg:.0f}")
    if trend is not None:
        parts.append(f"trending={'YES' if trend else 'NO'}")
    if tone:
        parts.append(f"tone={tone}")
    return "Reddit (24h): " + ", ".join(parts)


def _format_stocktwits(st: dict | None) -> str:
    if st is None:
        return "n/a"
    heat = st.get("heat", "unknown")
    if heat == "unknown":
        return "n/a"
    tone  = st.get("tone", "neutral")
    bulls = st.get("bulls", 0)
    bears = st.get("bears", 0)
    return f"heat={heat}, tone={tone}, bulls={bulls}, bears={bears}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aggregate_sentiment(
    ticker:     str,
    reddit:     dict | None = None,
    stocktwits: dict | None = None,
) -> dict:
    """Compute social_heat_zscore and assemble source_breakdown.

    The z-score baseline is updated only when reddit contains a live
    mention_count.  StockTwits heat is exposed directly for the
    document_builder pre-filter without being folded into the z-score.
    """
    # --- StockTwits heat level and numeric score ---
    raw_heat = (stocktwits or {}).get("heat")
    st_heat  = raw_heat if raw_heat in _ST_HEAT_SCORE else None
    st_score = _ST_HEAT_SCORE.get(raw_heat) if raw_heat else None

    breakdown = {
        "reddit":     _format_reddit(reddit),
        "stocktwits": _format_stocktwits(stocktwits),
        "twitter":    "n/a",
        "youtube":    "n/a",
    }

    mention_count: int | None = (reddit or {}).get("mention_count")

    if mention_count is None:
        return {
            "social_heat_zscore": None,
            "mention_count":      None,
            "stocktwits_heat":    st_heat,
            "stocktwits_score":   st_score,
            "source_breakdown":   breakdown,
        }

    # --- Z-score against 30-day rolling Reddit baseline ---
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
            zscore = 0.0 if mention_count == mean else float("inf")

    today_str = dt.date.today().isoformat()
    history   = [e for e in history if e.get("date") != today_str]
    history.append({"date": today_str, "count": mention_count})
    history   = history[-MAX_HISTORY_DAYS:]
    baseline[ticker] = history
    _save_baseline(baseline)

    return {
        "social_heat_zscore": round(zscore, 2) if zscore is not None else None,
        "mention_count":      mention_count,
        "stocktwits_heat":    st_heat,
        "stocktwits_score":   st_score,
        "source_breakdown":   breakdown,
    }
