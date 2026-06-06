"""One-off migration: retroactively close the 14 V1 positions.

The V1 close logic depends on live price fetch (yfinance). In the production
environment that fetch is blocked, so the 14 Apr-29 .. May-06 positions never
moved out of the "open" list even though every one of them is long past its
stop / d30 exit. This script applies the close logic retroactively using the
exit prices established in backtests/V1_RETROSPECTIVE_20260605.md (and, where a
price was never determinable from logs, the best-available last observed price).

It is idempotent: positions already in "closed" are left alone, and it only
closes tickers still present in "open".

Run once:

    python -m tracker.migrate_v1_close

After running, positions.json "open" is empty and "closed" holds 14 entries,
each with exit_price / exit_date / exit_reason / realized_pnl_pct / days_held
and the macro snapshot the position was opened into.
"""

from __future__ import annotations

import logging

from tracker.position_tracker import _load, _save, build_closed_record

logger = logging.getLogger(__name__)

# Macro snapshot at each entry date (from logs/<date>.txt headers).
_MACRO = {
    "2026-04-29": {"fear_greed": 26, "vix_structure": "Contango", "buffett": 227.0},
    "2026-04-30": {"fear_greed": 29, "vix_structure": "Contango", "buffett": 224.0},
    "2026-05-01": {"fear_greed": 26, "vix_structure": "Contango", "buffett": 226.0},
    "2026-05-04": {"fear_greed": 40, "vix_structure": "Contango", "buffett": 227.0},
    # 2026-05-05 Buffett was "unavailable" in the log; carry the adjacent reading.
    "2026-05-05": {"fear_greed": 50, "vix_structure": "Contango", "buffett": 226.0},
    "2026-05-06": {"fear_greed": 46, "vix_structure": "Contango", "buffett": 228.0},
}

# Exit data per ticker. exit_price=None marks a position with no determinable
# post-entry price in the logs (outcome stays "unknown").
#   estimate=True  → exit_price interpolated / best-available (see retrospective)
#   estimate=False → exit observed directly in the logs
_EXITS = {
    # Longs — both clean d30 winners (observed).
    "SOFI": dict(exit_price=18.22,  exit_date="2026-05-29", reason="CLOSED_D30",  estimate=False),
    "HOOD": dict(exit_price=94.30,  exit_date="2026-05-29", reason="CLOSED_D30",  estimate=False),
    # Shorts.
    "GOOGL": dict(exit_price=368.00, exit_date="2026-05-30", reason="CLOSED_D30", estimate=True),   # interpolated d30
    "RDDT":  dict(exit_price=None,   exit_date="2026-05-31", reason="CLOSED_D30", estimate=True),    # no post-entry price
    "SOUN":  dict(exit_price=8.88,   exit_date="2026-05-31", reason="CLOSED_D30", estimate=True),    # best-available May-08
    "XRX":   dict(exit_price=2.60,   exit_date="2026-05-31", reason="CLOSED_D30", estimate=True),    # best-available May-04
    "GME":   dict(exit_price=None,   exit_date="2026-06-03", reason="CLOSED_D30", estimate=True),    # no post-entry price
    "NBIS":  dict(exit_price=207.27, exit_date="2026-06-03", reason="CLOSED_D30", estimate=True),    # best-available May-13
    "INTC":  dict(exit_price=120.61, exit_date="2026-06-04", reason="CLOSED_D30", estimate=True),    # best-available May-12
    "MU":    dict(exit_price=800.25, exit_date="2026-05-13", reason="STOPPED_OUT", estimate=False),  # stop @ +25%
    "POET":  dict(exit_price=11.51,  exit_date="2026-05-07", reason="STOPPED_OUT", estimate=True),   # stop @ +25%
    "SMCI":  dict(exit_price=43.33,  exit_date="2026-05-22", reason="STOPPED_OUT", estimate=True),   # stop @ +25%
    "AMD":   dict(exit_price=526.74, exit_date="2026-06-03", reason="STOPPED_OUT", estimate=False),  # stop @ +25%
    "ARM":   dict(exit_price=213.31, exit_date="2026-06-05", reason="CLOSED_D30", estimate=True),    # best-available May-07
}


def migrate() -> dict:
    state = _load()
    still_open: list[dict] = []
    newly_closed: list[dict] = []

    for pos in state["open"]:
        ticker = pos["ticker"]
        exit_spec = _EXITS.get(ticker)
        if exit_spec is None:
            logger.warning("%s: no exit spec — leaving open", ticker)
            still_open.append(pos)
            continue

        # Backfill the macro snapshot if the position was stored with empty {}.
        if not pos.get("macro_context"):
            pos["macro_context"] = _MACRO.get(pos["entry_date"], {})

        closed = build_closed_record(
            pos,
            exit_price=exit_spec["exit_price"],
            exit_date=exit_spec["exit_date"],
            exit_reason=exit_spec["reason"],
        )
        closed["exit_estimated"] = exit_spec["estimate"]
        newly_closed.append(closed)
        logger.info(
            "closed %s %s: exit=%s reason=%s pnl=%s outcome=%s",
            ticker, pos["direction"],
            closed["exit_price"], closed["exit_reason"],
            closed["realized_pnl_pct"], closed["outcome"],
        )

    state["open"] = still_open
    state["closed"].extend(newly_closed)
    _save(state)
    return {"closed": newly_closed, "still_open": still_open}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = migrate()
    closed = result["closed"]
    correct = sum(1 for c in closed if (c["realized_pnl_pct"] or 0) > 0)
    incorrect = sum(1 for c in closed if c["realized_pnl_pct"] is not None and c["realized_pnl_pct"] <= 0)
    unknown = sum(1 for c in closed if c["realized_pnl_pct"] is None)
    print(f"\nMigrated {len(closed)} position(s) to closed.")
    print(f"  correct (pnl>0): {correct}")
    print(f"  incorrect (pnl<=0): {incorrect}")
    print(f"  unknown (no price): {unknown}")
    print(f"  still open: {len(result['still_open'])}")
