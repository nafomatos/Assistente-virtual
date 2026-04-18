"""Classifies current volume vs the 30d average."""

from __future__ import annotations


def analyze_volume(market_data: dict) -> dict:
    current = market_data["current_volume"]
    baseline = market_data["avg_volume_30d"]

    if baseline <= 0:
        return {"classification": "normal", "ratio": 0.0}

    ratio = current / baseline
    if ratio < 1.5:
        classification = "normal"
    elif ratio < 2.5:
        classification = "elevated"
    elif ratio < 5.0:
        classification = "anomalous"
    else:
        classification = "extreme"

    return {"classification": classification, "ratio": round(ratio, 2)}
