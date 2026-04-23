"""Social-heat aggregator.

Combines StockTwits and YouTube signals into a single `social_heat_zscore`
and a formatted `source_breakdown` dict.

Weights (when both sources available):
    StockTwits  — 60 %   (currently blocked by 403; treated as unavailable)
    YouTube     — 40 %   (becomes 100 % when StockTwits is unavailable)

The z-score is computed on YouTube video_count against a 30-day rolling
baseline stored in logs/sentiment_baseline.json.

StockTwits heat is mapped to a numeric score (explosive=100, elevated=70,
stable=30, low=10) and exposed as `stocktwits_heat` for the pre-filter in
document_builder.py.

Usage
-----
    stocktwits_data = fetch_stocktwits_sentiment(ticker)
    youtube_data    = fetch_youtube_signals(ticker, name)   # RED/AMBER only
    sentiment       = aggregate_sentiment(ticker,
                                          stocktwits=stocktwits_data,
                                          youtube=youtube_data)

Return shape
------------
    {
        "social_heat_zscore": float | None,
        "video_count":        int   | None,
        "stocktwits_heat":    str   | None,  # "explosive"|"elevated"|"stable"|"low"|None
        "stocktwits_score":   int   | None,  # 100|70|30|10|None
        "source_breakdown": {
            "stocktwits": str,   # "heat=elevated, tone=bearish, bulls=3, bears=12" or "n/a"
            "youtube":    str,   # "heat=elevated, tone=bearish, top=..." or "n/a"
            "twitter":    str,   # "n/a" until Phase 5
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


# ── baseline persistence ────────────────────────────────────────────────────

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


# ── per-source formatters ───────────────────────────────────────────────────

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


def _format_youtube(yt: dict | None) -> str:
    if not yt or yt.get("video_count", 0) == 0:
        return "n/a"
    heat = yt.get("heat", "low")
    tone = yt.get("tone", "neutral")
    top  = (yt.get("top_videos") or [])
    result = f"heat={heat}, tone={tone}"
    if top:
        title   = top[0].get("title", "")[:60]
        views   = top[0].get("views", 0)
        views_s = f"{views / 1000:.0f}k" if views >= 1000 else str(views)
        result += f', top="{title}" ({views_s} views)'
    return result


# ── public API ──────────────────────────────────────────────────────────────

def aggregate_sentiment(
    ticker:     str,
    stocktwits: dict | None = None,
    youtube:    dict | None = None,
) -> dict:
    """Compute social_heat_zscore and assemble source_breakdown.

    The z-score baseline is updated only when youtube contains a live
    video_count.  StockTwits heat is exposed directly for the
    document_builder pre-filter without being folded into the z-score.
    """
    # StockTwits heat level and numeric score
    raw_heat = (stocktwits or {}).get("heat")
    st_heat  = raw_heat if raw_heat in _ST_HEAT_SCORE else None
    st_score = _ST_HEAT_SCORE.get(raw_heat) if raw_heat else None

    breakdown = {
        "stocktwits": _format_stocktwits(stocktwits),
        "youtube":    _format_youtube(youtube),
        "twitter":    "n/a",
    }

    video_count: int | None = (youtube or {}).get("video_count")

    if video_count is None:
        return {
            "social_heat_zscore": None,
            "video_count":        None,
            "stocktwits_heat":    st_heat,
            "stocktwits_score":   st_score,
            "source_breakdown":   breakdown,
        }

    # Z-score against 30-day rolling YouTube video_count baseline
    baseline = _load_baseline()
    history: list[dict] = baseline.get(ticker, [])

    zscore: float | None = None
    if len(history) >= MIN_HISTORY_DAYS:
        counts = [e["count"] for e in history[-MAX_HISTORY_DAYS:]]
        mean   = statistics.mean(counts)
        std    = statistics.pstdev(counts)
        if std > 0:
            zscore = (video_count - mean) / std
        else:
            zscore = 0.0 if video_count == mean else float("inf")

    today_str = dt.date.today().isoformat()
    history   = [e for e in history if e.get("date") != today_str]
    history.append({"date": today_str, "count": video_count})
    history   = history[-MAX_HISTORY_DAYS:]
    baseline[ticker] = history
    _save_baseline(baseline)

    return {
        "social_heat_zscore": round(zscore, 2) if zscore is not None else None,
        "video_count":        video_count,
        "stocktwits_heat":    st_heat,
        "stocktwits_score":   st_score,
        "source_breakdown":   breakdown,
    }
