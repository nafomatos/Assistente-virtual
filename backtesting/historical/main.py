"""CLI entry point for the historical backtester.

Usage
-----
    python -m backtesting.historical.main --period covid_2020
    python -m backtesting.historical.main --period gamestop_2021
    python -m backtesting.historical.main --period covid_2020 --no-report
    python -m backtesting.historical.main --list

This is a standalone research tool. It does NOT modify the daily pipeline,
GitHub Actions workflow, or any production code path.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Predefined backtest periods
# ---------------------------------------------------------------------------

PERIODS: dict[str, dict] = {
    "covid_2020": {
        "start":   "2020-02-01",
        "end":     "2020-06-01",
        "tickers": ["NVDA", "TSLA", "AAPL", "AMZN", "GOOGL", "GC=F", "SI=F", "CL=F", "HG=F"],
        "name":    "COVID Crash & Recovery",
    },
    "gamestop_2021": {
        "start":   "2021-01-01",
        "end":     "2021-02-28",
        "tickers": ["GME", "AMC", "BB", "PLTR", "GC=F", "SI=F", "TSLA", "NVDA"],
        "name":    "GameStop & Silver Squeeze",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_periods() -> None:
    print("\nAvailable backtest periods:\n")
    for key, cfg in PERIODS.items():
        print(f"  {key}")
        print(f"    name    : {cfg['name']}")
        print(f"    dates   : {cfg['start']} → {cfg['end']}")
        print(f"    tickers : {', '.join(cfg['tickers'])}")
        print()


def _load_existing(period_key: str) -> dict | None:
    """Return cached results JSON if present, so re-running skips API calls."""
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    path = os.path.join(results_dir, f"{period_key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Historical backtest for Artificial Price Radar signals.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--period", "-p",
        metavar="PERIOD_KEY",
        help="Predefined period to run (e.g. covid_2020, gamestop_2021).",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available predefined periods and exit.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip HTML report generation after the backtest.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-run even if a cached results file already exists.",
    )

    args = parser.parse_args(argv)

    if args.list:
        _list_periods()
        return 0

    if not args.period:
        parser.print_help()
        print(f"\nError: --period is required. Available: {', '.join(PERIODS)}", file=sys.stderr)
        return 1

    period_key = args.period
    if period_key not in PERIODS:
        print(
            f"Error: unknown period '{period_key}'. "
            f"Use --list to see available options.",
            file=sys.stderr,
        )
        return 1

    cfg = PERIODS[period_key]

    # --- Check cache ----------------------------------------------------------
    if not args.force:
        cached = _load_existing(period_key)
        if cached is not None:
            logger.info(
                "Found cached results for '%s' — skipping API calls. "
                "Use --force to re-run.",
                period_key,
            )
            results = cached
        else:
            results = None
    else:
        results = None

    # --- Run backtest ---------------------------------------------------------
    if results is None:
        from backtesting.historical.runner import run_historical_backtest

        logger.info("Starting backtest: %s (%s → %s)", cfg["name"], cfg["start"], cfg["end"])
        results = run_historical_backtest(
            start_date=cfg["start"],
            end_date=cfg["end"],
            tickers=cfg["tickers"],
            period_name=period_key,
        )

    # --- Print summary --------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Backtest complete — {cfg['name']}")
    print("=" * 60)
    print(f"  Period       : {results['start_date']} → {results['end_date']}")
    print(f"  Trading days : {results['trading_days_processed']}")
    print(f"  Signals      : {results['total_signals_generated']}")
    print(f"  Claude calls : {results['total_claude_calls']}")

    tu = results.get("token_usage", {})
    print(f"  Tokens in    : {tu.get('input_tokens', 0):,}")
    print(f"  Tokens out   : {tu.get('output_tokens', 0):,}")
    print(f"  Cache reads  : {tu.get('cache_read_input_tokens', 0):,}")

    hr = results.get("hit_rates", {})
    print("\n  Hit rates (contrarian_buy / reduce_exposure):")
    for w in (5, 10, 30):
        key = f"d{w}"
        window_data = hr.get(key, {})
        parts = []
        for rec, counts in sorted(window_data.items()):
            parts.append(f"{rec}: {counts['pct']:.1f}% ({counts['hits']}/{counts['total']})")
        if parts:
            print(f"    d+{w:2d}: {' | '.join(parts)}")
        else:
            print(f"    d+{w:2d}: no data")
    print()

    # --- HTML report ----------------------------------------------------------
    if not args.no_report:
        from backtesting.historical.report_builder import save_report

        report_path = save_report(results)
        print(f"  HTML report  : {report_path}")
    else:
        results_dir = os.path.join(os.path.dirname(__file__), "results")
        json_path   = os.path.join(results_dir, f"{period_key}.json")
        print(f"  JSON results : {json_path}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
