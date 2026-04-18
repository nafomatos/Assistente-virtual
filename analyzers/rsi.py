"""14-day RSI with classification bands.

Uses Wilder's smoothing (the canonical RSI formulation). Expects a list
of recent daily closes via market_data["closes_recent"].
"""

from __future__ import annotations

PERIOD = 14


def _rsi_wilder(closes: list[float], period: int = PERIOD) -> float | None:
    """Canonical Wilder RSI. Returns None if there isn't enough history."""
    if len(closes) < period + 1:
        return None

    gains  = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period

    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _classify(rsi: float) -> str:
    if rsi < 20:
        return "extreme_oversold"
    if rsi < 30:
        return "oversold"
    if rsi > 80:
        return "extreme_overbought"
    if rsi > 70:
        return "overbought"
    return "normal"


def analyze_rsi(market_data: dict) -> dict:
    closes = market_data.get("closes_recent") or []
    rsi = _rsi_wilder(closes, PERIOD)
    if rsi is None:
        return {"rsi": None, "classification": "normal", "period": PERIOD}
    return {
        "rsi":            round(rsi, 1),
        "classification": _classify(rsi),
        "period":         PERIOD,
    }
