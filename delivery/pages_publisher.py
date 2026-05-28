"""Publish daily full-report HTML to docs/ for GitHub Pages.

Writes:
  docs/reports/YYYY-MM-DD.html  — full email HTML (reuses build_html_email)
  docs/index.html               — newest-first index, last MAX_DAYS days

GitHub Pages must be configured to serve from /docs on the main branch
(Settings → Pages → Source: Deploy from a branch → main /docs).
The public URL base is https://nafomatos.github.io/Assistente-virtual.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import logging
import os

logger = logging.getLogger(__name__)

PAGES_BASE_URL = "https://nafomatos.github.io/Assistente-virtual"
REPORTS_SUBDIR = "reports"
MAX_DAYS = 90


def publish_report(
    date: dt.date,
    results: list[dict],
    fear_greed: dict | None,
    vix_structure: dict | None,
    buffett: dict | None,
    report_text: str,
    open_positions: list[dict] | None = None,
    closed_stats: dict | None = None,
    active_clusters: list[dict] | None = None,
    stopped_out_today: list[dict] | None = None,
    docs_dir: str = "docs",
) -> str:
    """Write the full-report HTML to docs/reports/ and refresh docs/index.html.

    Returns the public URL of the published report.
    Never raises — logs warnings on any failure.
    """
    from delivery.email_sender import build_html_email

    reports_dir = os.path.join(docs_dir, REPORTS_SUBDIR)
    os.makedirs(reports_dir, exist_ok=True)

    report_filename = f"{date.isoformat()}.html"
    report_path     = os.path.join(reports_dir, report_filename)

    try:
        full_html = build_html_email(
            results=results,
            date=date,
            fear_greed=fear_greed,
            vix_structure=vix_structure,
            buffett=buffett,
            open_positions=open_positions,
            closed_stats=closed_stats,
            active_clusters=active_clusters,
            stopped_out_today=stopped_out_today,
        )
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(full_html)
        logger.info("pages_publisher: wrote %s", report_path)
    except Exception as exc:
        logger.warning("pages_publisher: failed to write report HTML — %s", exc)

    try:
        _rebuild_index(docs_dir, reports_dir)
    except Exception as exc:
        logger.warning("pages_publisher: failed to rebuild index — %s", exc)

    return f"{PAGES_BASE_URL}/{REPORTS_SUBDIR}/{report_filename}"


def _rebuild_index(docs_dir: str, reports_dir: str) -> None:
    """Rewrite docs/index.html with a newest-first list of the last MAX_DAYS reports."""
    cutoff = dt.date.today() - dt.timedelta(days=MAX_DAYS)

    entries: list[tuple[dt.date, str]] = []
    try:
        for name in os.listdir(reports_dir):
            if not name.endswith(".html"):
                continue
            stem = name[:-5]
            try:
                d = dt.date.fromisoformat(stem)
            except ValueError:
                continue
            if d >= cutoff:
                entries.append((d, name))
    except OSError:
        pass

    entries.sort(reverse=True)

    if entries:
        rows = "".join(
            f"<li style='padding:8px 0;border-bottom:1px solid #27272a;'>"
            f"<a href='{REPORTS_SUBDIR}/{html_lib.escape(fname)}'"
            f" style='color:#60a5fa;text-decoration:none;font-size:14px;'>"
            f"{d.strftime('%A, %d %b %Y')}</a>"
            f"</li>"
            for d, fname in entries
        )
    else:
        rows = (
            "<li style='color:#64748b;font-size:13px;padding:8px 0;'>"
            "No reports in the last 90 days.</li>"
        )

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Artificial Price Radar — Reports</title>
</head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f1f5f9;">
<div style="max-width:600px;margin:0 auto;padding:32px 16px;">

  <div style="margin-bottom:24px;">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;">Artificial Price Radar</div>
    <div style="font-size:24px;font-weight:700;">Daily Reports</div>
    <div style="font-size:13px;color:#64748b;margin-top:4px;">Last {MAX_DAYS} days</div>
  </div>

  <ul style="list-style:none;padding:0;margin:0;">
    {rows}
  </ul>

  <div style="margin-top:28px;font-size:11px;color:#374151;">
    Artificial Price Radar &middot; Auto-generated daily
  </div>

</div>
</body>
</html>"""

    index_path = os.path.join(docs_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(index_html)
    logger.info("pages_publisher: updated %s (%d entries)", index_path, len(entries))
