"""CNN-style Fear & Greed Index via alternative.me.

Fetched once per run (not per ticker) and passed as shared macro context.

API: https://api.alternative.me/fng/?limit=2
    {
      "data": [
        {"value": "55", "value_classification": "Greed",       "timestamp": "..."},
        {"value": "48", "value_classification": "Neutral",     "timestamp": "..."}
      ]
    }
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.alternative.me/fng/"
TIMEOUT = 10


def fetch_fear_greed() -> dict | None:
    """Return today's Fear & Greed score plus direction vs yesterday.

    Shape:
        {"score": 55, "label": "Greed",
         "previous_score": 48, "direction": "improving|deteriorating|flat"}

    Returns None on network/parse failure (so the pipeline degrades gracefully
    instead of crashing).
    """
    try:
        resp = requests.get(API_URL, params={"limit": 2}, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"fear & greed fetch failed: {e}")
        return None

    data = payload.get("data") or []
    if not data:
        logger.warning("fear & greed response had no data")
        return None

    today = data[0]
    yesterday = data[1] if len(data) >= 2 else None

    try:
        score = int(today["value"])
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"fear & greed: bad today value: {e}")
        return None

    label = today.get("value_classification", "Unknown")

    prev_score: int | None = None
    if yesterday is not None:
        try:
            prev_score = int(yesterday["value"])
        except (KeyError, ValueError, TypeError):
            prev_score = None

    if prev_score is None:
        direction = "flat"
    elif score > prev_score:
        direction = "improving"
    elif score < prev_score:
        direction = "deteriorating"
    else:
        direction = "flat"

    return {
        "score":          score,
        "label":          label,
        "previous_score": prev_score,
        "direction":      direction,
    }


def format_summary(fg: dict | None) -> str:
    """One-line summary for the report header."""
    if fg is None:
        return "Fear & Greed: unavailable"

    delta = ""
    if fg["previous_score"] is not None:
        diff = fg["score"] - fg["previous_score"]
        sign = "+" if diff > 0 else ""
        delta = f" ({sign}{diff} vs yesterday, {fg['direction']})"
    return f"Fear & Greed: {fg['score']}/100 — {fg['label']}{delta}"
