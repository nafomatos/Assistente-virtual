#!/usr/bin/env python3
"""Cluster Boost Validation Runner.

Runs 4 historical periods × 2 cluster-boost states (on / off) = 8 total
backtests, then writes a markdown verdict report to backtests/.

Usage
-----
    # Full 8-run validation (skips periods that already have cached results)
    python scripts/run_cluster_validation.py

    # Force-rerun all 8 (ignores cache)
    python scripts/run_cluster_validation.py --force

    # Single-period run (both flag states for that period)
    python scripts/run_cluster_validation.py --period covid_2020

    # Smoke test: uses synthetic fixture, no API calls, confirms harness wiring
    python scripts/run_cluster_validation.py --smoke-test

Output
------
    backtests/cluster_boost_validation_YYYYMMDD.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

# Ensure the repo root is on sys.path so `backtesting.*` and `tracker.*` are importable
# regardless of whether the script is invoked as `python scripts/run_cluster_validation.py`
# (from project root) or `python run_cluster_validation.py` (from scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PERIODS = ["covid_2020", "gamestop_2021", "tech_bear_2022", "financial_crisis_2008"]

_PERIOD_LABELS = {
    "covid_2020":           "COVID Crash & Recovery (Feb–Jun 2020)",
    "gamestop_2021":        "GameStop & Silver Squeeze (Jan–Feb 2021)",
    "tech_bear_2022":       "2022 Tech Bear Market (Nov 2021–Dec 2022)",
    "financial_crisis_2008": "2008 Global Financial Crisis (Sep 2008–Apr 2009)",
}

_RESULTS_DIR  = os.path.join(os.path.dirname(__file__), "..", "backtesting", "historical", "results")
_REPORTS_DIR  = os.path.join(os.path.dirname(__file__), "..", "backtests")

# Verdict thresholds
_PASS_MIN_PERIODS   = 3   # at least this many periods must improve
_PASS_MIN_DELTA_PP  = 3.0  # by at least this many percentage points at d+30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_key(period: str, boost_on: bool) -> str:
    return f"{period}_boost_{'on' if boost_on else 'off'}"


def _results_path(period: str, boost_on: bool) -> str:
    return os.path.join(_RESULTS_DIR, f"{_result_key(period, boost_on)}.json")


def _load_results(period: str, boost_on: bool) -> dict | None:
    path = _results_path(period, boost_on)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _run_backtest(period: str, boost_on: bool) -> dict:
    """Import and call the backtester directly (no subprocess)."""
    from backtesting.historical.main import PERIODS
    from backtesting.historical.runner import run_historical_backtest

    cfg = PERIODS[period]
    rk  = _result_key(period, boost_on)
    return run_historical_backtest(
        start_date=cfg["start"],
        end_date=cfg["end"],
        tickers=cfg["tickers"],
        period_name=period,
        result_key=rk,
        cluster_boost=boost_on,
    )


def _combined_hit_rate(window_data: dict) -> tuple[float | None, int]:
    """Combine contrarian_buy + reduce_exposure hits/totals at a given window.

    Returns (pct, total_evaluated).
    """
    hits = total = 0
    for rec in ("contrarian_buy", "reduce_exposure"):
        entry = window_data.get(rec, {})
        hits  += entry.get("hits", 0)
        total += entry.get("total", 0)
    if total == 0:
        return None, 0
    return round(100 * hits / total, 1), total


def _confidence_filtered_hit_rate(
    signals: list[dict], min_conf: int, window: str = "d30"
) -> tuple[float | None, int]:
    """Hit rate restricted to signals with confidence >= min_conf."""
    hits = total = 0
    for sig in signals:
        if sig.get("recommendation") not in ("contrarian_buy", "reduce_exposure"):
            continue
        if (sig.get("confidence") or 0) < min_conf:
            continue
        outcome = sig.get("outcomes", {}).get(window, {})
        if outcome.get("status") != "evaluated":
            continue
        hit = outcome.get("hit")
        if hit is None:
            continue
        total += 1
        if hit:
            hits += 1
    if total == 0:
        return None, 0
    return round(100 * hits / total, 1), total


def _rec_hit_rates(hit_rates: dict, window: str = "d30") -> dict[str, tuple[float, int]]:
    """Per-recommendation hit rate at a given window."""
    result = {}
    for rec, entry in hit_rates.get(window, {}).items():
        if rec in ("contrarian_buy", "reduce_exposure") and entry.get("total", 0) > 0:
            result[rec] = (entry["pct"], entry["total"])
    return result


def _sector_attribution(signals: list[dict], window: str = "d30") -> list[dict]:
    """Per-sector hit rate for signals that received a cluster boost."""
    by_sector: dict[str, dict] = {}
    for sig in signals:
        if not sig.get("cluster_boost_applied"):
            continue
        if sig.get("recommendation") not in ("contrarian_buy", "reduce_exposure"):
            continue
        sector = (sig.get("cluster_boost_info") or {}).get("sector", "unknown")
        if sector not in by_sector:
            by_sector[sector] = {"hits": 0, "total": 0}
        outcome = sig.get("outcomes", {}).get(window, {})
        if outcome.get("status") != "evaluated" or outcome.get("hit") is None:
            continue
        by_sector[sector]["total"] += 1
        if outcome["hit"]:
            by_sector[sector]["hits"] += 1

    rows = []
    for sector, counts in sorted(by_sector.items()):
        t = counts["total"]
        h = counts["hits"]
        pct = round(100 * h / t, 1) if t else None
        rows.append({"sector": sector, "hits": h, "total": t, "pct": pct})
    return rows


def _extract_metrics(results: dict) -> dict:
    """Pull all validation metrics out of one results dict."""
    signals   = results.get("signals", [])
    hit_rates = results.get("hit_rates", {})
    boost_sum = results.get("cluster_boost_summary", {})

    d10_pct, d10_n = _combined_hit_rate(hit_rates.get("d10", {}))
    d30_pct, d30_n = _combined_hit_rate(hit_rates.get("d30", {}))

    conf7_pct, conf7_n = _confidence_filtered_hit_rate(signals, min_conf=7)
    conf8_pct, conf8_n = _confidence_filtered_hit_rate(signals, min_conf=8)

    return {
        "total_signals":        results.get("total_signals_generated", 0),
        "boosted_count":        boost_sum.get("total_boosted", 0),
        "boost_by_sector":      boost_sum.get("by_sector", {}),
        "d10_pct":              d10_pct,
        "d10_n":                d10_n,
        "d30_pct":              d30_pct,
        "d30_n":                d30_n,
        "d30_conf7_pct":        conf7_pct,
        "d30_conf7_n":          conf7_n,
        "d30_conf8_pct":        conf8_pct,
        "d30_conf8_n":          conf8_n,
        "d30_by_rec":           _rec_hit_rates(hit_rates),
        "sector_attribution":   _sector_attribution(signals),
        "cap_reached":          results.get("cap_reached", False),
    }


# ---------------------------------------------------------------------------
# Smoke-test fixture
# ---------------------------------------------------------------------------

def _make_signal(
    ticker: str,
    date_str: str,
    rec: str,
    conf: int,
    hit_d10: bool,
    hit_d30: bool,
    boosted: bool = False,
    sector: str = "semis",
) -> dict:
    sig: dict = {
        "ticker":         ticker,
        "date":           date_str,
        "tier":           "red",
        "classification": "bubble_forming" if rec == "reduce_exposure" else "irrational_panic",
        "recommendation": rec,
        "confidence":     conf,
        "confidence_raw": conf + (2 if not boosted else 3),
        "reasoning":      "Synthetic smoke-test signal.",
        "price_at_signal": 100.0,
        "outcomes": {
            "d5":  {"status": "evaluated", "price": 103.0, "change_pct": 3.0,  "hit": True},
            "d10": {"status": "evaluated", "price": 110.0 if hit_d10 else 91.0,
                    "change_pct": 10.0 if hit_d10 else -9.0, "hit": hit_d10},
            "d30": {"status": "evaluated", "price": 115.0 if hit_d30 else 87.0,
                    "change_pct": 15.0 if hit_d30 else -13.0, "hit": hit_d30},
        },
    }
    if boosted:
        sig["cluster_boost_applied"] = True
        sig["cluster_boost_info"] = {
            "sector":              sector,
            "direction_group":     "bearish_overheating",
            "count":               4,
            "original_confidence": conf - 1,
            "boost_amount":        1,
        }
    return sig


def _build_smoke_fixture() -> dict[str, dict[bool, dict]]:
    """Synthetic results for all 4 periods × both flag states.

    Numbers are plausible-looking but entirely made up — for harness wiring
    verification only, not for drawing any real conclusions.
    """
    # Each period is a 2-tuple (off_results, on_results)
    fixture: dict[str, dict[bool, dict]] = {}

    raw_data = {
        # period: (off_d30_pct, on_d30_pct, n_signals, n_boosted)
        "covid_2020":            (57.1, 61.3, 28, 6),
        "gamestop_2021":         (60.0, 62.5, 16, 4),
        "tech_bear_2022":        (55.6, 59.3, 27, 5),
        "financial_crisis_2008": (53.8, 57.7, 26, 5),
    }

    from backtesting.historical.main import PERIODS

    for period, (off_pct, on_pct, n_sig, n_boost) in raw_data.items():
        cfg   = PERIODS[period]
        start = dt.date.fromisoformat(cfg["start"])

        for boost_on in (False, True):
            n = n_sig
            signals = []
            # Directional signals — mix of hits and misses to land near target pct
            hit_count = round(n * (on_pct if boost_on else off_pct) / 100)
            for i in range(n):
                hit = i < hit_count
                date_str = (start + dt.timedelta(days=i * 3)).isoformat()
                ticker   = ["NVDA", "TSLA", "AAPL", "AMZN"][i % 4]
                rec      = "reduce_exposure" if i % 3 != 0 else "contrarian_buy"
                conf     = 7 if i % 2 == 0 else 6
                boosted  = boost_on and i < n_boost
                signals.append(_make_signal(ticker, date_str, rec, conf, hit, hit, boosted))

            # Build a minimal hit_rates dict
            cb_hits   = sum(1 for s in signals if s["recommendation"] == "contrarian_buy"
                            and s["outcomes"]["d30"]["hit"])
            cb_total  = sum(1 for s in signals if s["recommendation"] == "contrarian_buy")
            re_hits   = sum(1 for s in signals if s["recommendation"] == "reduce_exposure"
                            and s["outcomes"]["d30"]["hit"])
            re_total  = sum(1 for s in signals if s["recommendation"] == "reduce_exposure")

            d10_cb_hits  = sum(1 for s in signals if s["recommendation"] == "contrarian_buy"
                               and s["outcomes"]["d10"]["hit"])
            d10_re_hits  = sum(1 for s in signals if s["recommendation"] == "reduce_exposure"
                               and s["outcomes"]["d10"]["hit"])

            hit_rates = {
                "d5":  {},
                "d10": {
                    "contrarian_buy":  {"hits": d10_cb_hits, "total": cb_total,
                                        "pct": round(100*d10_cb_hits/cb_total, 1) if cb_total else 0},
                    "reduce_exposure": {"hits": d10_re_hits, "total": re_total,
                                        "pct": round(100*d10_re_hits/re_total, 1) if re_total else 0},
                },
                "d30": {
                    "contrarian_buy":  {"hits": cb_hits,  "total": cb_total,
                                        "pct": round(100*cb_hits/cb_total, 1)  if cb_total else 0},
                    "reduce_exposure": {"hits": re_hits,  "total": re_total,
                                        "pct": round(100*re_hits/re_total, 1)  if re_total else 0},
                },
            }

            boosted_sigs = [s for s in signals if s.get("cluster_boost_applied")]
            by_sector    = {}
            for s in boosted_sigs:
                sec = (s.get("cluster_boost_info") or {}).get("sector", "unknown")
                by_sector[sec] = by_sector.get(sec, 0) + 1

            fixture.setdefault(period, {})[boost_on] = {
                "period_name":             period,
                "result_key":              _result_key(period, boost_on),
                "start_date":              cfg["start"],
                "end_date":                cfg["end"],
                "tickers":                 cfg["tickers"],
                "trading_days_processed":  n * 3,
                "total_signals_generated": n,
                "total_claude_calls":      n,
                "cap_reached":             False,
                "cluster_boost_enabled":   boost_on,
                "cluster_boost_summary":   {"total_boosted": n_boost if boost_on else 0,
                                            "by_sector": by_sector},
                "token_usage":             {"input_tokens": n*1200, "output_tokens": n*80,
                                            "cache_read_input_tokens": n*1000,
                                            "cache_creation_input_tokens": 1200},
                "hit_rates":               hit_rates,
                "vix_timeline":            {"min": 15.0, "max": 82.7, "avg": 35.0,
                                            "days_above_35": 12, "days_above_50": 5},
                "signals":                 signals,
            }

    return fixture


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _fmt_pct(pct: float | None, n: int = 0) -> str:
    if pct is None:
        return "—"
    n_str = f" ({n})" if n else ""
    return f"{pct:.1f}%{n_str}"


def _delta_str(off: float | None, on: float | None) -> str:
    if off is None or on is None:
        return "—"
    delta = on - off
    sign  = "+" if delta >= 0 else ""
    emoji = " ✓" if delta >= _PASS_MIN_DELTA_PP else (" ✗" if delta < 0 else "")
    return f"{sign}{delta:.1f}pp{emoji}"


def generate_report(
    all_metrics: dict[str, dict[bool, dict]],
    smoke_test: bool = False,
) -> str:
    today     = dt.date.today().isoformat()
    watermark = " _(smoke-test fixture — not real backtest data)_" if smoke_test else ""

    lines: list[str] = []
    lines.append(f"# Cluster Boost Validation Report — {today}{watermark}")
    lines.append("")
    lines.append(
        f"**Verdict threshold:** ≥{_PASS_MIN_PERIODS} of {len(_PERIODS)} periods improved "
        f"by ≥{_PASS_MIN_DELTA_PP:.0f}pp at d+30 (combined contrarian_buy + reduce_exposure)."
    )
    lines.append("")

    # ── Section 1: Summary table ──────────────────────────────────────────────
    lines.append("## 1. Summary Table — d+30 hit rate")
    lines.append("")
    lines.append("| Period | Boost OFF | Boost ON | Delta | Pass? |")
    lines.append("|--------|-----------|----------|-------|-------|")

    period_pass: dict[str, bool] = {}

    for period in _PERIODS:
        pair    = all_metrics.get(period, {})
        off_m   = pair.get(False, {})
        on_m    = pair.get(True, {})
        off_pct = off_m.get("d30_pct")
        on_pct  = on_m.get("d30_pct")

        passed  = (
            off_pct is not None
            and on_pct is not None
            and (on_pct - off_pct) >= _PASS_MIN_DELTA_PP
        )
        period_pass[period] = passed

        label   = _PERIOD_LABELS.get(period, period)
        off_str = _fmt_pct(off_pct, off_m.get("d30_n", 0))
        on_str  = _fmt_pct(on_pct,  on_m.get("d30_n",  0))
        delta   = _delta_str(off_pct, on_pct)
        p_str   = "✓ PASS" if passed else "✗ FAIL"
        lines.append(f"| {label} | {off_str} | {on_str} | {delta} | {p_str} |")

    lines.append("")

    # ── Section 2: Per-period detail ──────────────────────────────────────────
    lines.append("## 2. Per-Period Detail")
    lines.append("")

    for period in _PERIODS:
        pair  = all_metrics.get(period, {})
        label = _PERIOD_LABELS.get(period, period)
        lines.append(f"### {label}")
        lines.append("")

        for boost_on in (False, True):
            tag = "**Boost ON**" if boost_on else "**Boost OFF**"
            m   = pair.get(boost_on, {})
            if not m:
                lines.append(f"{tag}: _no results_")
                lines.append("")
                continue

            lines.append(f"{tag}")
            lines.append(f"- Total signals: {m.get('total_signals', 0)}")
            lines.append(f"- Boosted signals: {m.get('boosted_count', 0)}")
            lines.append(f"- Cap reached: {m.get('cap_reached', False)}")
            lines.append(
                f"- d+10 hit rate: {_fmt_pct(m.get('d10_pct'), m.get('d10_n', 0))}"
            )
            lines.append(
                f"- d+30 hit rate: {_fmt_pct(m.get('d30_pct'), m.get('d30_n', 0))}"
            )
            lines.append(
                f"- d+30 (conf ≥ 7): {_fmt_pct(m.get('d30_conf7_pct'), m.get('d30_conf7_n', 0))}"
            )
            lines.append(
                f"- d+30 (conf ≥ 8): {_fmt_pct(m.get('d30_conf8_pct'), m.get('d30_conf8_n', 0))}"
            )

            by_rec = m.get("d30_by_rec", {})
            if by_rec:
                lines.append("- d+30 by recommendation:")
                for rec, (pct, n) in sorted(by_rec.items()):
                    lines.append(f"  - `{rec}`: {pct:.1f}% ({n})")

            lines.append("")

    # ── Section 3: Sector attribution ─────────────────────────────────────────
    lines.append("## 3. Sector Attribution (Boost ON runs only)")
    lines.append("")
    lines.append("Sector attribution tracks which sectors triggered the most boosts")
    lines.append("and whether boosted signals in those sectors were directionally correct at d+30.")
    lines.append("")
    lines.append("| Period | Sector | Boosted signals | d+30 hit rate |")
    lines.append("|--------|--------|-----------------|---------------|")

    for period in _PERIODS:
        label = _PERIOD_LABELS.get(period, period)
        on_m  = all_metrics.get(period, {}).get(True, {})
        rows  = on_m.get("sector_attribution", [])
        if not rows:
            lines.append(f"| {label} | — | — | — |")
            continue
        for row in rows:
            pct_str = f"{row['pct']:.1f}%" if row["pct"] is not None else "—"
            lines.append(
                f"| {label} | `{row['sector']}` | {row['total']} | {pct_str} |"
            )

    lines.append("")

    # ── Section 4: Verdict ────────────────────────────────────────────────────
    lines.append("## 4. Verdict")
    lines.append("")
    pass_count = sum(1 for v in period_pass.values() if v)
    overall    = pass_count >= _PASS_MIN_PERIODS

    lines.append(f"**{'PASS ✓' if overall else 'FAIL ✗'}** — "
                 f"{pass_count}/{len(_PERIODS)} periods improved by ≥{_PASS_MIN_DELTA_PP:.0f}pp at d+30.")
    lines.append("")
    lines.append("| Period | Result |")
    lines.append("|--------|--------|")
    for period in _PERIODS:
        label  = _PERIOD_LABELS.get(period, period)
        result = "✓ PASS" if period_pass.get(period) else "✗ FAIL"
        lines.append(f"| {label} | {result} |")

    lines.append("")

    # ── Section 5: Recommended action ────────────────────────────────────────
    lines.append("## 5. Recommended Action")
    lines.append("")
    if overall:
        lines.append(
            "**FLIP FLAG** — set `CLUSTER_BOOST_ENABLED=true` in the GitHub Actions "
            "environment or `.env` to activate the cluster confidence boost in production."
        )
    else:
        # Build a hypothesis based on which periods failed
        failed = [_PERIOD_LABELS.get(p, p) for p, v in period_pass.items() if not v]
        hyp    = (
            "the boost may not generalise to periods dominated by macro-driven moves "
            "rather than sector-specific clustering"
            if len(failed) >= 2
            else f"the boost underperformed in: {'; '.join(failed)}"
        )
        lines.append(
            f"**DO NOT FLIP** — investigate hypothesis: _{hyp}_. "
            "Consider narrowing the cluster threshold, adjusting the window, "
            "or reviewing sector mapping before re-running validation."
        )

    lines.append("")
    lines.append("---")
    lines.append(f"_Generated by `scripts/run_cluster_validation.py` on {today}_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cluster boost validation — 4 periods × on/off = 8 backtests.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--period", "-p",
        metavar="PERIOD_KEY",
        help="Run only this period (both flag states). Default: all 4 periods.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-run even if a cached results file exists.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Use a synthetic fixture instead of running real backtests. "
            "No API calls made. Confirms the harness wires up end-to-end."
        ),
    )
    args = parser.parse_args(argv)

    periods = [args.period] if args.period else _PERIODS

    # -- Validate period key --------------------------------------------------
    from backtesting.historical.main import PERIODS as _DEFINED_PERIODS
    for p in periods:
        if p not in _DEFINED_PERIODS:
            print(f"Error: unknown period '{p}'. "
                  f"Available: {', '.join(_DEFINED_PERIODS)}", file=sys.stderr)
            return 1

    # -- Gather results -------------------------------------------------------
    all_results:  dict[str, dict[bool, dict]] = {}  # period → {boost_on → raw results}
    all_metrics:  dict[str, dict[bool, dict]] = {}  # period → {boost_on → extracted metrics}
    smoke_test = args.smoke_test

    if smoke_test:
        print("Smoke test mode: using synthetic fixture (no API calls).")
        fixture = _build_smoke_fixture()
        for period in periods:
            all_results[period] = fixture.get(period, {})
    else:
        os.makedirs(_RESULTS_DIR, exist_ok=True)
        for period in periods:
            all_results[period] = {}
            for boost_on in (False, True):
                tag = "on" if boost_on else "off"
                if not args.force:
                    cached = _load_results(period, boost_on)
                    if cached is not None:
                        print(f"[cache] {period} boost={tag} — loaded from disk")
                        all_results[period][boost_on] = cached
                        continue

                print(f"[run]   {period} boost={tag} — starting backtest …")
                try:
                    all_results[period][boost_on] = _run_backtest(period, boost_on)
                    print(f"[done]  {period} boost={tag}")
                except Exception as exc:
                    print(f"[ERROR] {period} boost={tag}: {exc}", file=sys.stderr)
                    all_results[period][boost_on] = {}

    # -- Extract metrics ------------------------------------------------------
    for period in periods:
        all_metrics[period] = {}
        for boost_on in (False, True):
            results = all_results[period].get(boost_on)
            if results:
                all_metrics[period][boost_on] = _extract_metrics(results)
            else:
                all_metrics[period][boost_on] = {}

    # -- Generate report ------------------------------------------------------
    report_md  = generate_report(all_metrics, smoke_test=smoke_test)
    today_str  = dt.date.today().strftime("%Y%m%d")
    report_name = f"cluster_boost_validation_{today_str}.md"
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    report_path = os.path.join(_REPORTS_DIR, report_name)

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_md)

    print(f"\nReport written → {report_path}")
    print()
    print(report_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
