"""Main orchestrator — collects market data, runs analyzers,
writes a single .txt report, and emails it.

Usage:
    python main.py                   # default: NVDA TSLA GC=F
    python main.py NVDA TSLA AAPL    # custom tickers
    python main.py --no-email        # skip the email step
"""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from analyzers.price_velocity import analyze_price_velocity
from analyzers.volume_analyzer import analyze_volume
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


def run_pipeline(tickers: list[str]) -> list[dict]:
    results = []
    for ticker in tickers:
        logger.info(f"--- {ticker} ---")
        try:
            market = fetch_market_data(ticker, LOOKBACK_DAYS)
        except Exception as e:
            logger.error(f"{ticker}: market data failed: {e}")
            continue

        volume = analyze_volume(market)
        velocity = analyze_price_velocity(market)
        signals = {"market": market, "volume": volume, "velocity": velocity}
        results.append({"ticker": ticker, "signals": signals})
    return results


def print_signal_summary(results: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("SIGNAL SUMMARY (pre-filter)")
    print("=" * 72)
    for r in results:
        ticker = r["ticker"]
        name = TICKER_NAMES.get(ticker, ticker)
        m = r["signals"]["market"]
        v = r["signals"]["volume"]
        p = r["signals"]["velocity"]
        status = "INCLUDED" if passes_prefilter(r["signals"]) else "filtered-out"
        print(
            f"[{ticker:>5}] {name:<18} "
            f"price=${m['current_price']:>10,.2f}  "
            f"ret={m['daily_return_pct']:+6.2f}%  "
            f"vol={v['ratio']}x ({v['classification']})  "
            f"z={p['z_score']} ({p['classification']},{p['direction']})  "
            f"-> {status}"
        )


if __name__ == "__main__":
    argv = sys.argv[1:]
    send_email = "--no-email" not in argv
    tickers = [a for a in argv if not a.startswith("--")] or ["NVDA", "TSLA", "GC=F"]

    results = run_pipeline(tickers)
    print_signal_summary(results)

    path, included, skipped = write_document(results)
    print(f"\nReport written to: {path}")
    print(f"Included: {included or '(none)'}")
    print(f"Skipped : {skipped or '(none)'}")

    if send_email:
        try:
            send_report(report_path=path)
            print("Email sent.")
        except EmailConfigError as e:
            logger.warning(f"email skipped: {e}")
            print(f"Email skipped: {e}")
        except Exception as e:
            logger.exception("email send failed")
            # non-zero exit so the GitHub Action surfaces the failure
            sys.exit(f"Email send failed: {e}")
