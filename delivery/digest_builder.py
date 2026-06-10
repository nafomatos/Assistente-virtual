"""Build the Tier-1 digest email — mobile-first, one-screen summary.

Sends only the essential daily briefing with a link to the full report on
GitHub Pages. The full HTML email (asset cards, paste block, etc.) is
written to docs/reports/YYYY-MM-DD.html by pages_publisher.py instead.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib

from output.document_builder import get_alert_tier

PAGES_BASE_URL = "https://nafomatos.github.io/Assistente-virtual"


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _fg_color(score: int) -> str:
    if score < 30:
        return "#ef4444"
    if score < 45:
        return "#f97316"
    if score < 55:
        return "#94a3b8"
    if score < 70:
        return "#4ade80"
    return "#22c55e"


def _rec_label(rec: str) -> tuple[str, str]:
    """Return (display text, badge background color)."""
    if rec == "contrarian_buy":
        return "BUY ↑", "#16a34a"
    if rec == "reduce_exposure":
        return "REDUCE ↓", "#dc2626"
    return rec.upper(), "#475569"


def build_digest_subject(n_actionable: int, date: dt.date) -> str:
    return f"[Radar] {n_actionable} actionable · {date.strftime('%d %b %Y')}"


def build_digest_html(
    results: list[dict],
    date: dt.date,
    fear_greed: dict | None,
    vix_structure: dict | None,
    buffett: dict | None,
    open_positions: list[dict] | None = None,
    classified_signals: list[dict] | None = None,
    active_clusters: list[dict] | None = None,
    stopped_out_today: list[dict] | None = None,
) -> str:
    """Build mobile-first digest HTML (~1 phone screen, <500 words)."""
    classified_signals = classified_signals or []
    active_clusters    = active_clusters or []
    open_positions     = open_positions or []
    stopped_out_today  = stopped_out_today or []

    sizing_by_ticker = {
        r["ticker"]: r["sizing_block"]
        for r in results
        if r.get("sizing_block")
    }

    actionable = [
        s for s in classified_signals
        if s.get("recommendation") in ("contrarian_buy", "reduce_exposure")
    ]

    # Tickers whose volume metrics were nulled by the artifact containment
    # (analyzers/volume_quality.py) — actionable rows for these get a note.
    artifact_tickers = {
        r["ticker"] for r in results
        if (r["signals"].get("volume") or {}).get("artifact")
        or (r["signals"].get("volume") or {}).get("data_quality") == "suspicious_volume"
    }

    red_count   = sum(1 for r in results if get_alert_tier(r["signals"]) == "red")
    amber_count = sum(1 for r in results if get_alert_tier(r["signals"]) == "amber")
    report_url  = f"{PAGES_BASE_URL}/reports/{date.isoformat()}.html"

    # ── Macro ──────────────────────────────────────────────────────────────
    fg_score  = (fear_greed or {}).get("score")
    fg_label  = (fear_greed or {}).get("label", "")
    buf_pct   = (buffett or {}).get("ratio_pct")
    buf_cls   = (buffett or {}).get("classification", "")
    vix_val   = (vix_structure or {}).get("vix")
    vix_inv   = (vix_structure or {}).get("vix_inverted", False)

    macro_parts = []
    if fg_score is not None:
        color = _fg_color(fg_score)
        macro_parts.append(
            f"F&amp;G&nbsp;<span style='color:{color};font-weight:700;'>{fg_score}</span>"
            f"<span style='color:#64748b;'>&nbsp;{html_lib.escape(fg_label)}</span>"
        )
    if buf_pct is not None:
        macro_parts.append(
            f"Buffett&nbsp;<span style='color:#94a3b8;font-weight:600;'>{buf_pct:.0f}%</span>"
            f"<span style='color:#475569;'>&nbsp;{html_lib.escape(buf_cls)}</span>"
        )
    if vix_val is not None:
        vix_color = "#ef4444" if vix_inv else "#94a3b8"
        vix_state = "⚠ Backwardation" if vix_inv else "Normal"
        macro_parts.append(
            f"VIX&nbsp;<span style='color:{vix_color};'>{vix_val:.1f}&nbsp;—&nbsp;{vix_state}</span>"
        )

    macro_html = ""
    if macro_parts:
        macro_html = (
            f"<div style='background:#1e1e1e;border-radius:6px;padding:12px 16px;"
            f"margin-bottom:14px;font-size:12px;line-height:1.9;'>"
            f"<div style='font-size:9px;font-weight:700;color:#475569;letter-spacing:.08em;"
            f"text-transform:uppercase;margin-bottom:6px;'>MACRO</div>"
            + "&nbsp;&nbsp;·&nbsp;&nbsp;".join(macro_parts)
            + "</div>"
        )

    # ── Coverage ───────────────────────────────────────────────────────────
    coverage_html = (
        f"<div style='font-size:12px;color:#64748b;margin-bottom:14px;'>"
        f"<span style='color:#ef4444;font-weight:700;'>{red_count} RED</span>"
        f"&nbsp;&nbsp;"
        f"<span style='color:#f97316;font-weight:700;'>{amber_count} AMBER</span>"
        f"&nbsp;&nbsp;·&nbsp;&nbsp;"
        f"<span style='color:#475569;'>{len(results)} tickers</span>"
        f"</div>"
    )

    # ── Portfolio ──────────────────────────────────────────────────────────
    positions_html = ""
    if open_positions or stopped_out_today:
        stopped_line = ""
        if stopped_out_today:
            tickers_str = "&nbsp;&middot;&nbsp;".join(
                f"<span style='font-weight:600;'>{html_lib.escape(p['ticker'])}</span>"
                f"&nbsp;<span style='color:#f97316;'>{p.get('pnl_pct', 0):+.1f}%</span>"
                for p in stopped_out_today
            )
            stopped_line = (
                f"<div style='margin-top:6px;font-size:11px;color:#f97316;'>"
                f"&#9888; Stopped out today:&nbsp;{tickers_str}"
                f"</div>"
            )

        summary_line = ""
        if open_positions:
            sorted_pos = sorted(open_positions, key=lambda p: p.get("pnl_pct", 0))
            worst = sorted_pos[0]
            best  = sorted_pos[-1]
            summary_line = (
                f"<span style='color:#64748b;'>{len(open_positions)} open</span>"
                f"&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"Best&nbsp;<span style='font-weight:600;'>{html_lib.escape(best['ticker'])}</span>"
                f"&nbsp;<span style='color:#4ade80;'>{best.get('pnl_pct', 0):+.1f}%</span>"
                f"&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"Worst&nbsp;<span style='font-weight:600;'>{html_lib.escape(worst['ticker'])}</span>"
                f"&nbsp;<span style='color:#ef4444;'>{worst.get('pnl_pct', 0):+.1f}%</span>"
            )

        positions_html = (
            f"<div style='background:#1e1e1e;border-radius:6px;padding:12px 16px;"
            f"margin-bottom:14px;font-size:12px;'>"
            f"<div style='font-size:9px;font-weight:700;color:#475569;letter-spacing:.08em;"
            f"text-transform:uppercase;margin-bottom:6px;'>PORTFOLIO</div>"
            f"{summary_line}"
            f"{stopped_line}"
            f"</div>"
        )

    # ── Actionable signals ─────────────────────────────────────────────────
    if actionable:
        rows = ""
        for sig in actionable:
            ticker = sig["ticker"]
            rec    = sig.get("recommendation", "")
            conf   = sig.get("confidence", 0)
            reason = _truncate(sig.get("reasoning", ""), 100)
            label, badge_color = _rec_label(rec)
            sb       = sizing_by_ticker.get(ticker)
            size_str = f"{sb['position_size_pct']:.1f}%" if sb else "n/a"
            d10_str  = sb["windows"]["d10"] if sb else "—"
            artifact_note = ""
            if ticker in artifact_tickers:
                artifact_note = (
                    f"<div style='font-size:10px;color:#f97316;margin-top:3px;'>"
                    f"&#9888; (volume data excluded &mdash; unreliable)</div>"
                )
            rows += (
                f"<div style='border-top:1px solid #27272a;padding:10px 0;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"margin-bottom:5px;'>"
                f"<span style='font-weight:700;font-size:15px;color:#f1f5f9;'>"
                f"{html_lib.escape(ticker)}</span>"
                f"<span style='background:{badge_color};color:#fff;font-size:10px;"
                f"font-weight:700;padding:2px 7px;border-radius:3px;'>{label}</span>"
                f"</div>"
                f"<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
                f"Alloc&nbsp;<span style='color:#f1f5f9;font-weight:600;'>{html_lib.escape(size_str)}</span>"
                f"&nbsp;&nbsp;d+10&nbsp;<span style='color:#94a3b8;'>{html_lib.escape(d10_str)}</span>"
                f"&nbsp;&nbsp;conf&nbsp;<span style='color:#94a3b8;'>{conf}/10</span>"
                f"</div>"
                f"<div style='font-size:11px;color:#94a3b8;font-style:italic;'>"
                f"{html_lib.escape(reason)}</div>"
                f"{artifact_note}"
                f"</div>"
            )
        actionable_html = (
            f"<div style='background:#1a1a1a;border-radius:6px;"
            f"padding:12px 16px;margin-bottom:14px;'>"
            f"<div style='font-size:9px;font-weight:700;color:#475569;letter-spacing:.08em;"
            f"text-transform:uppercase;margin-bottom:4px;'>ACTIONABLE SIGNALS</div>"
            f"{rows}"
            f"</div>"
        )
    else:
        actionable_html = (
            f"<div style='background:#1a1a1a;border-radius:6px;padding:14px 16px;"
            f"margin-bottom:14px;font-size:13px;color:#64748b;font-style:italic;'>"
            f"No actionable signals today — monitoring continues."
            f"</div>"
        )

    # ── Cluster alerts ─────────────────────────────────────────────────────
    cluster_html = ""
    if active_clusters:
        rows = ""
        for cl in active_clusters:
            sector    = html_lib.escape(cl.get("sector", "?"))
            direction = html_lib.escape(cl.get("direction_group", "?"))
            count     = cl.get("count", 0)
            tickers_s = html_lib.escape(", ".join(cl.get("tickers", [])))
            rows += (
                f"<div style='font-size:12px;padding:5px 0;border-top:1px solid #1e3a5f;'>"
                f"<span style='color:#60a5fa;font-weight:700;'>{sector}</span>"
                f"&nbsp;—&nbsp;"
                f"<span style='color:#94a3b8;'>{direction}</span>"
                f"&nbsp;<span style='color:#475569;'>({count}: {tickers_s})</span>"
                f"</div>"
            )
        cluster_html = (
            f"<div style='background:#0f1f35;border:1px solid #1e3a5f;border-radius:6px;"
            f"padding:12px 16px;margin-bottom:14px;'>"
            f"<div style='font-size:9px;font-weight:700;color:#3b82f6;letter-spacing:.08em;"
            f"text-transform:uppercase;margin-bottom:4px;'>CLUSTER ALERTS</div>"
            f"{rows}"
            f"</div>"
        )

    # ── Full-report CTA ────────────────────────────────────────────────────
    link_html = (
        f"<div style='text-align:center;margin-top:20px;'>"
        f"<a href='{html_lib.escape(report_url)}'"
        f" style='display:inline-block;background:#1e40af;color:#fff;font-size:13px;"
        f"font-weight:600;padding:11px 26px;border-radius:6px;text-decoration:none;'>"
        f"View Full Report &rarr;</a>"
        f"<div style='margin-top:8px;font-size:10px;color:#374151;'>"
        f"{html_lib.escape(report_url)}</div>"
        f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f1f5f9;">
<div style="max-width:480px;margin:0 auto;padding:20px 16px;">

  <div style="margin-bottom:16px;">
    <div style="font-size:9px;font-weight:700;color:#475569;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;">Artificial Price Radar</div>
    <div style="font-size:20px;font-weight:700;color:#f1f5f9;">{len(actionable)} actionable &mdash; {date.strftime('%d %b %Y')}</div>
  </div>

  {macro_html}
  {coverage_html}
  {positions_html}
  {actionable_html}
  {cluster_html}
  {link_html}

  <div style="margin-top:24px;font-size:10px;color:#374151;text-align:center;">
    Generated {date.isoformat()} &middot; Artificial Price Radar
  </div>

</div>
</body>
</html>"""
