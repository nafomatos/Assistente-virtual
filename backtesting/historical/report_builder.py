"""Generate an HTML backtest report from a results dict produced by runner.py.

Usage
-----
    from backtesting.historical.report_builder import save_report
    path = save_report(results)          # saves to backtesting/historical/results/
    path = save_report(results, "/tmp/report.html")
"""

from __future__ import annotations

import os

EVAL_WINDOWS = [5, 10, 30]

_STYLE = """
<style>
  body  { font-family: Arial, sans-serif; font-size: 14px; color: #222; background: #f5f5f5; margin: 0; padding: 20px; }
  .card { background: #fff; border-radius: 6px; padding: 20px 24px; margin-bottom: 20px;
          box-shadow: 0 1px 3px rgba(0,0,0,.12); }
  h1   { font-size: 22px; margin: 0 0 4px; color: #111; }
  h2   { font-size: 16px; margin: 16px 0 8px; color: #333; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 16px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th   { background: #f0f0f0; text-align: left; padding: 6px 10px; border: 1px solid #ddd; }
  td   { padding: 5px 10px; border: 1px solid #ddd; vertical-align: top; }
  tr:nth-child(even) td { background: #fafafa; }
  .hit  { color: #2a7a2a; font-weight: bold; }
  .miss { color: #b33; font-weight: bold; }
  .na   { color: #999; }
  .tag-red   { background:#fee; color:#b00; padding:1px 6px; border-radius:3px; font-size:12px; }
  .tag-amber { background:#fff3cd; color:#856404; padding:1px 6px; border-radius:3px; font-size:12px; }
  .note { background:#fffbe6; border-left:4px solid #f0ad4e; padding:8px 12px; font-size:13px;
          border-radius:0 4px 4px 0; margin-top:10px; }
  .stat-grid { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:8px; }
  .stat { background:#f8f8f8; border:1px solid #ddd; border-radius:4px;
          padding:10px 16px; min-width:140px; text-align:center; }
  .stat .n  { font-size:26px; font-weight:bold; color:#333; }
  .stat .lbl{ font-size:11px; color:#666; margin-top:2px; }
</style>
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct_cell(pct: float | None) -> str:
    if pct is None:
        return '<td class="na">—</td>'
    color = "#2a7a2a" if pct >= 55 else ("#b33" if pct < 45 else "#777")
    return f'<td style="color:{color};font-weight:bold">{pct:.1f}%</td>'


def _hit_label(hit: bool | None) -> str:
    if hit is True:
        return '<span class="hit">✓ hit</span>'
    if hit is False:
        return '<span class="miss">✗ miss</span>'
    return '<span class="na">—</span>'


def _change_str(change_pct: float | None) -> str:
    if change_pct is None:
        return "—"
    color = "#2a7a2a" if change_pct > 0 else ("#b33" if change_pct < 0 else "#777")
    sign  = "+" if change_pct > 0 else ""
    return f'<span style="color:{color}">{sign}{change_pct:.1f}%</span>'


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _stat_grid(results: dict) -> str:
    td  = results["trading_days_processed"]
    sig = results["total_signals_generated"]
    cc  = results["total_claude_calls"]
    stats = [
        (td,  "trading days"),
        (sig, "signals generated"),
        (cc,  "Claude calls made"),
    ]
    items = "".join(
        f'<div class="stat"><div class="n">{n}</div><div class="lbl">{lbl}</div></div>'
        for n, lbl in stats
    )
    return f'<div class="stat-grid">{items}</div>'


def _hit_rate_table(hit_rates: dict) -> str:
    recoms = sorted(
        {r for w in EVAL_WINDOWS for r in hit_rates.get(f"d{w}", {})},
    )
    if not recoms:
        return "<p>No directional recommendations to evaluate.</p>"

    header = "<tr><th>Recommendation</th>" + "".join(
        f"<th>d+{w} hit rate (n)</th>" for w in EVAL_WINDOWS
    ) + "</tr>"

    rows = []
    for rec in recoms:
        cells = f"<td><code>{rec}</code></td>"
        for w in EVAL_WINDOWS:
            entry = hit_rates.get(f"d{w}", {}).get(rec)
            if entry and entry["total"] > 0:
                cells += _pct_cell(entry["pct"]) + f"<td style='font-size:11px;color:#666'>{entry['hits']}/{entry['total']}</td>"
            else:
                cells += '<td class="na">—</td><td class="na">—</td>'
        rows.append(f"<tr>{cells}</tr>")

    # Merge the n columns into the pct column for cleaner layout
    # Rebuild: one cell per window showing "60.0% (6/10)"
    header = "<tr><th>Recommendation</th>" + "".join(
        f"<th>d+{w} hit rate</th>" for w in EVAL_WINDOWS
    ) + "</tr>"
    rows = []
    for rec in recoms:
        cells = f"<td><code>{rec}</code></td>"
        for w in EVAL_WINDOWS:
            entry = hit_rates.get(f"d{w}", {}).get(rec)
            if entry and entry["total"] > 0:
                color = "#2a7a2a" if entry["pct"] >= 55 else ("#b33" if entry["pct"] < 45 else "#777")
                cells += (
                    f'<td style="color:{color};font-weight:bold">'
                    f'{entry["pct"]:.1f}% ({entry["hits"]}/{entry["total"]})</td>'
                )
            else:
                cells += '<td class="na">—</td>'
        rows.append(f"<tr>{cells}</tr>")

    return f'<table>{header}{"".join(rows)}</table>'


def _best_worst_table(signals: list[dict], best: bool, n: int = 5) -> str:
    """Top-n best or worst directional calls.

    Best  = correct + highest (confidence × |move|) at d+10 (fallback d+30).
    Worst = incorrect + highest confidence, sorted by adverse move magnitude.
    """
    candidates = []
    for sig in signals:
        recom = sig.get("recommendation", "")
        if recom not in ("contrarian_buy", "reduce_exposure"):
            continue
        conf = sig.get("confidence") or 0

        # Prefer d+10, fall back to d+30, then d+5
        outcome = None
        for w in (10, 30, 5):
            o = sig.get("outcomes", {}).get(f"d{w}", {})
            if o.get("status") == "evaluated":
                outcome = o
                break
        if outcome is None:
            continue

        hit = outcome.get("hit")
        change_pct = outcome.get("change_pct", 0.0)

        if best and hit is not True:
            continue
        if not best and hit is not False:
            continue

        score = conf * abs(change_pct) if best else conf * abs(change_pct)
        candidates.append((score, sig, outcome, change_pct))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:n]

    if not top:
        return "<p>None.</p>"

    header = "<tr><th>Date</th><th>Ticker</th><th>Recommendation</th><th>Confidence</th><th>Move (d+10)</th><th>Reasoning</th></tr>"
    rows = []
    for _, sig, outcome, change_pct in top:
        tier_tag = f'<span class="tag-{sig["tier"]}">{sig["tier"].upper()}</span>'
        rows.append(
            f"<tr>"
            f"<td>{sig['date']}</td>"
            f"<td>{sig['ticker']} {tier_tag}</td>"
            f"<td><code>{sig['recommendation']}</code></td>"
            f"<td>{sig['confidence']}</td>"
            f"<td>{_change_str(change_pct)}</td>"
            f"<td style='font-size:12px'>{sig.get('reasoning','')[:200]}</td>"
            f"</tr>"
        )

    return f'<table>{header}{"".join(rows)}</table>'


def _confidence_calibration(signals: list[dict]) -> str:
    """Hit rate broken down by confidence band at d+10 (best single window)."""
    bands = [(1, 4), (5, 6), (7, 8), (9, 10)]
    data: dict[str, dict] = {f"{lo}-{hi}": {"hits": 0, "total": 0} for lo, hi in bands}

    for sig in signals:
        recom = sig.get("recommendation", "")
        if recom not in ("contrarian_buy", "reduce_exposure"):
            continue
        conf = sig.get("confidence") or 0
        outcome = sig.get("outcomes", {}).get("d10", {})
        if outcome.get("status") != "evaluated":
            continue
        hit = outcome.get("hit")
        if hit is None:
            continue

        for lo, hi in bands:
            if lo <= conf <= hi:
                band_key = f"{lo}-{hi}"
                data[band_key]["total"] += 1
                if hit:
                    data[band_key]["hits"] += 1
                break

    header = "<tr><th>Confidence band</th><th>d+10 hit rate</th><th>Calls</th></tr>"
    rows = []
    for lo, hi in bands:
        k = f"{lo}-{hi}"
        t = data[k]["total"]
        h = data[k]["hits"]
        if t > 0:
            pct = round(100 * h / t, 1)
            color = "#2a7a2a" if pct >= 55 else ("#b33" if pct < 45 else "#777")
            pct_str = f'<span style="color:{color};font-weight:bold">{pct:.1f}%</span>'
        else:
            pct_str = '<span class="na">—</span>'
        rows.append(f"<tr><td>{k}</td><td>{pct_str}</td><td>{t}</td></tr>")

    return f'<table>{header}{"".join(rows)}</table>'


def _token_summary(token_usage: dict) -> str:
    rows = []
    labels = {
        "input_tokens":                "Input tokens",
        "output_tokens":               "Output tokens",
        "cache_read_input_tokens":     "Cache-read tokens",
        "cache_creation_input_tokens": "Cache-write tokens",
    }
    for key, label in labels.items():
        val = token_usage.get(key, 0)
        rows.append(f"<tr><td>{label}</td><td>{val:,}</td></tr>")
    return f'<table><tr><th>Metric</th><th>Count</th></tr>{"".join(rows)}</table>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html_report(results: dict) -> str:
    """Return a self-contained HTML string for the backtest report."""
    period  = results.get("period_name", "unknown")
    start   = results.get("start_date", "")
    end     = results.get("end_date", "")
    signals = results.get("signals", [])
    hr      = results.get("hit_rates", {})
    tu      = results.get("token_usage", {})

    cap_warning = ""
    if results.get("cap_reached"):
        cap_warning = (
            "<div style='background:#ffeeba;border-left:4px solid #f0ad4e;"
            "padding:8px 12px;font-size:13px;border-radius:0 4px 4px 0;margin-top:8px;'>"
            "⚠ <strong>200-call cap reached</strong> — backtest stopped early. "
            "Results cover only the signals collected before the cutoff."
            "</div>"
        )

    body = f"""
<div class="card">
  <h1>Backtest Report — {period}</h1>
  <div class="sub">{start} → {end} &nbsp;|&nbsp; {len(results.get('tickers',[]))} tickers</div>
  {_stat_grid(results)}
  <div class="note">
    ⚠ No sentiment data available for historical periods — technical signals only
    (volume, price velocity, RSI). Social-heat-based Divergence Rules were not applied.
    Macro context (Fear &amp; Greed, VIX, Buffett) was marked unavailable in each prompt.
  </div>
  {cap_warning}
</div>

<div class="card">
  <h2>Hit Rate by Recommendation Type</h2>
  {_hit_rate_table(hr)}
</div>

<div class="card">
  <h2>Top 5 Best Calls</h2>
  <div class="sub">Directional calls that were correct, ranked by confidence × |move| at d+10</div>
  {_best_worst_table(signals, best=True)}
</div>

<div class="card">
  <h2>Top 5 Worst Calls</h2>
  <div class="sub">High-confidence directional calls that were wrong, ranked by confidence × adverse move</div>
  {_best_worst_table(signals, best=False)}
</div>

<div class="card">
  <h2>Confidence Calibration (d+10)</h2>
  <div class="sub">Are high-confidence calls actually more accurate?</div>
  {_confidence_calibration(signals)}
</div>

<div class="card">
  <h2>Token Usage Summary</h2>
  {_token_summary(tu)}
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest — {period}</title>
{_STYLE}
</head>
<body>
{body}
</body>
</html>"""


def save_report(results: dict, output_path: str | None = None) -> str:
    """Generate HTML report and write it to disk. Returns the file path."""
    period = results.get("period_name", "backtest")

    if output_path is None:
        results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(results_dir, exist_ok=True)
        output_path = os.path.join(results_dir, f"{period}_report.html")

    html = generate_html_report(results)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    return output_path
