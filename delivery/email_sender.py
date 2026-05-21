"""Gmail SMTP delivery — multipart HTML + plain-text fallback.

Credentials from environment (see .env.example):
    GMAIL_ADDRESS       sending account
    GMAIL_APP_PASSWORD  App Password (not the Google account password)
    EMAIL_RECIPIENT     recipient address
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import os
import smtplib
from email.message import EmailMessage

from config import TICKER_NAMES
from output.document_builder import OUTPUT_DIR, get_alert_tier

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class EmailConfigError(RuntimeError):
    """Missing or invalid email configuration."""


def _load_config() -> tuple[str, str, str]:
    sender    = os.environ.get("GMAIL_ADDRESS")
    password  = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT")
    missing = [k for k, v in (("GMAIL_ADDRESS", sender),
                               ("GMAIL_APP_PASSWORD", password),
                               ("EMAIL_RECIPIENT", recipient)) if not v]
    if missing:
        raise EmailConfigError(f"missing env vars: {', '.join(missing)} — see .env.example")
    return sender, password, recipient


# ── colour helpers ─────────────────────────────────────────────────────────

def _fg_color(score: int) -> str:
    if score < 30:  return "#ef4444"
    if score < 45:  return "#f97316"
    if score < 55:  return "#94a3b8"
    if score < 70:  return "#4ade80"
    return "#22c55e"


def _buffett_color(classification: str) -> str:
    return {"Undervalued": "#22c55e", "Fair Value": "#4ade80",
            "Overvalued": "#f97316", "Extreme": "#ef4444"}.get(classification, "#94a3b8")


def _tier_color(tier: str) -> str:
    return "#ef4444" if tier == "red" else "#f97316"


def _truncate(text: str, n: int = 90) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


# ── position tracker cards ─────────────────────────────────────────────────

def _position_border_color(pnl_pct: float) -> str:
    if pnl_pct > 2.0:
        return "#22c55e"   # green — on track
    if pnl_pct < -2.0:
        return "#ef4444"   # red — underwater
    return "#475569"       # grey — neutral


def _direction_badge(direction: str) -> str:
    color = "#22c55e" if direction == "long" else "#f97316"
    label = "LONG ↑" if direction == "long" else "SHORT ↓"
    return (
        f"<span style='background:{color};color:#fff;font-size:10px;font-weight:700;"
        f"padding:2px 6px;border-radius:3px;'>{label}</span>"
    )


def _status_badge(status: str) -> str:
    colors = {
        "ON TRACK":    "#22c55e",
        "UNDERWATER":  "#ef4444",
        "NEUTRAL":     "#64748b",
        "STOPPED_OUT": "#f97316",  # orange — distinct from UNDERWATER red
    }
    c = colors.get(status, "#64748b")
    return f"<span style='color:{c};font-weight:700;font-size:11px;'>{status}</span>"


def _position_card(pos: dict) -> str:
    """Render one open position as a dark-theme card."""
    ticker      = html.escape(pos["ticker"])
    direction   = pos.get("direction", "long")
    confidence  = pos.get("confidence", "?")
    entry_price = pos.get("entry_price", 0)
    entry_date  = pos.get("entry_date", "")
    current     = pos.get("current_price", entry_price)
    pnl_pct     = pos.get("pnl_pct", 0.0)
    days_held   = pos.get("days_held", 0)
    status      = pos.get("status", "NEUTRAL")

    border  = _position_border_color(pnl_pct)
    dir_badge = _direction_badge(direction)
    st_badge  = _status_badge(status)

    pnl_color = "#22c55e" if pnl_pct >= 0 else "#ef4444"
    pnl_sign  = "+" if pnl_pct >= 0 else ""

    # Progress bar — days_held / 30
    pct_complete = min(100, int(days_held / 30 * 100))
    bar_color = border

    return (
        f"<div style='background:#1a1a1a;border-radius:6px;border-left:4px solid {border};"
        f"padding:12px 14px;margin-bottom:8px;'>"
        # header row
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>"
        f"<div>"
        f"<span style='font-weight:700;font-size:14px;'>{ticker}</span>"
        f"&nbsp;&nbsp;{dir_badge}"
        f"&nbsp;&nbsp;<span style='color:#64748b;font-size:11px;'>conf {confidence}</span>"
        f"</div>"
        f"<div style='text-align:right;font-size:12px;'>"
        f"<span style='color:#94a3b8;'>Entry</span> <span style='font-weight:600;'>${entry_price:.2f}</span>"
        f"&nbsp;&nbsp;<span style='color:#94a3b8;'>on</span> <span style='color:#cbd5e1;'>{entry_date}</span>"
        f"</div>"
        f"</div>"
        # price + P&L row
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'>"
        f"<div style='font-size:13px;'>"
        f"<span style='color:#94a3b8;'>Current</span> "
        f"<span style='font-weight:700;font-size:14px;'>${current:.2f}</span>"
        f"&nbsp;<span style='color:{pnl_color};font-weight:700;'>({pnl_sign}{pnl_pct:.1f}%)</span>"
        f"</div>"
        f"<div style='font-size:11px;color:#64748b;'>"
        f"Days held: <span style='color:#94a3b8;font-weight:600;'>{days_held}</span> / 30"
        f"&nbsp;&nbsp;{st_badge}"
        f"</div>"
        f"</div>"
        # progress bar
        f"<div style='background:#2d2d2d;border-radius:3px;height:3px;'>"
        f"<div style='background:{bar_color};width:{pct_complete}%;height:3px;border-radius:3px;'></div>"
        f"</div>"
        f"</div>"
    )


def _active_positions_card(
    open_positions: list[dict],
    closed_stats: dict | None,
    stopped_out_today: list[dict] | None = None,
) -> str:
    """ACTIVE POSITIONS section inserted above macro context."""
    stopped_out_today = stopped_out_today or []
    if not open_positions and not closed_stats and not stopped_out_today:
        return ""

    # Stopped-out positions appear first with STOPPED_OUT status badge
    stopped_cards = ""
    for pos in stopped_out_today:
        enriched = {
            **pos,
            "current_price": pos.get("exit_price", pos["entry_price"]),
            "days_held":     pos.get("days_held", 0),
            "status":        "STOPPED_OUT",
        }
        stopped_cards += _position_card(enriched)

    position_html = stopped_cards
    if open_positions:
        position_html += "".join(_position_card(p) for p in open_positions)
    if not position_html:
        position_html = (
            "<div style='color:#64748b;font-style:italic;font-size:12px;"
            "padding:8px 0;'>No open positions.</div>"
        )

    # Closed summary line
    summary_html = ""
    if closed_stats and closed_stats.get("total", 0) > 0:
        total    = closed_stats["total"]
        correct  = closed_stats["correct"]
        win_rate = closed_stats["win_rate"]
        avg_pnl  = closed_stats["avg_pnl"]
        pnl_color = "#22c55e" if avg_pnl >= 0 else "#ef4444"
        pnl_sign  = "+" if avg_pnl >= 0 else ""
        summary_html = (
            f"<div style='margin-top:10px;padding-top:10px;border-top:1px solid #2d2d2d;"
            f"font-size:11px;color:#64748b;'>"
            f"Closed positions: "
            f"<span style='color:#94a3b8;'>{total} total</span>"
            f" &middot; <span style='color:#22c55e;'>{correct} correct ({win_rate:.1f}%)</span>"
            f" &middot; Avg P&amp;L: "
            f"<span style='color:{pnl_color};font-weight:700;'>{pnl_sign}{avg_pnl:.1f}%</span>"
            f"</div>"
        )

    n_open = len(open_positions)
    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:12px;'>ACTIVE POSITIONS "
        f"<span style='color:#475569;font-weight:400;'>({n_open} open)</span></div>"
        f"{position_html}"
        f"{summary_html}"
        f"</div>"
    )


# ── macro card ─────────────────────────────────────────────────────────────

def _macro_card(
    fear_greed: dict | None,
    vix_structure: dict | None,
    buffett: dict | None,
) -> str:
    # Fear & Greed row
    if fear_greed:
        fc = _fg_color(fear_greed["score"])
        delta = ""
        if fear_greed.get("previous_score") is not None:
            diff = fear_greed["score"] - fear_greed["previous_score"]
            delta = f" <span style='color:#64748b;font-size:11px;'>({'+' if diff > 0 else ''}{diff})</span>"
        fg_cell = (
            f"<span style='color:{fc};font-weight:700;'>"
            f"{fear_greed['score']}/100 — {html.escape(fear_greed['label'])}"
            f"</span>{delta}"
        )
    else:
        fg_cell = "<span style='color:#64748b;'>unavailable</span>"

    # VIX row
    if vix_structure:
        vc = "#ef4444" if vix_structure["vix_inverted"] else "#4ade80"
        vix_label = "Backwardation" if vix_structure["vix_inverted"] else "Contango"
        vix_note  = "stress elevated" if vix_structure["vix_inverted"] else "normal"
        vix_cell = (
            f"<span style='color:{vc};font-weight:700;'>{vix_label} ({vix_structure['ratio']:.2f})</span>"
            f" <span style='color:#64748b;font-size:11px;'>— {vix_note}</span>"
        )
    else:
        vix_cell = "<span style='color:#64748b;'>unavailable</span>"

    # Buffett row
    if buffett:
        bc = _buffett_color(buffett["classification"])
        buffett_cell = (
            f"<span style='color:{bc};font-weight:700;'>"
            f"{buffett['ratio_pct']:.0f}% — {html.escape(buffett['classification'])}"
            f"</span>"
            f" <span style='color:#64748b;font-size:11px;'>(avg ~120%)</span>"
        )
    else:
        buffett_cell = "<span style='color:#64748b;'>unavailable</span>"

    rows = [("Fear &amp; Greed", fg_cell),
            ("VIX Structure",    vix_cell),
            ("Buffett Indicator", buffett_cell)]
    trs = "".join(
        f"<tr>"
        f"<td style='color:#94a3b8;padding:4px 14px 4px 0;font-size:12px;white-space:nowrap;vertical-align:middle;'>{label}</td>"
        f"<td style='font-size:13px;padding:4px 0;vertical-align:middle;'>{value}</td>"
        f"</tr>"
        for label, value in rows
    )
    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>MACRO CONTEXT</div>"
        f"<table style='border-collapse:collapse;width:100%;'><tbody>{trs}</tbody></table>"
        f"</div>"
    )


# ── coverage card ──────────────────────────────────────────────────────────

def _coverage_card(red: list[str], amber: list[str], total: int) -> str:
    n_skip = total - len(red) - len(amber)

    def badge(text: str, color: str) -> str:
        return (
            f"<span style='background:{color};color:#fff;font-size:11px;font-weight:700;"
            f"padding:2px 8px;border-radius:3px;margin-right:6px;display:inline-block;'>"
            f"{text}</span>"
        )

    badges = badge(f"{len(red)} RED", "#ef4444") + badge(f"{len(amber)} AMBER", "#f97316") + badge(f"{n_skip} filtered", "#374151")
    tickers_html = ""
    if red:
        tickers_html += f"<div style='margin-top:8px;font-size:11px;color:#64748b;'>RED: {', '.join(red)}</div>"
    if amber:
        tickers_html += f"<div style='margin-top:3px;font-size:11px;color:#64748b;'>AMBER: {', '.join(amber)}</div>"

    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:14px 20px;margin-bottom:20px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>COVERAGE — {total} tickers scanned</div>"
        f"{badges}"
        f"{tickers_html}"
        f"</div>"
    )


# ── sentiment summary ──────────────────────────────────────────────────────

def _sentiment_row(sentiment: dict | None) -> str:
    if not sentiment:
        return "<span style='color:#64748b;font-style:italic;'>Sentiment: pending</span>"

    parts = []
    st_heat = sentiment.get("stocktwits_heat")
    heat_z  = sentiment.get("social_heat_zscore")
    bd      = sentiment.get("source_breakdown") or {}
    st_str  = bd.get("stocktwits") or ""

    st_tone = None
    if "tone=" in st_str:
        st_tone = st_str.split("tone=")[-1].split(",")[0].strip()

    if st_heat and st_heat not in ("unknown",):
        heat_color = {"explosive": "#ef4444", "elevated": "#f97316",
                      "stable": "#4ade80", "low": "#64748b"}.get(st_heat, "#94a3b8")
        parts.append(f"Heat: <span style='color:{heat_color};font-weight:700;'>{st_heat.title()}</span>")

    if st_tone and st_tone not in ("n/a", "unknown"):
        tone_color = {"bullish": "#4ade80", "bearish": "#ef4444",
                      "neutral": "#94a3b8"}.get(st_tone, "#94a3b8")
        parts.append(f"Tone: <span style='color:{tone_color};font-weight:700;'>{st_tone.title()}</span>")

    if heat_z is not None:
        zc = "#ef4444" if heat_z > 2 else "#f97316" if heat_z > 1 else "#94a3b8"
        parts.append(f"Social-z: <span style='color:{zc};font-weight:700;'>{heat_z:+.1f}</span>")

    youtube = bd.get("youtube")
    if youtube and youtube != "n/a" and "tone=" in youtube:
        yt_tone = youtube.split("tone=")[-1].split(",")[0].strip()
        if yt_tone and yt_tone not in ("n/a", "unknown"):
            yc = {"bullish": "#4ade80", "bearish": "#ef4444",
                  "neutral": "#94a3b8"}.get(yt_tone, "#94a3b8")
            parts.append(f"YouTube: <span style='color:{yc};font-weight:700;'>{yt_tone.title()}</span>")

    if not parts:
        return "<span style='color:#64748b;font-style:italic;'>Sentiment: n/a</span>"
    return " &middot; ".join(parts)


# ── cluster alerts card ────────────────────────────────────────────────────

def _data_quality_badge(data_quality: str, ratio: float) -> str:
    """Warning banner shown when volume multiple exceeds the suspicious threshold."""
    if data_quality != "suspicious_volume":
        return ""
    return (
        f"<div style='background:#422006;border:1px solid #92400e;border-radius:4px;"
        f"padding:6px 10px;margin-top:8px;font-size:11px;color:#fbbf24;font-weight:600;'>"
        f"⚠ DATA QUALITY: extreme volume reading ({ratio:.1f}x) — verify before acting"
        f"</div>"
    )


def _cluster_boost_badge(cluster_boost: dict) -> str:
    """Inline badge shown on individual asset cards when a cluster boost was applied."""
    sector    = cluster_boost.get("sector", "")
    direction = cluster_boost.get("direction_group", "")
    count     = cluster_boost.get("count", 0)
    amount    = cluster_boost.get("boost_amount", 0)
    return (
        f"<span style='background:#1e3a5f;color:#93c5fd;font-size:10px;font-weight:700;"
        f"padding:2px 7px;border-radius:3px;margin-left:6px;'>"
        f"cluster boost: +{amount} ({sector} {direction}, {count} tickers)"
        f"</span>"
    )


def _cluster_alerts_card(active_clusters: list[dict]) -> str:
    """CLUSTER ALERTS section rendered before individual ticker cards."""
    if not active_clusters:
        return ""

    rows_html = ""
    for c in active_clusters:
        sector    = html.escape(c["sector"])
        direction = html.escape(c["direction_group"])
        count     = c["count"]
        boost     = c["boost"]
        first     = html.escape(c.get("first_seen", ""))
        last      = html.escape(c.get("last_seen", ""))
        tickers   = html.escape(", ".join(c.get("tickers", [])))

        try:
            days_span = (
                dt.date.fromisoformat(c["last_seen"]) - dt.date.fromisoformat(c["first_seen"])
            ).days + 1
        except (KeyError, ValueError):
            days_span = 0

        rows_html += (
            f"<div style='border-top:1px solid #1e3a5f;padding:10px 0;'>"
            f"<div style='font-size:13px;font-weight:600;color:#93c5fd;margin-bottom:4px;'>"
            f"{sector} &middot; {direction} &middot; "
            f"<span style='color:#f1f5f9;'>{count} tickers in {days_span} days</span>"
            f"</div>"
            f"<div style='font-size:11px;color:#64748b;margin-bottom:2px;'>"
            f"&rarr; confidence +{boost} applied to all signals in the cluster"
            f"</div>"
            f"<div style='font-size:11px;color:#64748b;'>"
            f"&rarr; tickers: <span style='color:#94a3b8;'>{tickers}</span>"
            f"</div>"
            f"</div>"
        )

    return (
        f"<div style='background:#0f1f35;border:1px solid #1e3a5f;border-radius:6px;"
        f"padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#3b82f6;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:4px;'>CLUSTER ALERTS</div>"
        f"<div style='font-size:10px;color:#475569;margin-bottom:8px;'>"
        f"3+ tickers from the same sector signalling in the same direction within 5 days"
        f"</div>"
        f"{rows_html}"
        f"</div>"
    )


# ── sizing panel ──────────────────────────────────────────────────────────

def _sizing_panel(sizing_block: dict) -> str:
    """Render the sizing + targets block as a muted monospace panel."""
    size = sizing_block["position_size_pct"]
    t    = sizing_block["targets"]
    w    = sizing_block["windows"]
    s    = sizing_block["strikes"]

    is_bearish = t.get("is_bearish", False)
    z_labels   = ("z=+1", "z=0", "z=−1") if is_bearish else ("z=−1", "z=0", "z=+1")

    def _px(v: float) -> str:
        return f"${v:,.2f}"

    label_style = "color:#4b5563;"
    value_style = "color:#9ca3af;"

    def row(label: str, value: str) -> str:
        pad = "&nbsp;" * max(0, 17 - len(label))
        return (
            f"<div style='margin:2px 0;font-size:11px;'>"
            f"<span style='{label_style}'>{label}{pad}</span>"
            f"<span style='{value_style}'>{value}</span>"
            f"</div>"
        )

    targets_str = (
        f"conservative {_px(t['conservative'])} ({z_labels[0]})"
        f" &nbsp;|&nbsp; medium {_px(t['medium'])} ({z_labels[1]})"
        f" &nbsp;|&nbsp; aggressive {_px(t['aggressive'])} ({z_labels[2]})"
    )
    window_str = (
        f"checkpoint {w['d10']} (d+10) &middot; close {w['d30']} (d+30)"
    )
    strikes_str = (
        f"ATM ${s['atm']:,} &nbsp;|&nbsp; OTM 5% ${s['otm_5pct']:,}"
        f" &nbsp;|&nbsp; OTM 10% ${s['otm_10pct']:,}"
    )

    return (
        f"<div style='background:#111827;border:1px solid #1f2937;border-radius:4px;"
        f"padding:10px 12px;margin-top:10px;"
        f"font-family:\"Menlo\",\"Monaco\",\"Courier New\",monospace;'>"
        f"<div style='font-size:9px;font-weight:700;color:#374151;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:6px;'>&#127919; SIZING &amp; TARGETS</div>"
        + row("Position size:", f"{size:.2f}% of capital")
        + row("Targets:", targets_str)
        + row("Window:", window_str)
        + row("Option strikes:", strikes_str)
        + "</div>"
    )


# ── asset card ─────────────────────────────────────────────────────────────

def _asset_card(ticker: str, signals: dict, tier: str, cluster_boost: dict | None = None, sizing_block: dict | None = None) -> str:
    name = TICKER_NAMES.get(ticker, ticker)
    m = signals["market"]
    v = signals["volume"]
    p = signals["velocity"]
    r = signals.get("rsi") or {}
    s = signals.get("sentiment")

    border  = _tier_color(tier)
    tier_bg = _tier_color(tier)
    label_style = (
        f"background:{tier_bg};color:#fff;font-size:10px;font-weight:700;"
        f"padding:2px 6px;border-radius:3px;text-transform:uppercase;"
    )

    price = m["current_price"]
    ret   = m["daily_return_pct"]
    ret_color = "#4ade80" if ret >= 0 else "#ef4444"
    ret_sign  = "+" if ret >= 0 else ""

    vol_ratio = v["ratio"]
    vol_class = v["classification"]
    vol_color = {"extreme": "#ef4444", "anomalous": "#f97316"}.get(vol_class, "#94a3b8")

    z30  = p["z_score_30d"]
    z200 = p["z_score_200d"]
    z30_color = "#ef4444" if abs(z30) > 2 else "#f97316" if abs(z30) > 1.5 else "#94a3b8"

    rsi_val = r.get("rsi")
    rsi_cls = r.get("classification", "n/a")
    if rsi_val is not None:
        rsi_color = "#ef4444" if (rsi_val > 75 or rsi_val < 25) else "#f97316" if (rsi_val > 65 or rsi_val < 35) else "#94a3b8"
        rsi_html = f"<span style='color:{rsi_color};'>{rsi_val:.0f}</span> <span style='color:#64748b;font-size:10px;'>({rsi_cls})</span>"
    else:
        rsi_html = "<span style='color:#64748b;'>n/a</span>"

    metrics = [
        ("VOL",   f"<span style='color:{vol_color};font-weight:700;'>{vol_ratio:.1f}x</span> <span style='color:#64748b;font-size:10px;'>({vol_class})</span>"),
        ("Z-30D", f"<span style='color:{z30_color};font-weight:700;'>{z30:+.2f}</span>"),
        ("Z-200D",f"<span style='color:#94a3b8;'>{z200:+.2f}</span>"),
        ("RSI-14", rsi_html),
    ]
    metric_tds = "".join(
        f"<td style='padding:0 18px 0 0;vertical-align:top;'>"
        f"<div style='font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;'>{lbl}</div>"
        f"<div style='font-size:13px;'>{val}</div>"
        f"</td>"
        for lbl, val in metrics
    )

    news = m.get("recent_news") or []
    news_html = ""
    if news:
        first = news[0]
        title = html.escape(_truncate(first.get("title", ""), 90))
        pub   = html.escape(first.get("publisher") or "")
        age   = first.get("age_hours")
        age_s = f"{age}h ago" if isinstance(age, (int, float)) else ""
        meta  = ", ".join(filter(None, [pub, age_s]))
        news_html = (
            f"<div style='border-top:1px solid #2d2d2d;margin-top:10px;padding-top:8px;"
            f"font-size:11px;color:#cbd5e1;'>"
            f"<span style='color:#64748b;'>News: </span>{title}"
            f"<span style='color:#475569;'>{' — ' + meta if meta else ''}</span>"
            f"</div>"
        )

    sentiment_html = (
        f"<div style='margin-top:8px;font-size:11px;'>{_sentiment_row(s)}</div>"
    )

    boost_badge = _cluster_boost_badge(cluster_boost) if cluster_boost else ""
    dq_badge    = _data_quality_badge(v.get("data_quality", "ok"), v["ratio"])
    sizing_html = _sizing_panel(sizing_block) if sizing_block else ""

    return (
        f"<div style='background:#1a1a1a;border-radius:6px;border-left:4px solid {border};"
        f"padding:14px 16px;margin-bottom:12px;'>"
        # header
        f"<table style='width:100%;border-collapse:collapse;margin-bottom:10px;'><tbody><tr>"
        f"<td style='vertical-align:middle;'>"
        f"<span style='{label_style}'>{tier.upper()}</span>"
        f"&nbsp;<span style='font-weight:700;font-size:15px;'>{html.escape(ticker)}</span>"
        f"&nbsp;<span style='color:#94a3b8;font-size:12px;'>{html.escape(name)}</span>"
        f"{boost_badge}"
        f"</td>"
        f"<td style='text-align:right;vertical-align:middle;font-size:14px;font-weight:600;white-space:nowrap;'>"
        f"${price:,.2f}&nbsp;<span style='color:{ret_color};'>{ret_sign}{ret:.2f}%</span>"
        f"</td>"
        f"</tr></tbody></table>"
        # metrics
        f"<table style='border-collapse:collapse;'><tbody><tr>{metric_tds}</tr></tbody></table>"
        # data quality warning (shown only when suspicious_volume)
        f"{dq_badge}"
        # news + sentiment
        f"{news_html}"
        f"{sentiment_html}"
        # sizing & targets (only when classified signal is actionable)
        f"{sizing_html}"
        f"</div>"
    )


# ── full HTML document ─────────────────────────────────────────────────────

def build_html_email(
    results: list[dict],
    date: dt.date,
    fear_greed: dict | None,
    vix_structure: dict | None,
    buffett: dict | None,
    report_text: str,
    open_positions: list[dict] | None = None,
    closed_stats: dict | None = None,
    active_clusters: list[dict] | None = None,
    stopped_out_today: list[dict] | None = None,
) -> str:
    red_items   = [
        (r["ticker"], r["signals"], r.get("cluster_boost"), r.get("sizing_block"))
        for r in results if get_alert_tier(r["signals"]) == "red"
    ]
    amber_items = [
        (r["ticker"], r["signals"], r.get("cluster_boost"), r.get("sizing_block"))
        for r in results if get_alert_tier(r["signals"]) == "amber"
    ]
    red_tickers   = [t for t, _, _, _ in red_items]
    amber_tickers = [t for t, _, _, _ in amber_items]

    cards = "".join(_asset_card(t, s, "red",   cb, sb) for t, s, cb, sb in red_items)
    cards += "".join(_asset_card(t, s, "amber", cb, sb) for t, s, cb, sb in amber_items)
    if not cards:
        cards = (
            "<div style='background:#1a1a1a;border-radius:6px;padding:16px;color:#64748b;"
            "font-style:italic;text-align:center;font-size:13px;'>"
            "No alerts today — all tickers within normal ranges."
            "</div>"
        )

    # Append plain-text sizing blocks for any actionable signals
    from analyzers.position_sizing import format_sizing_text as _fmt_sizing

    sizing_lines = []
    for r in results:
        sb = r.get("sizing_block")
        if sb and get_alert_tier(r["signals"]):
            sizing_lines.append(_fmt_sizing(r["ticker"], sb))
    sizing_addendum = (
        "\n\n" + "─" * 72 + "\nSIZING & TARGETS (post-classification)\n" + "─" * 72 + "\n"
        + "\n\n".join(sizing_lines)
    ) if sizing_lines else ""

    paste_block = (
        f"<div style='margin-top:28px;'>"
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"margin-bottom:10px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;'>CLAUDE.AI PASTE BLOCK</div>"
        f"<button id='copy-claude-btn' onclick='copyClaudeContent()'"
        f" style='background:#4f46e5;color:#fff;border:none;border-radius:5px;"
        f"padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;"
        f"letter-spacing:.01em;'>&#128203; Copy for Claude.ai</button>"
        f"</div>"
        f"<div style='background:#18181b;border-radius:6px;padding:20px;"
        f"border:1px solid #27272a;'>"
        f"<pre id='claude-paste-content'"
        f" style='margin:0;font-size:10px;line-height:1.55;color:#d1d5db;"
        f"font-family:\"Menlo\",\"Monaco\",\"Courier New\",monospace;"
        f"white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;'>"
        f"{html.escape(report_text + sizing_addendum)}</pre>"
        f"</div>"
        f"</div>"
    )

    positions_section  = _active_positions_card(open_positions or [], closed_stats, stopped_out_today)
    cluster_section    = _cluster_alerts_card(active_clusters or [])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script>
function copyClaudeContent() {{
  var content = document.getElementById('claude-paste-content').innerText;
  navigator.clipboard.writeText(content).then(function() {{
    var btn = document.getElementById('copy-claude-btn');
    var original = btn.innerHTML;
    btn.innerHTML = '&#10003; Copied';
    setTimeout(function() {{ btn.innerHTML = original; }}, 2000);
  }}).catch(function(err) {{
    console.error('Copy failed:', err);
    alert('Copy failed — please select manually');
  }});
}}
</script>
</head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f1f5f9;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

  <div style="margin-bottom:20px;">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;">Artificial Price Radar</div>
    <div style="font-size:22px;font-weight:700;color:#f1f5f9;">Daily Signals &mdash; {date.strftime('%d %b %Y')}</div>
  </div>

  {positions_section}

  {_macro_card(fear_greed, vix_structure, buffett)}

  {_coverage_card(red_tickers, amber_tickers, len(results))}

  {cluster_section}

  {cards}

  {paste_block}

  <div style="margin-top:20px;font-size:10px;color:#374151;text-align:center;">
    Generated {date.isoformat()} &middot; Artificial Price Radar
  </div>

</div>
</body>
</html>"""


# ── weekly helpers ─────────────────────────────────────────────────────────

def _weekly_macro_card(macro_evolution: dict) -> str:
    """Dark-theme card showing Fear & Greed and Buffett Indicator evolution."""
    fg_start = (macro_evolution.get("fear_greed_start") or {}).get("score")
    fg_end   = (macro_evolution.get("fear_greed_end")   or {}).get("score")
    fg_start_date = (macro_evolution.get("fear_greed_start") or {}).get("date", "")
    fg_end_date   = (macro_evolution.get("fear_greed_end")   or {}).get("date", "")

    if fg_start is not None and fg_end is not None:
        diff = fg_end - fg_start
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
        diff_str = f"{'+' if diff > 0 else ''}{diff}"
        fg_cell = (
            f"<span style='color:{_fg_color(fg_start)};font-weight:700;'>{fg_start}/100</span>"
            f"<span style='color:#64748b;'> ({fg_start_date})</span>"
            f"<span style='color:#475569;'> {arrow} </span>"
            f"<span style='color:{_fg_color(fg_end)};font-weight:700;'>{fg_end}/100</span>"
            f"<span style='color:#64748b;'> ({fg_end_date})</span>"
            f"<span style='color:#64748b;font-size:11px;'> &nbsp;{diff_str}</span>"
        )
    else:
        fg_cell = "<span style='color:#64748b;'>unavailable</span>"

    buf_start_pct = (macro_evolution.get("buffett_start") or {}).get("pct")
    buf_end_pct   = (macro_evolution.get("buffett_end")   or {}).get("pct")
    buf_end_cls   = (macro_evolution.get("buffett_end")   or {}).get("class", "")

    if buf_end_pct is not None:
        bc = _buffett_color(buf_end_cls)
        if buf_start_pct is not None:
            buf_diff = buf_end_pct - buf_start_pct
            diff_span = (
                f"<span style='color:#64748b;font-size:11px;'>"
                f" &nbsp;({'+' if buf_diff >= 0 else ''}{buf_diff:.0f}pp)</span>"
            )
            start_span = f"<span style='color:#94a3b8;'>{buf_start_pct:.0f}%</span> → "
        else:
            diff_span = ""
            start_span = "<span style='color:#64748b;font-size:11px;'>N/A</span> → "
        buf_cell = (
            f"{start_span}"
            f"<span style='color:{bc};font-weight:700;'>{buf_end_pct:.0f}% — {html.escape(buf_end_cls)}</span>"
            f"{diff_span}"
        )
    elif buf_start_pct is not None:
        bc = _buffett_color((macro_evolution.get("buffett_start") or {}).get("class", ""))
        buf_cell = (
            f"<span style='color:{bc};font-weight:700;'>{buf_start_pct:.0f}%</span>"
            f" → <span style='color:#64748b;font-size:11px;'>N/A</span>"
        )
    else:
        buf_cell = "<span style='color:#64748b;'>unavailable</span>"

    rows = [("Fear &amp; Greed", fg_cell), ("Buffett Indicator", buf_cell)]
    trs = "".join(
        f"<tr>"
        f"<td style='color:#94a3b8;padding:4px 14px 4px 0;font-size:12px;white-space:nowrap;vertical-align:middle;'>{label}</td>"
        f"<td style='font-size:13px;padding:4px 0;vertical-align:middle;'>{value}</td>"
        f"</tr>"
        for label, value in rows
    )
    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>MACRO EVOLUTION</div>"
        f"<table style='border-collapse:collapse;width:100%;'><tbody>{trs}</tbody></table>"
        f"</div>"
    )


def _weekly_frequency_table(
    asset_frequency: dict,
    highest_volume: list[dict],
    red_alerts: list[dict],
    amber_alerts: list[dict],
) -> str:
    """Signal frequency table: ticker | days flagged | peak vol | tier."""
    if not asset_frequency:
        return (
            "<div style='background:#1e1e1e;border-radius:6px;padding:14px 20px;"
            "margin-bottom:14px;color:#64748b;font-style:italic;font-size:13px;'>"
            "Nenhum alerta registrado esta semana.</div>"
        )

    red_set = {a["ticker"] for a in red_alerts}
    amber_set = {a["ticker"] for a in amber_alerts}

    vol_by_ticker: dict[str, float] = {}
    for v in highest_volume:
        t = v["ticker"]
        if v["ratio"] > vol_by_ticker.get(t, 0.0):
            vol_by_ticker[t] = v["ratio"]

    header_style = (
        "font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;"
        "letter-spacing:.06em;padding:4px 10px 4px 0;"
    )
    rows_html = (
        f"<tr>"
        f"<th style='{header_style}'>Ativo</th>"
        f"<th style='{header_style}text-align:right;'>Dias</th>"
        f"<th style='{header_style}text-align:right;'>Vol pico</th>"
        f"<th style='{header_style}text-align:right;'>Tier</th>"
        f"</tr>"
    )
    for ticker, days in asset_frequency.items():
        tier = "RED" if ticker in red_set else "AMBER"
        tier_color = "#ef4444" if tier == "RED" else "#f97316"
        peak_vol = vol_by_ticker.get(ticker)
        vol_str = f"{peak_vol:.1f}x" if peak_vol else "—"
        rows_html += (
            f"<tr>"
            f"<td style='font-size:13px;padding:4px 10px 4px 0;font-weight:600;'>{html.escape(ticker)}</td>"
            f"<td style='font-size:13px;padding:4px 10px 4px 0;text-align:right;color:#94a3b8;'>{days}</td>"
            f"<td style='font-size:13px;padding:4px 10px 4px 0;text-align:right;color:#94a3b8;'>{vol_str}</td>"
            f"<td style='font-size:13px;padding:4px 0;text-align:right;'>"
            f"<span style='color:{tier_color};font-weight:700;font-size:10px;'>{tier}</span>"
            f"</td>"
            f"</tr>"
        )

    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>FREQUÊNCIA DE SINAIS</div>"
        f"<table style='border-collapse:collapse;width:100%;'><tbody>{rows_html}</tbody></table>"
        f"</div>"
    )


def _weekly_volume_spikes(highest_volume: list[dict]) -> str:
    """Top 3 volume spikes card."""
    if not highest_volume:
        return ""
    items_html = ""
    for i, v in enumerate(highest_volume[:3], 1):
        items_html += (
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:5px 0;border-bottom:1px solid #2d2d2d;'>"
            f"<span style='font-size:13px;'>"
            f"<span style='color:#94a3b8;margin-right:6px;'>#{i}</span>"
            f"<span style='font-weight:700;'>{html.escape(v['ticker'])}</span>"
            f"<span style='color:#64748b;font-size:11px;margin-left:8px;'>{v['date']}</span>"
            f"</span>"
            f"<span style='color:#ef4444;font-weight:700;font-size:14px;'>{v['ratio']:.1f}x</span>"
            f"</div>"
        )
    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>TOP 3 PICOS DE VOLUME</div>"
        f"{items_html}"
        f"</div>"
    )


def _weekly_dynamic_changes(dynamic_changes: dict) -> str:
    """Promoted/demoted tickers card. Omitted entirely if both lists are empty."""
    promoted = dynamic_changes.get("promoted") or []
    demoted  = dynamic_changes.get("demoted")  or []
    if not promoted and not demoted:
        return ""

    def _badge_list(tickers: list[str], color: str, label: str) -> str:
        if not tickers:
            return ""
        badges = "".join(
            f"<span style='background:{color};color:#fff;font-size:11px;font-weight:700;"
            f"padding:2px 8px;border-radius:3px;margin-right:4px;'>{html.escape(t)}</span>"
            for t in tickers
        )
        return (
            f"<div style='margin-bottom:8px;'>"
            f"<span style='color:#64748b;font-size:11px;margin-right:8px;'>{label}</span>"
            f"{badges}</div>"
        )

    content = _badge_list(promoted, "#22c55e", "Promovidos →") + _badge_list(demoted, "#ef4444", "Removidos →")
    return (
        f"<div style='background:#1e1e1e;border-radius:6px;padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>ALTERAÇÕES DE TICKERS</div>"
        f"{content}"
        f"</div>"
    )


def _weekly_narrative_card(narrative: str) -> str:
    if not narrative:
        return ""
    return (
        f"<div style='background:#1a2035;border-radius:6px;border-left:4px solid #3b82f6;"
        f"padding:16px 20px;margin-bottom:14px;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:10px;'>ANÁLISE SEMANAL</div>"
        f"<div style='font-size:13px;line-height:1.65;color:#cbd5e1;white-space:pre-wrap;'>"
        f"{html.escape(narrative)}"
        f"</div>"
        f"</div>"
    )


def build_weekly_html_email(
    summary: dict,
    narrative: str,
    date: dt.date,
) -> str:
    week_start = summary.get("week_start", "")
    week_end   = summary.get("week_end", date.isoformat())
    days       = summary.get("days_analyzed", 0)
    total      = summary.get("total_signals", 0)
    me         = summary.get("macro_evolution", {})

    macro_card     = _weekly_macro_card(me)
    freq_table     = _weekly_frequency_table(
        summary.get("asset_frequency", {}),
        summary.get("highest_volume", []),
        summary.get("red_alerts", []),
        summary.get("amber_alerts", []),
    )
    vol_card       = _weekly_volume_spikes(summary.get("highest_volume", []))
    dynamic_card   = _weekly_dynamic_changes(summary.get("dynamic_changes", {}))
    narrative_card = _weekly_narrative_card(narrative)

    days_note = f"{days} de 5 dias úteis analisados"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f1f5f9;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

  <div style="margin-bottom:20px;">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;">Artificial Price Radar</div>
    <div style="font-size:22px;font-weight:700;color:#f1f5f9;">Resumo Semanal &mdash; {week_start} a {week_end}</div>
    <div style="font-size:12px;color:#64748b;margin-top:4px;">{days_note} &middot; {total} alertas totais (RED+AMBER)</div>
  </div>

  {macro_card}

  {freq_table}

  {vol_card}

  {dynamic_card}

  {narrative_card}

  <div style="margin-top:20px;font-size:10px;color:#374151;text-align:center;">
    Gerado em {date.isoformat()} &middot; Artificial Price Radar
  </div>

</div>
</body>
</html>"""


# ── public entry point ─────────────────────────────────────────────────────

def send_weekly_report(
    summary: dict,
    narrative: str,
    date: dt.date,
) -> None:
    """Send the weekly summary as a standalone HTML email.

    Subject: [Radar] Weekly Summary — Week of {monday_date}
    Raises EmailConfigError if SMTP credentials are absent.
    """
    sender, password, recipient = _load_config()

    week_start = summary.get("week_start", date.isoformat())
    html_body = build_weekly_html_email(summary=summary, narrative=narrative, date=date)

    plain = (
        f"[Radar] Resumo Semanal — {week_start} a {summary.get('week_end', date.isoformat())}\n\n"
        f"Dias analisados: {summary.get('days_analyzed', 0)}\n"
        f"Total de alertas: {summary.get('total_signals', 0)}\n\n"
        f"Ativos mais frequentes:\n"
        + "\n".join(
            f"  {t}: {d}d" for t, d in (summary.get("asset_frequency") or {}).items()
        )
        + ("\n\n" + narrative if narrative else "")
    )

    msg = EmailMessage()
    msg["Subject"] = f"[Radar] Weekly Summary — Week of {week_start}"
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    logger.info(f"sending weekly report (week of {week_start}) to {recipient}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(msg)
    logger.info("weekly report email sent")


def send_report(
    report_path: str | None = None,
    date: dt.date | None = None,
    output_dir: str = OUTPUT_DIR,
    results: list[dict] | None = None,
    fear_greed: dict | None = None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
    open_positions: list[dict] | None = None,
    closed_stats: dict | None = None,
    active_clusters: list[dict] | None = None,
    classified_signals: list[dict] | None = None,
    stopped_out_today: list[dict] | None = None,
) -> None:
    """Send the Tier-1 digest email (mobile-first, one-screen summary).

    The full HTML report is published separately to GitHub Pages by
    pages_publisher.publish_report() before this function is called.

    Raises FileNotFoundError if the .txt report file is missing,
    EmailConfigError if SMTP credentials are absent.
    """
    from delivery.digest_builder import build_digest_html, build_digest_subject

    date = date or dt.date.today()
    path = report_path or os.path.join(output_dir, f"daily_report_{date.isoformat()}.txt")

    if not os.path.isfile(path):
        raise FileNotFoundError(f"report not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        body = f.read()

    sender, password, recipient = _load_config()

    n_actionable = sum(
        1 for s in (classified_signals or [])
        if s.get("recommendation") in ("contrarian_buy", "reduce_exposure")
    )
    subject = build_digest_subject(n_actionable, date)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.set_content(body)

    if results is not None:
        digest_html = build_digest_html(
            results=results,
            date=date,
            fear_greed=fear_greed,
            vix_structure=vix_structure,
            buffett=buffett,
            open_positions=open_positions,
            classified_signals=classified_signals,
            active_clusters=active_clusters,
            stopped_out_today=stopped_out_today,
        )
        msg.add_alternative(digest_html, subtype="html")

    logger.info("sending digest to %s via %s:%d", recipient, SMTP_HOST, SMTP_PORT)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(msg)
    logger.info("email sent")


def send_backtest_report(html_path: str, period_name: str) -> None:
    """Send a historical backtest HTML report via email.

    Subject: [Radar] Historical Backtest — {period_name}
    Raises FileNotFoundError if the HTML file is missing,
    EmailConfigError if SMTP credentials are absent.
    """
    if not os.path.isfile(html_path):
        raise FileNotFoundError(f"backtest report not found: {html_path}")

    with open(html_path, "r", encoding="utf-8") as fh:
        html_body = fh.read()

    sender, password, recipient = _load_config()

    plain = (
        f"[Radar] Historical Backtest — {period_name}\n\n"
        f"Full HTML report attached. Open in a web browser for best results.\n"
        f"Report path: {html_path}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = f"[Radar] Historical Backtest — {period_name}"
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    logger.info("sending backtest report '%s' to %s", period_name, recipient)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(msg)
    logger.info("backtest report email sent")
