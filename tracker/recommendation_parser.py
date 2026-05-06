"""Parse Claude.ai recommendation JSON and add directional entries to the tracker.

Only contrarian_buy and reduce_exposure are tracked; wait / no_action are skipped.
Entry price is fetched live from yfinance at parse time.
"""

from __future__ import annotations

import datetime as dt
import logging

from tracker.position_tracker import add_position, fetch_price

logger = logging.getLogger(__name__)

DIRECTIONAL = {"contrarian_buy", "reduce_exposure"}


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

        entry_price = fetch_price(ticker)
        if entry_price is None:
            logger.warning("%s: could not fetch current price — skipping", ticker)
            continue

        pos = add_position(
            ticker=ticker,
            direction=direction,
            recommendation=rec_type,
            confidence=int(rec.get("confidence") or 5),
            reasoning=(rec.get("reasoning") or "")[:400],
            entry_price=entry_price,
            entry_date=date.isoformat(),
            macro_context=macro_context,
        )
        added.append(pos)

    return added
