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


# ── asset card ─────────────────────────────────────────────────────────────

def _asset_card(ticker: str, signals: dict, tier: str) -> str:
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

    return (
        f"<div style='background:#1a1a1a;border-radius:6px;border-left:4px solid {border};"
        f"padding:14px 16px;margin-bottom:12px;'>"
        # header
        f"<table style='width:100%;border-collapse:collapse;margin-bottom:10px;'><tbody><tr>"
        f"<td style='vertical-align:middle;'>"
        f"<span style='{label_style}'>{tier.upper()}</span>"
        f"&nbsp;<span style='font-weight:700;font-size:15px;'>{html.escape(ticker)}</span>"
        f"&nbsp;<span style='color:#94a3b8;font-size:12px;'>{html.escape(name)}</span>"
        f"</td>"
        f"<td style='text-align:right;vertical-align:middle;font-size:14px;font-weight:600;white-space:nowrap;'>"
        f"${price:,.2f}&nbsp;<span style='color:{ret_color};'>{ret_sign}{ret:.2f}%</span>"
        f"</td>"
        f"</tr></tbody></table>"
        # metrics
        f"<table style='border-collapse:collapse;'><tbody><tr>{metric_tds}</tr></tbody></table>"
        # news + sentiment
        f"{news_html}"
        f"{sentiment_html}"
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
) -> str:
    red_items   = [(r["ticker"], r["signals"]) for r in results if get_alert_tier(r["signals"]) == "red"]
    amber_items = [(r["ticker"], r["signals"]) for r in results if get_alert_tier(r["signals"]) == "amber"]
    red_tickers   = [t for t, _ in red_items]
    amber_tickers = [t for t, _ in amber_items]

    cards = "".join(_asset_card(t, s, "red")   for t, s in red_items)
    cards += "".join(_asset_card(t, s, "amber") for t, s in amber_items)
    if not cards:
        cards = (
            "<div style='background:#1a1a1a;border-radius:6px;padding:16px;color:#64748b;"
            "font-style:italic;text-align:center;font-size:13px;'>"
            "No alerts today — all tickers within normal ranges."
            "</div>"
        )

    paste_block = (
        f"<div style='background:#18181b;border-radius:6px;padding:20px;"
        f"margin-top:28px;border:1px solid #27272a;'>"
        f"<div style='font-size:10px;font-weight:700;color:#64748b;letter-spacing:.08em;"
        f"text-transform:uppercase;margin-bottom:12px;'>CLAUDE.AI PASTE BLOCK</div>"
        f"<pre style='margin:0;font-size:10px;line-height:1.55;color:#d1d5db;"
        f"font-family:\"Menlo\",\"Monaco\",\"Courier New\",monospace;"
        f"white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;'>"
        f"{html.escape(report_text)}</pre>"
        f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f1f5f9;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

  <div style="margin-bottom:20px;">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;">Artificial Price Radar</div>
    <div style="font-size:22px;font-weight:700;color:#f1f5f9;">Daily Signals &mdash; {date.strftime('%d %b %Y')}</div>
  </div>

  {_macro_card(fear_greed, vix_structure, buffett)}

  {_coverage_card(red_tickers, amber_tickers, len(results))}

  {cards}

  {paste_block}

  <div style="margin-top:20px;font-size:10px;color:#374151;text-align:center;">
    Generated {date.isoformat()} &middot; Artificial Price Radar
  </div>

</div>
</body>
</html>"""


# ── public entry point ─────────────────────────────────────────────────────

def send_report(
    report_path: str | None = None,
    date: dt.date | None = None,
    output_dir: str = OUTPUT_DIR,
    results: list[dict] | None = None,
    fear_greed: dict | None = None,
    vix_structure: dict | None = None,
    buffett: dict | None = None,
) -> None:
    """Send the daily report as a multipart email (HTML + plain-text fallback).

    Pass `results`, `fear_greed`, `vix_structure`, and `buffett` to enable
    the HTML briefing section. Without them the email is plain-text only.
    Raises FileNotFoundError if the report file is missing, EmailConfigError
    if SMTP credentials are absent.
    """
    date = date or dt.date.today()
    path = report_path or os.path.join(output_dir, f"daily_report_{date.isoformat()}.txt")

    if not os.path.isfile(path):
        raise FileNotFoundError(f"report not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        body = f.read()

    sender, password, recipient = _load_config()

    msg = EmailMessage()
    msg["Subject"] = f"[Radar] Price Signals — {date.strftime('%d %b %Y')}"
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.set_content(body)

    if results is not None:
        html_body = build_html_email(
            results=results,
            date=date,
            fear_greed=fear_greed,
            vix_structure=vix_structure,
            buffett=buffett,
            report_text=body,
        )
        msg.add_alternative(html_body, subtype="html")

    logger.info(f"sending {path} to {recipient} via {SMTP_HOST}:{SMTP_PORT}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(msg)
    logger.info("email sent")
