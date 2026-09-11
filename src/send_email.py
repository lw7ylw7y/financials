"""Thin Gmail SMTP wrapper for post-release emails (Story 4)."""

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class EmailSendError(Exception):
    """Raised for any failure to send a post-release email."""


def send_email(
    subject: str,
    body: str,
    to_addr: str | None = None,
    from_addr: str | None = None,
    app_password: str | None = None,
) -> None:
    """Send a plain-text email via Gmail SMTP.

    Credentials default to the GMAIL_ADDRESS / GMAIL_APP_PASSWORD /
    RECIPIENT_EMAIL env vars (per Section 9 of v1_technical_design.md)
    when not passed explicitly.
    """
    from_addr = from_addr or os.environ.get("GMAIL_ADDRESS")
    app_password = app_password or os.environ.get("GMAIL_APP_PASSWORD")
    to_addr = to_addr or os.environ.get("RECIPIENT_EMAIL")

    missing = [
        name
        for name, value in (
            ("GMAIL_ADDRESS", from_addr),
            ("GMAIL_APP_PASSWORD", app_password),
            ("RECIPIENT_EMAIL", to_addr),
        )
        if not value
    ]
    if missing:
        raise EmailSendError(f"missing required config: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(from_addr, app_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailSendError(f"failed to send email: {e}") from e
