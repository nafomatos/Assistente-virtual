"""Classifies today's price move by z-score vs the 30d distribution."""

from __future__ import annotations


def analyze_price_velocity(market_data: dict) -> dict:
    daily_return = market_data["daily_return_pct"] / 100.0
    mean = market_data["returns_mean_30d"]
    std  = market_data["returns_std_30d"]

    if std <= 0:
        return {"classification": "normal", "z_score": 0.0, "direction": "flat"}

    z = (daily_return - mean) / std
    abs_z = abs(z)
    if abs_z < 1.0:
        classification = "normal"
    elif abs_z < 2.0:
        classification = "notable"
    elif abs_z < 3.0:
        classification = "extreme"
    else:
        classification = "blowout"

    direction = "up" if daily_return > 0 else ("down" if daily_return < 0 else "flat")

    return {
        "classification": classification,
        "z_score":  round(z, 2),
        "direction": direction,
    }
