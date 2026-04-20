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
    python main.py --debug              # run all 18, print per-ticker reasons,
                                        # skip email + log archival
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
from config import ALL_TICKERS, LOOKBACK_DAYS, SOCIAL_HEAT_THRESHOLD, TICKER_NAMES
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


def _prefilter_reason(signals: dict) -> str:
    """Explain, per ticker, why the pre-filter passed or failed.

    Uses the same 4 conditions as output.document_builder.passes_prefilter
    so the debug table reflects exactly what the report will do.
    """
    v = signals["volume"]
    p = signals["velocity"]
    heat = (signals.get("sentiment") or {}).get("social_heat", 0)

    hits: list[str] = []
    if p.get("macro_extreme"):
        hits.append(f"macro_extreme(z30={p['z_score_30d']:+.2f},z200={p['z_score_200d']:+.2f})")
    if v["classification"] in ("anomalous", "extreme"):
        hits.append(f"volume={v['classification']}({v['ratio']}x)")
    if p["classification"] in ("extreme", "blowout"):
        hits.append(f"velocity={p['classification']}(|z|>=2)")
    if heat > SOCIAL_HEAT_THRESHOLD:
        hits.append(f"social_heat={heat}>{SOCIAL_HEAT_THRESHOLD}")

    if hits:
        return "PASS: " + "; ".join(hits)
    return (
        f"SKIP: vol={v['classification']}({v['ratio']}x), "
        f"vel={p['classification']}(z30={p['z_score_30d']:+.2f},z200={p['z_score_200d']:+.2f}), "
        f"heat={heat}"
    )


def print_debug_table(results: list[dict]) -> None:
    """Debug-mode per-ticker table: ticker | vol | z30 | z200 | RSI | reason."""
    print("\n" + "=" * 120)
    print("DEBUG — raw signals for all tickers (pre-filter bypassed for display)")
    print("=" * 120)
    header = (
        f"{'TICKER':<7} {'VOL_RATIO':>10} {'Z_30D':>8} {'Z_200D':>8} "
        f"{'RSI':>6} {'RSI_CLASS':<18} REASON"
    )
    print(header)
    print("-" * 120)

    n_pass = n_skip = 0
    for r in results:
        ticker = r["ticker"]
        v = r["signals"]["volume"]
        p = r["signals"]["velocity"]
        rs = r["signals"]["rsi"]
        reason = _prefilter_reason(r["signals"])
        if reason.startswith("PASS"):
            n_pass += 1
        else:
            n_skip += 1

        rsi_str = f"{rs['rsi']:.1f}" if rs.get("rsi") is not None else "n/a"
        print(
            f"{ticker:<7} {v['ratio']:>9.2f}x "
            f"{p['z_score_30d']:>+8.2f} {p['z_score_200d']:>+8.2f} "
            f"{rsi_str:>6} {rs['classification']:<18} {reason}"
        )

    print("-" * 120)
    print(f"Totals: {n_pass} would pass, {n_skip} would be filtered out, {len(results)} fetched")


def archive_log(report_path: str, date: dt.date, logs_dir: str = LOGS_DIR) -> str:
    """Copy the generated report into logs/ for the GitHub Action to commit back."""
    os.makedirs(logs_dir, exist_ok=True)
    target = os.path.join(logs_dir, f"{date.isoformat()}.txt")
    shutil.copyfile(report_path, target)
    logger.info(f"archived log: {target}")
    return target


def _parse_args(argv: list[str]) -> tuple[list[str], bool, bool, bool, dt.date]:
    tickers: list[str] = []
    send_email = True
    force = False
    debug = False
    date = dt.date.today()

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-email":
            send_email = False
        elif a == "--force":
            force = True
        elif a == "--debug":
            debug = True
        elif a == "--date":
            i += 1
            date = dt.date.fromisoformat(argv[i])
        elif a.startswith("--"):
            raise SystemExit(f"unknown flag: {a}")
        else:
            tickers.append(a)
        i += 1

    # Debug mode: always run all 18 (unless user gave an explicit list),
    # never send email, bypass the calendar guard so it works off-hours.
    if debug:
        send_email = False
        force = True
        if not tickers:
            tickers = list(ALL_TICKERS)

    if not tickers:
        tickers = ["NVDA", "TSLA", "GC=F"]
    return tickers, send_email, force, debug, date


def main(argv: list[str]) -> int:
    tickers, send_email, force, debug, date = _parse_args(argv)

    ok, reason = (True, "forced") if force else check_trading_day(date)
    logger.info(f"market check for {date.isoformat()}: {reason}")
    if not ok:
        print(f"Market closed on {date.isoformat()} ({reason}). Exiting cleanly.")
        return 0

    fear_greed = fetch_fear_greed()
    logger.info(format_fg(fear_greed))

    results = run_pipeline(tickers)
    print_signal_summary(results)

    if debug:
        print_debug_table(results)
        print("\n[debug mode] skipping report write, log archive, and email.")
        return 0

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
