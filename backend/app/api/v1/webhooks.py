import hashlib
import hmac
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from sqlalchemy import select

from app.api.deps import DB
from app.core.config import get_settings
from app.models import ChannelAddress, NotificationDelivery, NotificationEvent, User
from app.services import channel_replies, notifications

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    s = get_settings()
    if (
        mode == "subscribe"
        and s.whatsapp_verify_token
        and secrets.compare_digest(token, s.whatsapp_verify_token)
    ):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@router.post("/whatsapp")
async def whatsapp_inbound(
    request: Request, db: DB, x_hub_signature_256: str = Header(default="")
) -> dict[str, str]:
    """Meta Cloud API webhook. Requires WHATSAPP_APP_SECRET; every request must carry a valid signature."""
    secret = get_settings().whatsapp_app_secret
    if not secret:
        raise HTTPException(503, "WhatsApp webhook is not configured")
    raw = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(403, "Invalid signature")
    payload: dict[str, Any] = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for st in value.get("statuses", []):
                if st.get("status") == "failed":
                    d = (
                        (
                            await db.execute(
                                select(NotificationDelivery).where(
                                    NotificationDelivery.provider_id == st.get("id", "")
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if d is not None and d.status == "sent":
                        d.status, d.error = "failed", "WhatsApp reported delivery failure"
                        ev_user = await db.get(User, d.user_id)
                        ev = await db.get(NotificationEvent, d.event_id)
                        if ev_user and ev:
                            await notifications._fallback(db, d, ev, ev_user)
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    await channel_replies.handle_inbound_text(
                        db,
                        "whatsapp",
                        m.get("from", ""),
                        m.get("text", {}).get("body", ""),
                        (m.get("context") or {}).get("id"),
                    )
    await db.commit()
    return {"status": "ok"}


@router.post("/telegram")
async def telegram_inbound(
    request: Request, db: DB, x_telegram_bot_api_secret_token: str = Header(default="")
) -> dict[str, str]:
    s = get_settings()
    if not s.telegram_webhook_secret:
        raise HTTPException(503, "Telegram webhook is not configured")
    if not secrets.compare_digest(x_telegram_bot_api_secret_token, s.telegram_webhook_secret):
        raise HTTPException(403, "Invalid secret")
    upd: dict[str, Any] = await request.json()
    msg = upd.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    if text.startswith("/start ") and chat_id:
        code = text.split(maxsplit=1)[1].strip()
        row = (
            await db.execute(
                select(ChannelAddress).where(
                    ChannelAddress.channel == "telegram", ChannelAddress.link_code == code
                )
            )
        ).scalar_one_or_none()
        if row is not None and code:
            row.address, row.opted_in, row.link_code = chat_id, True, ""
    elif text and chat_id:
        found = (
            await db.execute(
                select(ChannelAddress).where(
                    ChannelAddress.channel == "telegram", ChannelAddress.address == chat_id
                )
            )
        ).scalar_one_or_none()
        if found is not None:
            await channel_replies.handle_inbound_text(db, "telegram", chat_id, text)
    await db.commit()
    return {"status": "ok"}
