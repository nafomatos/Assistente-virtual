"""StockTwits sentiment collector — DISABLED.

StockTwits consistently returns HTTP 403 for GitHub Actions runner IPs
(confirmed by 29 errors per daily run as of 2026-05-13).  The collector
has been fully removed from the pipeline; this stub is kept so that any
import that survived a partial refactor doesn't break with ImportError.

All callers in main.py have been removed.  If StockTwits unblocks the
runner IPs in the future, restore the original collector from git history
(git log --all -- collectors/stocktwits_sentiment.py).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_NULL = {
    "heat":  "unknown",
    "tone":  "neutral",
    "count": 0,
    "bulls": 0,
    "bears": 0,
}


def fetch_stocktwits_sentiment(ticker: str) -> dict:
    """Disabled — returns null result without making any network call."""
    logger.debug("StockTwits %s: collector disabled (HTTP 403 on CI runners)", ticker)
    return {**_NULL, "error": "collector_disabled"}
