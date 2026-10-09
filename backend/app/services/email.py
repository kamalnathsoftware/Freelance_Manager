import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger(__name__)

# Captured messages when environment == "test" (used by the test-suite).
OUTBOX: list[dict[str, str]] = []


def _send_sync(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> None:
    if get_settings().environment == "test":
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        return
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
    except Exception:  # delivery must never break the request
        log.exception("email delivery failed to=%s", to)
