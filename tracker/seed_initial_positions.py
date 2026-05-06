"""One-time script to seed the 14 positions from the live system's first 7 days.

Entry price convention
----------------------
entry_price = the closing price on the SIGNAL DATE (entry_date), taken directly
from the "Current price" field in the daily report for that date (logs/<date>.txt).
This is the price at which a trader would have acted on the recommendation at
end-of-day; it is NOT the next day's open.

For positions where entry_price is None the script fetches the closing price for
entry_date via yfinance. When yfinance is unavailable (network blocked) it falls
back to the hardcoded fallback_price, which must be sourced from the daily log
("Current price: $X.XX" line for that ticker on that date).

Fallback price lookup
---------------------
  - INTC  2026-05-05: logs/2026-05-05.txt → "Current price: $108.15 (+12.92% today)"
  - MU    2026-05-05: logs/2026-05-05.txt → "Current price: $640.20 (+11.06% today)"
  - POET  2026-05-05: logs/2026-05-05.txt → "Current price: $9.21 (+29.54% today)"
  - SMCI  2026-05-06: logs/2026-05-06.txt → "Current price: $34.66 (+24.54% today)"
  - AMD   2026-05-06: logs/2026-05-06.txt → "Current price: $421.39 (+18.61% today)"
  - ARM   2026-05-06: logs/2026-05-06.txt → "Current price: $237.30 (+13.63% today)"

Known bug (fixed in position_tracker.py)
-----------------------------------------
The original fetch_price() filtered history with:
    hist[hist.index.normalize() <= dt.datetime.combine(date, dt.time())]
This raises TypeError in pandas when the DatetimeIndex is tz-aware, causing the
filter to fail silently (exception caught, returns None → falls back to wrong price).
Fixed by using:
    hist[hist.index.date <= date]
which compares datetime.date objects directly, avoiding the tz mismatch entirely.

Usage:
    python -m tracker.seed_initial_positions
    python -m tracker.seed_initial_positions --dry-run   # print without writing
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from tracker.position_tracker import add_position, fetch_price

INITIAL_POSITIONS = [
    {
        "ticker": "SOFI",
        "direction": "long",
        "recommendation": "contrarian_buy",
        "confidence": 7,
        "entry_date": "2026-04-29",
        "entry_price": 15.52,
        "reasoning": "Volume 3.3x anomalous, z30=-3.87...",
    },
    {
        "ticker": "HOOD",
        "direction": "long",
        "recommendation": "contrarian_buy",
        "confidence": 7,
        "entry_date": "2026-04-29",
        "entry_price": 71.20,
        "reasoning": "Volume 2.6x anomalous, z30=-2.68...",
    },
    {
        "ticker": "GOOGL",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 8,
        "entry_date": "2026-04-30",
        "entry_price": 384.80,
        "reasoning": "z30=+3.41, z200=+5.08...",
    },
    {
        "ticker": "RDDT",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 8,
        "entry_date": "2026-05-01",
        "entry_price": 166.48,
        "reasoning": "Volume 3.0x, z200=+3.05...",
    },
    {
        "ticker": "SOUN",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 7,
        "entry_date": "2026-05-01",
        "entry_price": 9.56,
        "reasoning": "Volume 2.7x, z200=+3.80...",
    },
    {
        "ticker": "XRX",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 7,
        "entry_date": "2026-05-01",
        "entry_price": 2.70,
        "reasoning": "Volume 4.0x anomalous...",
    },
    {
        "ticker": "GME",
        "direction": "long",
        "recommendation": "contrarian_buy",
        "confidence": 7,
        "entry_date": "2026-05-04",
        "entry_price": 23.84,
        "reasoning": "Volume 5.3x, z200=-4.41...",
    },
    {
        "ticker": "NBIS",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 8,
        "entry_date": "2026-05-04",
        "entry_price": 176.42,
        "reasoning": "+14.20%, z200=+2.02...",
    },
    {
        "ticker": "INTC",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 6,
        "entry_date": "2026-05-05",
        "entry_price": None,
        # "Current price" from logs/2026-05-05.txt: $108.15 (+12.92% today)
        "fallback_price": 108.15,
        "reasoning": "RSI 84, z200=+2.57...",
    },
    {
        "ticker": "MU",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 6,
        "entry_date": "2026-05-05",
        "entry_price": None,
        # "Current price" from logs/2026-05-05.txt: $640.20 (+11.06% today)
        "fallback_price": 640.20,
        "reasoning": "RSI 82, z200=+2.48...",
    },
    {
        "ticker": "POET",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 6,
        "entry_date": "2026-05-05",
        "entry_price": None,
        # "Current price" from logs/2026-05-05.txt: $9.21 (+29.54% today)
        "fallback_price": 9.21,
        "reasoning": "+29.54%, z200=+3.52...",
    },
    {
        "ticker": "SMCI",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 9,
        "entry_date": "2026-05-06",
        "entry_price": None,
        # "Current price" from logs/2026-05-06.txt: $34.66 (+24.54% today)
        "fallback_price": 34.66,
        "reasoning": "+24.5%, z200=+4.84, vol 3.6x...",
    },
    {
        "ticker": "AMD",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 8,
        "entry_date": "2026-05-06",
        "entry_price": None,
        # "Current price" from logs/2026-05-06.txt: $421.39 (+18.61% today)
        "fallback_price": 421.39,
        "reasoning": "+18.6%, z200=+4.25, RSI 81...",
    },
    {
        "ticker": "ARM",
        "direction": "short",
        "recommendation": "reduce_exposure",
        "confidence": 6,
        "entry_date": "2026-05-06",
        "entry_price": None,
        # "Current price" from logs/2026-05-06.txt: $237.30 (+13.63% today)
        "fallback_price": 237.30,
        "reasoning": "+13.6%, z200=+3.51...",
    },
]


def seed(dry_run: bool = False) -> None:
    logger = logging.getLogger("seed")
    ok = 0
    failed = 0

    for spec in INITIAL_POSITIONS:
        ticker     = spec["ticker"]
        entry_date = spec["entry_date"]
        price      = spec["entry_price"]

        if price is None:
            date_obj = dt.date.fromisoformat(entry_date)
            logger.info("%s: fetching close price for %s…", ticker, entry_date)
            price = fetch_price(ticker, date_obj)
            if price is None:
                fallback = spec.get("fallback_price")
                if fallback is not None:
                    logger.warning(
                        "%s: yfinance unavailable — using fallback price %.2f",
                        ticker, fallback,
                    )
                    price = fallback
                else:
                    logger.error("%s: could not fetch price for %s — skipping", ticker, entry_date)
                    failed += 1
                    continue
            else:
                logger.info("%s: fetched price = %.2f", ticker, price)

        if dry_run:
            print(
                f"  DRY-RUN  {ticker:<6} {spec['direction']:<5} "
                f"conf={spec['confidence']}  "
                f"@ ${price:.2f}  on {entry_date}"
            )
            ok += 1
            continue

        pos = add_position(
            ticker=ticker,
            direction=spec["direction"],
            recommendation=spec["recommendation"],
            confidence=spec["confidence"],
            reasoning=spec["reasoning"],
            entry_price=price,
            entry_date=entry_date,
            macro_context={},
        )
        print(
            f"  {ticker:<6} {spec['direction']:<5} conf={spec['confidence']}  "
            f"@ ${pos['entry_price']:.2f}  on {pos['entry_date']}  "
            f"(d30: {pos['d30_target']})"
        )
        ok += 1

    print(f"\nDone. {ok} seeded, {failed} failed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed initial 14 positions into the tracker")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    print("Seeding initial positions…\n")
    seed(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
