"""Parse Claude.ai recommendation JSON and add directional entries to the tracker.

Only contrarian_buy and reduce_exposure are tracked; wait / no_action are skipped.
Entry price is fetched live from yfinance at parse time.
"""

from __future__ import annotations

import datetime as dt
import logging

from claude_advisor.signal_gates import MIN_LONG_CONFIDENCE, MIN_SHORT_CONFIDENCE
from tracker.position_tracker import add_position, fetch_price

logger = logging.getLogger(__name__)

DIRECTIONAL = {"contrarian_buy", "reduce_exposure"}

DEFAULT_CONFIDENCE = 5


def _parse_confidence(raw: object) -> int:
    """Coerce a recommendation's confidence to an int in [1, 10].

    Malformed or missing values fall back to DEFAULT_CONFIDENCE instead of
    raising, so one bad recommendation cannot abort the whole batch.
    """
    try:
        confidence = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning(
            "unparseable confidence %r — defaulting to %d", raw, DEFAULT_CONFIDENCE
        )
        confidence = DEFAULT_CONFIDENCE
    return max(1, min(10, confidence))


def parse_and_add(
    recommendations: list[dict],
    date: dt.date | None = None,
    macro_context: dict | None = None,
) -> list[dict]:
    """Filter directional recommendations and add them as open positions.

    Args:
        recommendations: list of recommendation dicts from Claude.ai output.
        date:            entry date to record (defaults to today).
        macro_context:   snapshot of macro indicators at time of recording.

    Returns:
        List of position dicts that were added (skips already-tracked duplicates
        and non-directional entries).
    """
    date = date or dt.date.today()
    added: list[dict] = []

    for rec in recommendations:
        rec_type = rec.get("recommendation")
        ticker   = (rec.get("ticker") or "").strip().upper()

        if not ticker:
            logger.warning("recommendation missing ticker field — skipping")
            continue

        if rec_type not in DIRECTIONAL:
            logger.info("%s: skipping non-directional recommendation (%s)", ticker, rec_type)
            continue

        direction = "long" if rec_type == "contrarian_buy" else "short"
        confidence = _parse_confidence(rec.get("confidence"))

        # Strategy v2 actionable-confidence floors, enforced in code (the
        # prompt states them too, but prompt rules are advisory). A
        # reduce_exposure capped to 5 by the macro fear-cap (or otherwise
        # below 6) is an observation, not a trade; contrarian_buy requires 7.
        floor = MIN_SHORT_CONFIDENCE if direction == "short" else MIN_LONG_CONFIDENCE
        if confidence < floor:
            logger.info(
                "%s: skipping %s below actionable confidence floor (conf=%d < %d)",
                ticker, direction, confidence, floor,
            )
            continue

        entry_price = fetch_price(ticker)
        if entry_price is None:
            logger.warning("%s: could not fetch current price — skipping", ticker)
            continue

        pos = add_position(
            ticker=ticker,
            direction=direction,
            recommendation=rec_type,
            confidence=confidence,
            reasoning=(rec.get("reasoning") or "")[:400],
            entry_price=entry_price,
            entry_date=date.isoformat(),
            macro_context=macro_context,
        )
        added.append(pos)

    return added
