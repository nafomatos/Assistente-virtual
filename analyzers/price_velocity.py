"""Classifies today's price move by z-score against two windows:
a fast 30d distribution and a slow 200d distribution.

When the move is extreme on BOTH timeframes (|z_30d|>2 AND |z_200d|>2)
we set macro_extreme=True — that's a much rarer, more meaningful signal
than a one-off spike against a single window.
"""

from __future__ import annotations


def _classify(abs_z: float) -> str:
    if abs_z < 1.0:
        return "normal"
    if abs_z < 2.0:
        return "notable"
    if abs_z < 3.0:
        return "extreme"
    return "blowout"


def _z(daily_return: float, mean: float, std: float) -> float:
    if std <= 0:
        return 0.0
    return (daily_return - mean) / std


def analyze_price_velocity(market_data: dict) -> dict:
    daily_return = market_data["daily_return_pct"] / 100.0

    z30  = _z(daily_return,
              market_data["returns_mean_30d"],
              market_data["returns_std_30d"])
    z200 = _z(daily_return,
              market_data.get("returns_mean_200d", 0.0),
              market_data.get("returns_std_200d", 0.0))

    z_primary = z30 if abs(z30) >= abs(z200) else z200
    classification = _classify(abs(z_primary))

    if daily_return > 0:
        direction = "up"
    elif daily_return < 0:
        direction = "down"
    else:
        direction = "flat"

    macro_extreme = abs(z30) > 2.0 and abs(z200) > 2.0

    return {
        "classification": classification,
        "z_score":        round(z_primary, 2),  # kept for backwards compatibility
        "z_score_30d":    round(z30,  2),
        "z_score_200d":   round(z200, 2),
        "macro_extreme":  macro_extreme,
        "direction":      direction,
    }
