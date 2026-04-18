"""Gmail SMTP delivery for the daily report.

Reads output/daily_report_YYYY-MM-DD.txt and sends it as a plain-text
email. Credentials come from environment variables (see .env.example):

    GMAIL_ADDRESS       the sending account
    GMAIL_APP_PASSWORD  an App Password (NOT the Google account password)
    EMAIL_RECIPIENT     who receives the report (usually the same address)

Gmail requires an App Password when 2FA is on:
    https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import smtplib
from email.message import EmailMessage

from output.document_builder import OUTPUT_DIR

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class EmailConfigError(RuntimeError):
    """Missing or invalid email configuration."""


def _load_config() -> tuple[str, str, str]:
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT")
    missing = [
        k for k, v in (
            ("GMAIL_ADDRESS", sender),
            ("GMAIL_APP_PASSWORD", password),
            ("EMAIL_RECIPIENT", recipient),
        ) if not v
    ]
    if missing:
        raise EmailConfigError(
            f"missing env vars: {', '.join(missing)} — see .env.example"
        )
    return sender, password, recipient


def _resolve_report_path(date: dt.date, output_dir: str) -> str:
    return os.path.join(output_dir, f"daily_report_{date.isoformat()}.txt")


def send_report(
    report_path: str | None = None,
    date: dt.date | None = None,
    output_dir: str = OUTPUT_DIR,
) -> None:
    """Send the daily report file as a plain-text email.

    If `report_path` is None, looks for output/daily_report_<date>.txt.
    `date` defaults to today. Raises FileNotFoundError if the report
    file doesn't exist, EmailConfigError if env vars are missing.
    """
    date = date or dt.date.today()
    path = report_path or _resolve_report_path(date, output_dir)

    if not os.path.isfile(path):
        raise FileNotFoundError(f"report not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        body = f.read()

    sender, password, recipient = _load_config()

    msg = EmailMessage()
    msg["Subject"] = f"[Radar] Artificial Price Signals — {date.isoformat()}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    logger.info(f"sending {path} to {recipient} via {SMTP_HOST}:{SMTP_PORT}")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender, password)
        smtp.send_message(msg)
    logger.info("email sent")
