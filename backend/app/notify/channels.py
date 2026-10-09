"""Channel providers. Each `send` raises ChannelError(retryable=...) on failure and returns a provider message id."""

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.services.email import send_email


class ChannelError(Exception):
    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Message:
    title: str
    body: str
    url: str = ""
    code: str = ""  # short reply code, e.g. "A7"
    data: dict[str, Any] | None = None


class Channel(Protocol):
    name: str

    def configured(self) -> bool: ...

    async def send(self, target: Any, msg: Message) -> str: ...


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code >= 500 or r.status_code == 429:
        raise ChannelError(f"{what}: HTTP {r.status_code}", retryable=True)
    if r.status_code >= 400:
        raise ChannelError(f"{what}: HTTP {r.status_code} {r.text[:200]}", retryable=False)


class EmailChannel:
    name = "email"

    def configured(self) -> bool:
        return True

    async def send(self, target: str, msg: Message) -> str:
        link = f"\n\n{msg.url}" if msg.url.startswith("http") else ""
        await send_email(target, msg.title, f"{msg.body}{link}")
        return "smtp"


class ExpoPushChannel:
    """Expo push service: fans out to FCM (Android) / APNs (iOS) for the mobile app."""

    name = "push_expo"

    def configured(self) -> bool:
        return True

    async def send(self, target: list[str], msg: Message) -> str:
        s = get_settings()
        headers = {"Authorization": f"Bearer {s.expo_access_token}"} if s.expo_access_token else {}
        payload = [
            {"to": t, "title": msg.title, "body": msg.body[:300], "data": {"url": msg.url, **(msg.data or {})}, "sound": "default"}
            for t in target
        ]  # fmt: skip
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://exp.host/--/api/v2/push/send", json=payload, headers=headers)
        _check(r, "Expo push")
        return "expo"


class WebPushChannel:
    name = "push_web"

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.vapid_private_key and s.vapid_public_key)

    async def send(self, target: list[str], msg: Message) -> str:
        try:
            from pywebpush import WebPushException, webpush  # optional dependency
        except ImportError:
            raise ChannelError("pywebpush is not installed", retryable=False) from None
        import asyncio

        s = get_settings()
        payload = json.dumps({"title": msg.title, "body": msg.body[:300], "url": msg.url})
        errors = 0
        for sub in target:
            try:
                await asyncio.to_thread(
                    webpush, subscription_info=json.loads(sub), data=payload,
                    vapid_private_key=s.vapid_private_key, vapid_claims={"sub": s.vapid_subject},
                )  # fmt: skip
            except WebPushException:
                errors += 1
        if errors == len(target):
            raise ChannelError("web push failed for all subscriptions")
        return "webpush"


class WhatsAppChannel:
    """Meta WhatsApp Cloud API. Business-initiated messages must use an approved template."""

    name = "whatsapp"

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.whatsapp_token and s.whatsapp_phone_number_id)

    async def send(self, target: str, msg: Message) -> str:
        s = get_settings()
        params = [msg.title[:60], msg.body[:900].replace("\n", " "), msg.code or "-"]
        payload = {
            "messaging_product": "whatsapp",
            "to": target.lstrip("+"),
            "type": "template",
            "template": {
                "name": s.whatsapp_template,
                "language": {"code": s.whatsapp_template_lang},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}],
            },
        }  # fmt: skip
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"https://graph.facebook.com/v20.0/{s.whatsapp_phone_number_id}/messages",
                json=payload,
                headers={"Authorization": f"Bearer {s.whatsapp_token}"},
            )
        _check(r, "WhatsApp")
        return str((r.json().get("messages") or [{}])[0].get("id", ""))


class SmsChannel:
    name = "sms"

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from)

    async def send(self, target: str, msg: Message) -> str:
        s = get_settings()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                data={
                    "To": target,
                    "From": s.twilio_from,
                    "Body": f"{msg.title}: {msg.body}"[:300],
                },
                auth=(s.twilio_account_sid, s.twilio_auth_token),
            )
        _check(r, "Twilio")
        return str(r.json().get("sid", ""))


class TelegramChannel:
    name = "telegram"

    def configured(self) -> bool:
        return bool(get_settings().telegram_bot_token)

    async def send(self, target: str, msg: Message) -> str:
        s = get_settings()
        link = f"\n{msg.url}" if msg.url.startswith("http") else ""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": target,
                    "text": f"*{msg.title}*\n{msg.body}{link}",
                    "parse_mode": "Markdown",
                },
            )
        _check(r, "Telegram")
        return str(r.json().get("result", {}).get("message_id", ""))


CHANNELS: dict[str, Channel] = {
    c.name: c for c in (EmailChannel(), ExpoPushChannel(), WebPushChannel(), WhatsAppChannel(), SmsChannel(), TelegramChannel())  # type: ignore[misc]
}  # fmt: skip
USER_CHANNELS = ["in_app", "push", "email", "whatsapp", "sms", "telegram"]
