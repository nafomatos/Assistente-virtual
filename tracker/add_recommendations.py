"""CLI entry point for adding Claude.ai recommendations to the position tracker.

Usage:
    python -m tracker.add_recommendations --json '<json_array>'
    python -m tracker.add_recommendations --file recommendation.json
    python -m tracker.add_recommendations --json '...' --date 2026-05-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from tracker.recommendation_parser import parse_and_add

logger = logging.getLogger(__name__)


def _capture_macro_context() -> dict:
    """Snapshot the macro regime at entry (Fear & Greed, VIX structure, Buffett).

    Best-effort: any collector that fails or is unavailable is simply omitted,
    so a position is still recorded even when a macro source is down.
    """
    macro: dict = {}
    try:
        from collectors.fear_greed import fetch_fear_greed
        fg = fetch_fear_greed()
        if fg and fg.get("score") is not None:
            macro["fear_greed"] = fg.get("score")
    except Exception as exc:  # pragma: no cover - network/collector failure
        logger.info("macro: fear & greed unavailable (%s)", exc)
    try:
        from collectors.vix_structure import fetch_vix_structure
        vix = fetch_vix_structure()
        if vix:
            macro["vix_structure"] = vix.get("structure") or vix.get("label")
    except Exception as exc:  # pragma: no cover
        logger.info("macro: vix structure unavailable (%s)", exc)
    try:
        from collectors.buffett_indicator import fetch_buffett_indicator
        buf = fetch_buffett_indicator()
        if buf and buf.get("ratio_pct") is not None:
            macro["buffett"] = buf.get("ratio_pct")
    except Exception as exc:  # pragma: no cover
        logger.info("macro: buffett indicator unavailable (%s)", exc)
    return macro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add Claude.ai recommendations to the position tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m tracker.add_recommendations --json '[{...}]'\n"
            "  python -m tracker.add_recommendations --file rec.json\n"
            "  python -m tracker.add_recommendations --file rec.json --date 2026-05-01\n"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json",  metavar="JSON", help="JSON array of recommendations")
    group.add_argument("--file",  metavar="FILE", help="Path to JSON file with recommendations")
    parser.add_argument("--date", default=None, help="Entry date YYYY-MM-DD (default: today)")

    args = parser.parse_args(argv)

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.json:
        try:
            recommendations = json.loads(args.json)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON — {exc}", file=sys.stderr)
            return 1
    else:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                recommendations = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error reading file: {exc}", file=sys.stderr)
            return 1

    if not isinstance(recommendations, list):
        recommendations = [recommendations]

    # Strategy v2: capture the macro snapshot at entry so each position records
    # the regime it was opened into (no more empty macro_context: {}).
    macro_context = _capture_macro_context()

    added = parse_and_add(recommendations, date=date, macro_context=macro_context)

    if not added:
        print("No new positions added (all were non-directional or already tracked).")
        return 0

    print(f"\nAdded {len(added)} position(s):")
    for pos in added:
        print(
            f"  {pos['ticker']:>6}  {pos['direction']:<5}  "
            f"conf={pos['confidence']}  "
            f"@ ${pos['entry_price']:.2f}  on {pos['entry_date']}  "
            f"(d30 target: {pos['d30_target']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
