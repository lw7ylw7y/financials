"""Thin Gmail SMTP wrapper for post-release emails."""

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
    html_body: str | None = None,
    images: dict[str, bytes] | None = None,
    to_addr: str | None = None,
    from_addr: str | None = None,
    app_password: str | None = None,
) -> None:
    """Send an email via Gmail SMTP.

    Plain-text only if `html_body` is omitted. When given, sends
    multipart/alternative with `body` as the plain-text fallback (for
    clients that don't render HTML) and `html_body` as the preferred
    part. `images` (cid -> PNG bytes) are attached as inline parts
    related to the HTML body, referenced there as `<img src="cid:...">`
    — ignored if `html_body` is None, since there's no HTML to embed
    them in.

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
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
        if images:
            html_part = message.get_payload()[-1]
            for cid, png_bytes in images.items():
                html_part.add_related(
                    png_bytes, maintype="image", subtype="png", cid=f"<{cid}>"
                )

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(from_addr, app_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailSendError(f"failed to send email: {e}") from e
