"""Main orchestrator.

Steps:
  1. Check US market calendar — if today isn't a normal trading day,
     log and exit cleanly (no email, no log write).
  2. Fetch Fear & Greed once (shared macro context).
  3. For each ticker: market_data → volume / velocity / RSI analyzers.
  4. Build the paste-ready .txt report.
  5. Copy to logs/YYYY-MM-DD.txt.
  6. Email it (unless --no-email).

Usage:
    python main.py                      # default tickers
    python main.py NVDA TSLA AAPL       # custom tickers
    python main.py --no-email
    python main.py --date 2026-04-18    # test with a specific date (weekend ok)
    python main.py --force              # bypass market calendar check
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import sys

from dotenv import load_dotenv

from analyzers.price_velocity import analyze_price_velocity
from analyzers.rsi import analyze_rsi
from analyzers.volume_analyzer import analyze_volume
from collectors.fear_greed import fetch_fear_greed, format_summary as format_fg
from collectors.market_data import fetch_market_data
from config import LOOKBACK_DAYS, TICKER_NAMES
from delivery.email_sender import EmailConfigError, send_report
from output.document_builder import passes_prefilter, write_document

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("radar")

LOGS_DIR = "logs"
# Normal NYSE session is 6h 30m; early closes shorten it to ~3h 30m.
# Treating anything under 6h as "not a full session".
FULL_SESSION_MIN_HOURS = 6.0


def check_trading_day(date: dt.date) -> tuple[bool, str]:
    """Return (ok, reason). ok=False if today is a weekend, holiday, or
    early close on NYSE."""
    # Import lazily so `--force` / tests don't require the dep to be present.
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=date, end_date=date)
    if sched.empty:
        weekday = date.strftime("%A")
        if date.weekday() >= 5:
            return False, f"{weekday} — weekend"
        return False, f"{weekday} — NYSE holiday"

    row = sched.iloc[0]
    session_hours = (row["market_close"] - row["market_open"]).total_seconds() / 3600
    if session_hours < FULL_SESSION_MIN_HOURS:
        return False, f"early close ({session_hours:.1f}h session)"
    return True, "normal trading day"


def run_pipeline(tickers: list[str]) -> list[dict]:
    results = []
    for ticker in tickers:
        logger.info(f"--- {ticker} ---")
        try:
            market = fetch_market_data(ticker, LOOKBACK_DAYS)
        except Exception as e:
            logger.error(f"{ticker}: market data failed: {e}")
            continue

        volume   = analyze_volume(market)
        velocity = analyze_price_velocity(market)
        rsi      = analyze_rsi(market)
        signals = {
            "market":   market,
            "volume":   volume,
            "velocity": velocity,
            "rsi":      rsi,
        }
        results.append({"ticker": ticker, "signals": signals})
    return results


def print_signal_summary(results: list[dict]) -> None:
    print("\n" + "=" * 84)
    print("SIGNAL SUMMARY (pre-filter)")
    print("=" * 84)
    for r in results:
        ticker = r["ticker"]
        name = TICKER_NAMES.get(ticker, ticker)
        m = r["signals"]["market"]
        v = r["signals"]["volume"]
        p = r["signals"]["velocity"]
        rs = r["signals"]["rsi"]
        status = "INCLUDED" if passes_prefilter(r["signals"]) else "filtered-out"
        macro = " [MACRO]" if p.get("macro_extreme") else ""
        print(
            f"[{ticker:>5}] {name:<18} "
            f"px=${m['current_price']:>10,.2f}  "
            f"ret={m['daily_return_pct']:+6.2f}%  "
            f"vol={v['ratio']}x ({v['classification']})  "
            f"z30={p['z_score_30d']:+.2f} z200={p['z_score_200d']:+.2f}{macro}  "
            f"RSI={rs['rsi']} ({rs['classification']})  "
            f"-> {status}"
        )


def archive_log(report_path: str, date: dt.date, logs_dir: str = LOGS_DIR) -> str:
    """Copy the generated report into logs/ for the GitHub Action to commit back."""
    os.makedirs(logs_dir, exist_ok=True)
    target = os.path.join(logs_dir, f"{date.isoformat()}.txt")
    shutil.copyfile(report_path, target)
    logger.info(f"archived log: {target}")
    return target


def _parse_args(argv: list[str]) -> tuple[list[str], bool, bool, dt.date]:
    tickers: list[str] = []
    send_email = True
    force = False
    date = dt.date.today()

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-email":
            send_email = False
        elif a == "--force":
            force = True
        elif a == "--date":
            i += 1
            date = dt.date.fromisoformat(argv[i])
        elif a.startswith("--"):
            raise SystemExit(f"unknown flag: {a}")
        else:
            tickers.append(a)
        i += 1

    if not tickers:
        tickers = ["NVDA", "TSLA", "GC=F"]
    return tickers, send_email, force, date


def main(argv: list[str]) -> int:
    tickers, send_email, force, date = _parse_args(argv)

    ok, reason = (True, "forced") if force else check_trading_day(date)
    logger.info(f"market check for {date.isoformat()}: {reason}")
    if not ok:
        print(f"Market closed on {date.isoformat()} ({reason}). Exiting cleanly.")
        return 0

    fear_greed = fetch_fear_greed()
    logger.info(format_fg(fear_greed))

    results = run_pipeline(tickers)
    print_signal_summary(results)

    path, included, skipped = write_document(results, today=date, fear_greed=fear_greed)
    print(f"\nReport written to: {path}")
    print(f"Included: {included or '(none)'}")
    print(f"Skipped : {skipped or '(none)'}")

    archive_log(path, date)

    if send_email:
        try:
            send_report(report_path=path, date=date)
            print("Email sent.")
        except EmailConfigError as e:
            logger.warning(f"email skipped: {e}")
            print(f"Email skipped: {e}")
        except Exception as e:
            logger.exception("email send failed")
            print(f"Email send failed: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
