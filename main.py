"""Main orchestrator.

Steps:
  1. Check US market calendar — if today isn't a normal trading day,
     log and exit cleanly (no email, no log write).
  2. Load active tickers from ticker_manager; discover and add trending tickers.
  3. Fetch shared macro context once: Fear & Greed, VIX term structure,
     Buffett Indicator.
  4. For each active ticker: market_data → volume / velocity / RSI / sentiment.
  5. Update ticker state (triggers, flat streaks, stale removals).
  6. Build the paste-ready .txt report (Red alerts first, then Amber).
  7. Copy to logs/YYYY-MM-DD.txt.
  8. Email it (unless --no-email).

Usage:
    python main.py                      # default active tickers
    python main.py NVDA TSLA AAPL       # explicit tickers (skips discovery)
    python main.py --no-email
    python main.py --date 2026-04-18    # test with a specific date (weekend ok)
    python main.py --force              # bypass market calendar check
    python main.py --debug              # all active tickers, detailed output,
                                        # no email, no log commit, no state writes
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
from analyzers.sentiment_aggregator import aggregate_sentiment
from analyzers.volume_analyzer import analyze_volume
from collectors.buffett_indicator import fetch_buffett_indicator
from collectors.buffett_indicator import format_summary as format_buffett
from collectors.fear_greed import fetch_fear_greed, format_summary as format_fg
from collectors.market_data import fetch_market_data
from collectors.stocktwits_sentiment import fetch_stocktwits_sentiment
from collectors.trending_tickers import fetch_trending_tickers
from collectors.youtube_sentiment import fetch_youtube_signals
from collectors.vix_structure import fetch_vix_structure
from collectors.vix_structure import format_summary as format_vix
from config import LOOKBACK_DAYS, TICKER_NAMES
from config.ticker_manager import (
    add_dynamic_ticker,
    get_active_tickers,
    get_state_summary,
    record_flat,
    record_signal,
    record_trigger,
    remove_stale_dynamic,
)
from delivery.email_sender import EmailConfigError, send_report
from output.document_builder import get_alert_tier, get_tier_reason, write_document

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("radar")

LOGS_DIR = "logs"
FULL_SESSION_MIN_HOURS = 6.0


def check_trading_day(date: dt.date) -> tuple[bool, str]:
    """Return (ok, reason). ok=False if today is a weekend, holiday, or early close."""
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
    """Run market + StockTwits for all tickers.

    YouTube is fetched separately in main() for RED/AMBER tickers only
    (saves daily API quota). Raw StockTwits result is stored under
    '_st_raw' on each result dict for use during the enrichment step.
    """
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

        try:
            stocktwits = fetch_stocktwits_sentiment(ticker)
        except Exception as e:
            logger.error(f"{ticker}: StockTwits fetch failed: {e}")
            stocktwits = None

        sentiment = aggregate_sentiment(ticker, stocktwits=stocktwits)

        signals = {
            "market":    market,
            "volume":    volume,
            "velocity":  velocity,
            "rsi":       rsi,
            "sentiment": sentiment,
        }
        results.append({"ticker": ticker, "signals": signals, "_st_raw": stocktwits})
    return results


def enrich_with_youtube(results: list[dict]) -> None:
    """Fetch YouTube signals for RED/AMBER tickers and re-aggregate sentiment.

    Mutates results in-place. Removes the '_st_raw' side-channel from all
    entries regardless of tier.
    """
    for r in results:
        st_raw = r.pop("_st_raw", None)
        tier   = get_alert_tier(r["signals"])
        if not tier:
            continue
        ticker = r["ticker"]
        name   = TICKER_NAMES.get(ticker, ticker)
        youtube = None
        try:
            youtube = fetch_youtube_signals(ticker, name)
        except Exception as e:
            logger.error(f"{ticker}: YouTube fetch failed: {e}")
        r["signals"]["sentiment"] = aggregate_sentiment(
            ticker, stocktwits=st_raw, youtube=youtube
        )
        if youtube:
            logger.info(
                f"{ticker}: YouTube — {youtube.get('video_count', 0)} videos, "
                f"heat={youtube.get('heat')}, tone={youtube.get('tone')}"
            )


def print_signal_summary(results: list[dict]) -> None:
    print("\n" + "=" * 88)
    print("SIGNAL SUMMARY (pre-filter)")
    print("=" * 88)
    for r in results:
        ticker = r["ticker"]
        name = TICKER_NAMES.get(ticker, ticker)
        m  = r["signals"]["market"]
        v  = r["signals"]["volume"]
        p  = r["signals"]["velocity"]
        rs = r["signals"]["rsi"]
        tier = get_alert_tier(r["signals"])
        status = f"[{tier.upper()}]" if tier else "filtered-out"
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


def print_debug_table(results: list[dict]) -> None:
    """Debug-mode per-ticker table: tier + trigger reason for every ticker."""
    print("\n" + "=" * 120)
    print("DEBUG — raw signals + alert tiers for all tickers")
    print("=" * 120)
    header = (
        f"{'TICKER':<7} {'VOL_RATIO':>10} {'Z_30D':>8} {'Z_200D':>8} "
        f"{'RSI':>6} {'RSI_CLASS':<18} TIER/REASON"
    )
    print(header)
    print("-" * 120)

    n_red = n_amber = n_skip = 0
    for r in results:
        ticker = r["ticker"]
        v  = r["signals"]["volume"]
        p  = r["signals"]["velocity"]
        rs = r["signals"]["rsi"]
        tier   = get_alert_tier(r["signals"])
        reason = get_tier_reason(r["signals"])

        if tier == "red":
            n_red += 1
        elif tier == "amber":
            n_amber += 1
        else:
            n_skip += 1

        rsi_str = f"{rs['rsi']:.1f}" if rs.get("rsi") is not None else "n/a"
        sent = r["signals"].get("sentiment") or {}
        bd   = sent.get("source_breakdown") or {}
        st_heat = sent.get("stocktwits_heat") or "n/a"
        st_tone_str = (
            bd.get("stocktwits", "n/a").split("tone=")[-1].split(",")[0]
            if "tone=" in bd.get("stocktwits", "")
            else "n/a"
        )
        yt_str = bd.get("youtube", "n/a")
        yt_heat = yt_str.split("heat=")[-1].split(",")[0] if "heat=" in yt_str else "n/a"
        print(
            f"{ticker:<7} {v['ratio']:>9.2f}x "
            f"{p['z_score_30d']:>+8.2f} {p['z_score_200d']:>+8.2f} "
            f"{rsi_str:>6} {rs['classification']:<18} "
            f"st={st_heat}/{st_tone_str:<8} yt={yt_heat:<8} {reason}"
        )

    print("-" * 120)
    print(
        f"Totals: {n_red} red, {n_amber} amber, {n_skip} filtered-out, "
        f"{len(results)} fetched"
    )


def print_ticker_management_section(
    new_dynamic: list[str],
    promoted: list[str],
    demoted: list[str],
    stale_removed: list[str],
    trending_stats: dict,
    is_debug: bool = False,
) -> None:
    """Print the TICKER MANAGEMENT summary block."""
    summary = get_state_summary()
    note = " (read-only — no state written)" if is_debug else ""
    print("\n" + "=" * 88)
    print(f"TICKER MANAGEMENT{note}")
    print("=" * 88)
    print(
        f"  Permanent: {summary['n_permanent']} | "
        f"Dynamic: {summary['n_dynamic']} | "
        f"Inactive: {summary['n_inactive']}"
    )

    def _fmt(lst: list[str], suffix: str = "") -> str:
        if not lst:
            return "none"
        return ", ".join(f"{t}{suffix}" for t in lst)

    new_str   = _fmt(new_dynamic, " (+1)")
    prom_str  = _fmt(promoted)
    dem_str   = _fmt(demoted)
    stale_str = _fmt(stale_removed)

    print(f"  New dynamic today:      {new_str}")
    print(f"  Promoted to permanent:  {prom_str}")
    print(f"  Demoted to inactive:    {dem_str}")
    if stale_removed:
        print(f"  Stale dynamic removed:  {stale_str}")
    if trending_stats:
        dup_filtered = trending_stats.get("filtered", 0)
        already_tracked = (
            trending_stats.get("added", 0)
            - len(new_dynamic)
        )
        print(
            f"  Trending sources: "
            f"ApeWisdom={trending_stats.get('apewisdom', 0)}, "
            f"Yahoo={trending_stats.get('yahoo', 0)}, "
            f"merged={trending_stats.get('merged', 0)}, "
            f"added={len(new_dynamic)} "
            f"(duplicates/filtered: {dup_filtered + already_tracked})"
        )


def archive_log(report_path: str, date: dt.date, logs_dir: str = LOGS_DIR) -> str:
    """Copy the generated report into logs/ for the GitHub Action to commit back."""
    os.makedirs(logs_dir, exist_ok=True)
    target = os.path.join(logs_dir, f"{date.isoformat()}.txt")
    shutil.copyfile(report_path, target)
    logger.info(f"archived log: {target}")
    return target


def _parse_args(argv: list[str]) -> tuple[list[str], bool, bool, bool, dt.date]:
    """Parse CLI arguments. Returns empty tickers list when none are specified
    (main() fills in active tickers via ticker_manager in that case)."""
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

    if debug:
        send_email = False
        force = True

    return tickers, send_email, force, debug, date


def main(argv: list[str]) -> int:
    tickers_cli, send_email, force, debug, date = _parse_args(argv)

    ok, reason = (True, "forced") if force else check_trading_day(date)
    logger.info(f"market check for {date.isoformat()}: {reason}")
    if not ok:
        print(f"Market closed on {date.isoformat()} ({reason}). Exiting cleanly.")
        return 0

    # ── Ticker management — discovery ────────────────────────────────────────
    # When explicit tickers are given on the CLI we skip discovery entirely
    # so test/ad-hoc runs have no side effects on the managed list.
    use_discovery = not tickers_cli
    new_dynamic:    list[str] = []
    trending_stats: dict      = {}

    if use_discovery:
        tickers = get_active_tickers()
        trending, trending_stats = fetch_trending_tickers()
        active_set = set(tickers)
        for t in trending:
            if not debug:
                if add_dynamic_ticker(t, date.isoformat()):
                    new_dynamic.append(t)
            else:
                # In debug mode, show what *would* be added without writing state.
                if t not in active_set:
                    new_dynamic.append(t)
        if new_dynamic and not debug:
            tickers = get_active_tickers()  # re-fetch after additions
        logger.info(
            f"Active tickers: {len(tickers)} total | "
            f"Trending: {len(trending)} candidates | "
            f"Newly added: {len(new_dynamic)}"
        )
    else:
        tickers = tickers_cli

    # ── Macro context ────────────────────────────────────────────────────────
    fear_greed = fetch_fear_greed()
    logger.info(format_fg(fear_greed))

    vix_structure = fetch_vix_structure()
    logger.info(format_vix(vix_structure))

    buffett = fetch_buffett_indicator()
    logger.info(format_buffett(buffett))

    # ── Pipeline ─────────────────────────────────────────────────────────────
    results = run_pipeline(tickers)
    enrich_with_youtube(results)   # YouTube fetched only for RED/AMBER tickers
    print_signal_summary(results)

    # ── Post-pipeline ticker state updates ───────────────────────────────────
    promoted:     list[str] = []
    demoted:      list[str] = []
    stale_removed: list[str] = []

    if use_discovery and not debug:
        for r in results:
            t    = r["ticker"]
            tier = get_alert_tier(r["signals"])
            if tier:
                if record_trigger(t, date.isoformat()):
                    promoted.append(t)
                record_signal(t, date.isoformat())
            else:
                if record_flat(t, date.isoformat()):
                    demoted.append(t)
        stale_removed = remove_stale_dynamic()
        logger.info(
            f"Active tickers: {get_state_summary()['n_permanent']} permanent + "
            f"{get_state_summary()['n_dynamic']} dynamic | "
            f"New today: {', '.join(new_dynamic) or 'none'} | "
            f"Promoted: {', '.join(promoted) or 'none'} | "
            f"Demoted: {', '.join(demoted) or 'none'}"
        )

    if debug:
        print_debug_table(results)
        print_ticker_management_section(
            new_dynamic, promoted, demoted, stale_removed, trending_stats,
            is_debug=True,
        )
        print("\n[debug mode] skipping report write, log archive, and email.")
        return 0

    if use_discovery and (new_dynamic or promoted or demoted or stale_removed):
        print_ticker_management_section(
            new_dynamic, promoted, demoted, stale_removed, trending_stats,
        )

    # ── Report ───────────────────────────────────────────────────────────────
    path, included, skipped = write_document(
        results,
        today=date,
        fear_greed=fear_greed,
        vix_structure=vix_structure,
        buffett=buffett,
    )
    print(f"\nReport written to: {path}")
    print(f"Included: {included or '(none)'}")
    print(f"Skipped : {skipped or '(none)'}")

    archive_log(path, date)

    if send_email:
        try:
            send_report(
                report_path=path,
                date=date,
                results=results,
                fear_greed=fear_greed,
                vix_structure=vix_structure,
                buffett=buffett,
            )
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
