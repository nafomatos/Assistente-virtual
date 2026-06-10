"""Validate that the metal ETF proxies (GLD/SLV/COPX) have clean volume.

The yfinance front-month futures symbols (GC=F/SI=F/HG=F) stitch different
contracts' histories at roll, injecting fake volume — the artifact signature
is a 10x+ single-day volume multiple that is not a real market event
(GC=F hit 310x on 2026-05-18; see backtests/VOLUME_FIX*.md). ETFs have no
contract rolls, so their volume should never show that signature.

For each symbol this script pulls ~200 trading days and reports:
  - average / median daily volume (liquidity — the copper CPER-vs-COPX call)
  - zero-volume day count
  - the max single-day multiple vs a trailing 30d non-zero baseline
  - how many days exceeded 5x and 10x

PASS criteria for the new ETF symbols: no zero-volume days, max multiple in a
sane range (real news days are roughly < 5x; 10x+ is the artifact signature).
The legacy futures symbols are included for the before/after comparison.

Usage (requires network access to Yahoo Finance — run locally or in CI):
    python scripts/validate_etf_volume.py
Exit code 1 if any NEW symbol shows the artifact signature.
"""

from __future__ import annotations

import sys

import yfinance as yf

NEW_SYMBOLS    = ["GLD", "SLV", "COPX", "CPER"]   # CPER shown for the copper decision record
LEGACY_FUTURES = ["GC=F", "SI=F", "HG=F"]
ACTIVE_NEW     = {"GLD", "SLV", "COPX"}            # the symbols actually in the universe

MAX_SANE_MULTIPLE = 10.0    # the artifact signature threshold (matches analyze_volume)


def volume_stats(ticker: str, days: int = 200) -> dict | None:
    hist = yf.Ticker(ticker).history(period="1y", auto_adjust=False)
    if hist is None or hist.empty:
        return None
    vol = hist["Volume"].tail(days)
    nonzero = vol[vol > 0]
    values = vol.tolist()
    multiples: list[float] = []
    for i in range(30, len(values)):
        base = [x for x in values[i - 30:i] if x > 0]
        if base:
            multiples.append(values[i] / (sum(base) / len(base)))
    return {
        "ticker":      ticker,
        "days":        len(vol),
        "zero_days":   int((vol == 0).sum()),
        "avg_vol":     float(nonzero.mean()) if len(nonzero) else 0.0,
        "median_vol":  float(nonzero.median()) if len(nonzero) else 0.0,
        "max_multiple": max(multiples) if multiples else float("nan"),
        "n_over_5x":   sum(1 for m in multiples if m > 5),
        "n_over_10x":  sum(1 for m in multiples if m > 10),
    }


def main() -> int:
    print(f"{'TICKER':<7} {'AVG VOL':>14} {'MEDIAN VOL':>14} {'ZERO-DAYS':>9} "
          f"{'MAX MULT':>9} {'>5x':>4} {'>10x':>5}  VERDICT")
    print("-" * 80)
    failed = False
    for ticker in NEW_SYMBOLS + LEGACY_FUTURES:
        s = volume_stats(ticker)
        if s is None:
            print(f"{ticker:<7} NO DATA RETURNED")
            if ticker in ACTIVE_NEW:
                failed = True
            continue
        is_new = ticker in ACTIVE_NEW
        clean = s["zero_days"] == 0 and s["max_multiple"] < MAX_SANE_MULTIPLE
        verdict = ("CLEAN" if clean else "ARTIFACT SIGNATURE") if is_new else (
            "legacy (expected dirty)" if ticker in LEGACY_FUTURES else "info only")
        if is_new and not clean:
            failed = True
        print(f"{s['ticker']:<7} {s['avg_vol']:>14,.0f} {s['median_vol']:>14,.0f} "
              f"{s['zero_days']:>9} {s['max_multiple']:>8.1f}x {s['n_over_5x']:>4} "
              f"{s['n_over_10x']:>5}  {verdict}")

    print()
    if failed:
        print("FAIL: an active ETF symbol shows the artifact signature — "
              "Layer-1 containment will guard it, but investigate before relying "
              "on its volume metrics.")
        return 1
    print("PASS: all active ETF symbols show clean volume "
          f"(no zero-days, max multiple < {MAX_SANE_MULTIPLE:.0f}x).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
