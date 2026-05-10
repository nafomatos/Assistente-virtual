"""Position sizing, price targets, time windows, and option strikes.

Pure post-classification math — no API calls, no new data sources.
All functions operate on dicts produced by the main pipeline and the
Claude classification step.
"""

from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)


def compute_position_size(signal: dict, macro_context: dict) -> float:
    """Return position size as a percentage of capital.

    Returns 0.0 for non-directional recommendations or confidence < 6.

    signal keys used: confidence (int), recommendation (str), cluster_boost (dict|None)
    macro_context keys: buffett_indicator (float, ratio_pct e.g. 231),
                        fear_greed (int, 0-100 score)
    """
    confidence = signal.get("confidence", 0)

    if confidence >= 9:
        tier_base = 3.0
    elif confidence >= 7:
        tier_base = 2.0
    elif confidence >= 6:
        tier_base = 1.0
    else:
        return 0.0

    rec = signal.get("recommendation", "")
    if rec == "contrarian_buy":
        rec_mult = 1.2
    elif rec == "reduce_exposure":
        rec_mult = 1.0
    else:
        return 0.0

    cluster_mult = 1.25 if signal.get("cluster_boost") else 1.0

    buffett = macro_context.get("buffett_indicator", 0)
    fg      = macro_context.get("fear_greed", 100)
    macro_damp = 0.7 if (buffett > 220 or fg < 40) else 1.0

    return tier_base * rec_mult * cluster_mult * macro_damp


def compute_price_targets(
    current_price: float,
    z_score_30d: float,
    returns_std_30d: float,
    recommendation: str,
) -> dict:
    """Return three price targets from z-score reversion math.

    S = current_price * returns_std_30d  (dollar volatility)
    M = current_price - z_score_30d * S  (implied mean reference price)

    For reduce_exposure (bearish): targets at z=+1, z=0, z=-1
    For contrarian_buy  (bullish): targets at z=-1, z=0, z=+1
    """
    S = current_price * returns_std_30d
    M = current_price - z_score_30d * S
    is_bearish = recommendation == "reduce_exposure"

    if is_bearish:
        conservative = M + S   # z = +1
        medium       = M       # z =  0
        aggressive   = M - S   # z = -1
    else:
        conservative = M - S   # z = -1
        medium       = M       # z =  0
        aggressive   = M + S   # z = +1

    return {
        "conservative": round(conservative, 2),
        "medium":       round(medium,       2),
        "aggressive":   round(aggressive,   2),
        "is_bearish":   is_bearish,
    }


def compute_option_strikes(current_price: float, recommendation: str) -> dict:
    """Return ATM, OTM 5%, OTM 10% strikes (display only, no IV or expiry logic).

    Shorts (reduce_exposure): OTM strikes are below current price.
    Longs (contrarian_buy):   OTM strikes are above current price.
    """
    atm      = round(current_price)
    is_short = recommendation == "reduce_exposure"

    if is_short:
        otm_5pct  = round(current_price * 0.95)
        otm_10pct = round(current_price * 0.90)
    else:
        otm_5pct  = round(current_price * 1.05)
        otm_10pct = round(current_price * 1.10)

    return {"atm": atm, "otm_5pct": otm_5pct, "otm_10pct": otm_10pct}


def compute_time_windows(today: datetime.date | None = None) -> dict:
    """Return d+10 checkpoint and d+30 close dates as ISO strings.

    d+10 advances past weekends so the checkpoint is always a weekday.
    d+30 is a calendar date (weekends acceptable for the close target).
    """
    if today is None:
        today = datetime.date.today()

    d10 = today + datetime.timedelta(days=10)
    while d10.weekday() >= 5:   # skip Saturday (5) and Sunday (6)
        d10 += datetime.timedelta(days=1)

    d30 = today + datetime.timedelta(days=30)

    return {"d10": d10.isoformat(), "d30": d30.isoformat()}


def compute_sizing_block(
    classified_signal: dict,
    market_data: dict,
    velocity_data: dict,
    macro_context: dict,
    today: datetime.date | None = None,
) -> dict | None:
    """Assemble the full sizing block for one signal.

    Returns None when position_size == 0 (non-actionable signal) or when
    required price/z-score data is missing.  Never raises — logs a warning
    and returns None on any unexpected failure.

    classified_signal: Claude output dict (confidence, recommendation, cluster_boost)
    market_data:       r["signals"]["market"] (current_price, returns_std_30d)
    velocity_data:     r["signals"]["velocity"] (z_score_30d)
    macro_context:     {"buffett_indicator": float, "fear_greed": int}
    """
    try:
        position_size = compute_position_size(classified_signal, macro_context)
        if position_size == 0:
            return None

        current_price   = market_data.get("current_price")
        z_score_30d     = velocity_data.get("z_score_30d")
        returns_std_30d = market_data.get("returns_std_30d")

        if None in (current_price, z_score_30d, returns_std_30d):
            logger.warning(
                "position_sizing: missing data for %s (price=%s z30=%s std=%s)",
                classified_signal.get("ticker", "?"),
                current_price, z_score_30d, returns_std_30d,
            )
            return None

        recommendation = classified_signal.get("recommendation", "")

        targets = compute_price_targets(
            current_price, z_score_30d, returns_std_30d, recommendation
        )
        strikes = compute_option_strikes(current_price, recommendation)
        windows = compute_time_windows(today)

        return {
            "position_size_pct": round(position_size, 2),
            "targets":           targets,
            "strikes":           strikes,
            "windows":           windows,
        }
    except Exception as exc:
        logger.warning(
            "position_sizing: compute_sizing_block failed for %s: %s",
            classified_signal.get("ticker", "?"), exc,
        )
        return None


def format_sizing_text(ticker: str, sizing_block: dict) -> str:
    """Format a sizing block as a plain-text block for paste/log output."""
    size = sizing_block["position_size_pct"]
    t    = sizing_block["targets"]
    w    = sizing_block["windows"]
    s    = sizing_block["strikes"]

    is_bearish = t.get("is_bearish", False)
    if is_bearish:
        z_labels = ("z=+1", "z=0", "z=-1")
    else:
        z_labels = ("z=-1", "z=0", "z=+1")

    def _px(v: float) -> str:
        return f"${v:,.2f}"

    return (
        f"[{ticker}] \U0001f3af SIZING & TARGETS\n"
        f"  Position size:   {size:.2f}% of capital\n"
        f"  Targets:         conservative {_px(t['conservative'])} ({z_labels[0]})"
        f" | medium {_px(t['medium'])} ({z_labels[1]})"
        f" | aggressive {_px(t['aggressive'])} ({z_labels[2]})\n"
        f"  Window:          checkpoint {w['d10']} (d+10) · close {w['d30']} (d+30)\n"
        f"  Option strikes:  ATM ${s['atm']:,} | OTM 5% ${s['otm_5pct']:,}"
        f" | OTM 10% ${s['otm_10pct']:,}"
    )
