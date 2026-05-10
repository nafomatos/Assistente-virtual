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
import json
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
from claude_advisor.weekly_advisor import generate_weekly_narrative
from delivery.email_sender import EmailConfigError, send_report, send_weekly_report
from output.document_builder import get_alert_tier, get_tier_reason, write_document
from output.weekly_summary import generate_weekly_summary
from tracker.position_tracker import (
    close_expired_positions,
    get_aggregate_stats,
    update_open_positions,
)

load_dotenv()

CLUSTER_BOOST_ENABLED = os.getenv("CLUSTER_BOOST_ENABLED", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("radar")

LOGS_DIR = "logs"
FULL_SESSION_MIN_HOURS = 6.0


def should_send_weekly(date: dt.date, force: bool) -> bool:
    """Return True when the weekly summary email should be sent.

    Rules:
    - Always on Friday (weekday 4).
    - On Saturday/Sunday only when force=True (manual workflow_dispatch).
    - Never on Mon-Thu even with force (not meaningful mid-week).
    """
    if date.weekday() == 4:
        return True
    if force and date.weekday() in (5, 6):
        return True
    return False


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
        if volume.get("data_quality") == "suspicious_volume":
            logger.warning(
                "[DATA QUALITY] %s volume multiple %.1fx exceeds threshold"
                " — consider review",
                ticker, volume["ratio"],
            )
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
    alert_tickers = [r["ticker"] for r in results if get_alert_tier(r["signals"])]
    if not alert_tickers:
        logger.info("YouTube: no RED/AMBER tickers — skipping all YouTube fetches")
        for r in results:
            r.pop("_st_raw", None)
        return

    logger.info(f"YouTube: fetching for {len(alert_tickers)} RED/AMBER ticker(s): {', '.join(alert_tickers)}")

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
        vc = (youtube or {}).get("video_count", 0)
        logger.info(
            f"{ticker}: YouTube — {vc} videos, "
            f"heat={( youtube or {}).get('heat', 'n/a')}, "
            f"tone={(youtube or {}).get('tone', 'n/a')}"
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

    ok, reason = check_trading_day(date)
    logger.info(f"market check for {date.isoformat()}: {reason}")

    is_weekend = date.weekday() in (5, 6)
    # Force bypasses the market calendar only for non-weekend days (holidays,
    # early closes, ad-hoc testing). On weekends --force triggers weekly-only mode.
    run_full_pipeline = ok or (force and not is_weekend)

    if not run_full_pipeline:
        if force and is_weekend and should_send_weekly(date, force) and send_email and not debug:
            # Weekend manual dispatch: send weekly summary without the daily pipeline.
            logger.info("Weekend + --force: running weekly-only report (no daily pipeline)")
            print("Market closed (weekend). Running weekly-only report.")
            weekly_summary = generate_weekly_summary(LOGS_DIR, date)
            if not weekly_summary:
                logger.warning("weekly summary: no log data found — skipping")
                print("Weekly summary: no log data found.")
            else:
                days = weekly_summary.get("days_analyzed", 0)
                if days < 3:
                    logger.info(
                        f"weekly summary: only {days} of 5 trading days found — "
                        "sending with available data"
                    )
                narrative = generate_weekly_narrative(weekly_summary, {})
                if not narrative:
                    logger.info("weekly summary: sending without narrative")
                try:
                    send_weekly_report(summary=weekly_summary, narrative=narrative, date=date)
                    logger.info("weekly summary sent")
                    print("Weekly summary sent.")
                except EmailConfigError as e:
                    logger.warning(f"weekly email skipped: {e}")
                    print(f"Weekly email skipped: {e}")
                except Exception as e:
                    logger.exception("weekly email send failed")
                    print(f"Weekly email send failed: {e}", file=sys.stderr)
        else:
            print(f"Market closed on {date.isoformat()} ({reason}). Exiting cleanly.")
        return 0

    if force and not ok:
        logger.info(f"Bypassing market calendar for {date.isoformat()}: {reason}")

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

    # ── Position tracker ─────────────────────────────────────────────────────
    try:
        close_expired_positions(date)
        open_positions = update_open_positions(date)
        closed_stats   = get_aggregate_stats()
        logger.info(
            f"position tracker: {len(open_positions)} open, "
            f"{closed_stats.get('total', 0)} closed total"
        )
    except Exception as e:
        logger.warning(f"position tracker update failed (continuing): {e}")
        open_positions = []
        closed_stats   = {}

    # ── Report ───────────────────────────────────────────────────────────────
    path, included, skipped = write_document(
        results,
        today=date,
        fear_greed=fear_greed,
        vix_structure=vix_structure,
        buffett=buffett,
        open_positions=open_positions,
        closed_stats=closed_stats,
    )
    print(f"\nReport written to: {path}")
    print(f"Included: {included or '(none)'}")
    print(f"Skipped : {skipped or '(none)'}")

    archive_log(path, date)

    # ── Cluster Signal Booster ────────────────────────────────────────────────
    # Reads historical logs/signals_YYYYMMDD.json files (written by this block
    # on previous runs) and boosts confidence when 3+ tickers from the same
    # sector are signalling in the same direction within the rolling window.
    # Post-classification, pure Python — never touches the Claude prompt.
    active_clusters: list[dict] = []
    if CLUSTER_BOOST_ENABLED:
        from tracker.cluster_detector import detect_clusters
        from tracker.sectors import get_direction_group, get_sector

        active_clusters = detect_clusters(days_window=5)

        # Load today's classified signals (written by the Claude Haiku step)
        signals_path = os.path.join(LOGS_DIR, f"signals_{date.isoformat()}.json")
        classified_signals: list[dict] = []
        if os.path.exists(signals_path):
            try:
                with open(signals_path, "r", encoding="utf-8") as fh:
                    classified_signals = json.load(fh).get("signals", [])
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("cluster boost: could not load %s (%s)", signals_path, exc)

        for signal in classified_signals:
            sector = get_sector(signal["ticker"])
            direction = get_direction_group(
                signal.get("classification", ""),
                signal.get("recommendation", ""),
            )
            for cluster in active_clusters:
                if cluster["sector"] == sector and cluster["direction_group"] == direction:
                    original = signal["confidence"]
                    boosted  = min(original + cluster["boost"], 10)
                    signal["cluster_boost"] = {
                        "sector": sector,
                        "direction_group": direction,
                        "count": cluster["count"],
                        "original_confidence": original,
                        "boost_amount": cluster["boost"],
                    }
                    signal["confidence"] = boosted
                    logger.info(
                        "[CLUSTER BOOST] %s %s %s: %d -> %d (+%d, %d tickers)",
                        signal["ticker"], sector, direction,
                        original, boosted, cluster["boost"], cluster["count"],
                    )
                    break

        # Merge cluster_boost info into results for the email template
        classified_by_ticker = {s["ticker"]: s for s in classified_signals}
        for r in results:
            cb = classified_by_ticker.get(r["ticker"], {}).get("cluster_boost")
            if cb:
                r["cluster_boost"] = cb

        # Persist detected clusters for historical analysis / backtesting
        if active_clusters:
            clusters_path = os.path.join(LOGS_DIR, f"clusters_{date.isoformat()}.json")
            try:
                os.makedirs(LOGS_DIR, exist_ok=True)
                with open(clusters_path, "w", encoding="utf-8") as fh:
                    json.dump({"date": date.isoformat(), "clusters": active_clusters}, fh, indent=2)
                logger.info("clusters saved to %s", clusters_path)
            except OSError as exc:
                logger.warning("cluster boost: could not save clusters (%s)", exc)

    if send_email:
        try:
            send_report(
                report_path=path,
                date=date,
                results=results,
                fear_greed=fear_greed,
                vix_structure=vix_structure,
                buffett=buffett,
                open_positions=open_positions,
                closed_stats=closed_stats,
                active_clusters=active_clusters,
            )
            print("Email sent.")
        except EmailConfigError as e:
            logger.warning(f"email skipped: {e}")
            print(f"Email skipped: {e}")
        except Exception as e:
            logger.exception("email send failed")
            print(f"Email send failed: {e}", file=sys.stderr)
            return 1

    # ── Weekly summary (Fridays, or forced on weekends) ───────────────────
    if send_email and should_send_weekly(date, force):
        weekly_summary = generate_weekly_summary(LOGS_DIR, date)
        if not weekly_summary:
            logger.warning("weekly summary: no log data found — skipping weekly email")
        else:
            days = weekly_summary.get("days_analyzed", 0)
            if days < 3:
                logger.info(
                    f"weekly summary: only {days} of 5 trading days found — "
                    "sending with available data"
                )
            macro_context = {
                "fear_greed": fear_greed,
                "buffett": buffett,
            }
            narrative = generate_weekly_narrative(weekly_summary, macro_context)
            if not narrative:
                logger.info("weekly summary: sending without narrative (generation failed or skipped)")
            try:
                send_weekly_report(
                    summary=weekly_summary,
                    narrative=narrative,
                    date=date,
                )
                logger.info("weekly summary sent")
                print("Weekly summary sent.")
            except EmailConfigError as e:
                logger.warning(f"weekly email skipped: {e}")
                print(f"Weekly email skipped: {e}")
            except Exception as e:
                logger.exception("weekly email send failed")
                print(f"Weekly email send failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
