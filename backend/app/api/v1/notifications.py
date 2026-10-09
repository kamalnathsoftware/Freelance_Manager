import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.models import (
    ChannelAddress,
    DeviceToken,
    NotificationDelivery,
    NotificationEvent,
    NotificationPreference,
)
from app.schemas import ORM, Message
from app.services import notifications as svc
from app.services.common import get_owned

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotifOut(ORM):
    id: uuid.UUID
    type: str
    title: str
    body: str
    url: str
    priority: str
    read_at: datetime | None
    created_at: datetime


class DeliveryOut(ORM):
    id: uuid.UUID
    event_id: uuid.UUID
    channel: str
    status: str
    attempts: int
    error: str
    mode: str
    next_attempt_at: datetime | None
    fallback_of: uuid.UUID | None
    sent_at: datetime | None
    created_at: datetime
    event_title: str = ""


class PrefUpdate(BaseModel):
    matrix: dict[str, dict[str, dict[str, Any]]] = {}  # {event_type: {channel: {enabled, mode}}}
    quiet_start: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    quiet_end: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    digest_hour: int | None = Field(default=None, ge=0, le=23)
    fallback: dict[str, str] | None = None


class ChannelIn(BaseModel):
    channel: str = Field(pattern="^(email|whatsapp|sms|telegram)$")
    address: str = Field(default="", max_length=200)
    opted_in: bool = False


class DeviceIn(BaseModel):
    kind: str = Field(pattern="^(expo|webpush)$")
    token: str = Field(min_length=5)
    label: str = ""


@router.get("")
async def list_notifications(
    user: CurrentUser,
    db: DB,
    unread: bool = False,
    type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(NotificationEvent).where(NotificationEvent.user_id == user.id)
    if unread:
        stmt = stmt.where(NotificationEvent.read_at.is_(None))
    if type:
        stmt = stmt.where(NotificationEvent.type == type)
    rows = (
        await db.execute(
            stmt.order_by(NotificationEvent.created_at.desc()).limit(min(limit, 200)).offset(offset)
        )
    ).scalars()
    unread_n = (
        await db.execute(
            select(func.count(NotificationEvent.id)).where(
                NotificationEvent.user_id == user.id, NotificationEvent.read_at.is_(None)
            )
        )
    ).scalar_one()
    return {
        "items": [NotifOut.model_validate(r).model_dump(mode="json") for r in rows],
        "unread": unread_n,
    }


@router.post("/read-all", response_model=Message)
async def read_all(user: CurrentUser, db: DB) -> Message:
    rows = (
        await db.execute(
            select(NotificationEvent).where(
                NotificationEvent.user_id == user.id, NotificationEvent.read_at.is_(None)
            )
        )
    ).scalars()
    for r in rows:
        r.read_at = datetime.now(UTC)
    await db.commit()
    return Message(detail="All read")


@router.post("/{nid}/read", response_model=NotifOut)
async def mark_read(nid: uuid.UUID, user: CurrentUser, db: DB) -> NotificationEvent:
    ev = await get_owned(db, NotificationEvent, nid, user.id)
    ev.read_at = ev.read_at or datetime.now(UTC)
    await db.commit()
    return ev


@router.get("/deliveries", response_model=list[DeliveryOut])
async def delivery_log(
    user: CurrentUser,
    db: DB,
    status: str | None = None,
    channel: str | None = None,
    limit: int = 100,
) -> list[DeliveryOut]:
    stmt = (
        select(NotificationDelivery, NotificationEvent.title)
        .join(NotificationEvent, NotificationEvent.id == NotificationDelivery.event_id)
        .where(NotificationDelivery.user_id == user.id)
    )
    if status:
        stmt = stmt.where(NotificationDelivery.status == status)
    if channel:
        stmt = stmt.where(NotificationDelivery.channel == channel)
    out = []
    for d, title in (
        await db.execute(
            stmt.order_by(NotificationDelivery.created_at.desc()).limit(min(limit, 500))
        )
    ).all():
        o = DeliveryOut.model_validate(d)
        o.event_title = title
        out.append(o)
    return out


@router.post("/deliveries/{did}/retry", response_model=DeliveryOut)
async def retry(did: uuid.UUID, user: CurrentUser, db: DB) -> DeliveryOut:
    d = await get_owned(db, NotificationDelivery, did, user.id)
    if d.status not in ("failed", "skipped"):
        raise HTTPException(409, "Only failed or skipped deliveries can be retried")
    d.status, d.attempts = "pending", 0
    await svc.attempt(db, d)
    await db.commit()
    return DeliveryOut.model_validate(d)


@router.get("/preferences")
async def get_preferences(user: CurrentUser, db: DB) -> dict[str, Any]:
    matrix: dict[str, dict[str, dict[str, Any]]] = {}
    for t in svc.EVENT_TYPES:
        matrix[t] = {}
        for ch in svc.CHANNEL_NAMES:
            enabled, mode = await svc.preference(db, user.id, t, ch)
            matrix[t][ch] = {"enabled": enabled, "mode": mode}
    return {
        "event_types": [{"type": k, "label": v} for k, v in svc.EVENT_TYPES.items()],
        "channels": svc.CHANNEL_NAMES,
        "matrix": matrix,
        "settings": svc.settings_of(user),
    }


@router.put("/preferences")
async def put_preferences(body: PrefUpdate, user: CurrentUser, db: DB) -> dict[str, Any]:
    for t, chans in body.matrix.items():
        if t not in svc.EVENT_TYPES:
            raise HTTPException(422, f"Unknown event type {t}")
        for ch, v in chans.items():
            if ch not in svc.CHANNEL_NAMES:
                raise HTTPException(422, f"Unknown channel {ch}")
            mode = v.get("mode", "instant")
            if mode not in ("instant", "hourly", "daily"):
                raise HTTPException(422, "mode must be instant, hourly or daily")
            row = (
                await db.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id == user.id,
                        NotificationPreference.event_type == t,
                        NotificationPreference.channel == ch,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = NotificationPreference(user_id=user.id, event_type=t, channel=ch)
                db.add(row)
            row.enabled, row.mode = bool(v.get("enabled", True)), mode
    cur = dict((user.settings or {}).get("notif", {}))
    for k in ("quiet_start", "quiet_end", "digest_hour", "fallback"):
        v = getattr(body, k)
        if v is not None:
            cur[k] = v
    user.settings = {**(user.settings or {}), "notif": cur}
    await db.commit()
    return await get_preferences(user, db)


@router.get("/channels")
async def list_channels(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = {
        r.channel: r
        for r in (
            await db.execute(select(ChannelAddress).where(ChannelAddress.user_id == user.id))
        ).scalars()
    }
    s = get_settings()
    cfg = {
        "email": True,
        "whatsapp": bool(s.whatsapp_token),
        "sms": bool(s.twilio_account_sid),
        "telegram": bool(s.telegram_bot_token),
    }
    return [
        {"channel": c, "address": (rows[c].address if c in rows else user.email if c == "email" else ""),
         "opted_in": (rows[c].opted_in if c in rows else c == "email"), "server_configured": cfg[c]}
        for c in ("email", "whatsapp", "sms", "telegram")
    ]  # fmt: skip


@router.put("/channels", response_model=Message)
async def put_channel(body: ChannelIn, user: CurrentUser, db: DB) -> Message:
    if body.opted_in and not body.address and body.channel != "email":
        raise HTTPException(422, "Provide an address before opting in")
    row = (
        await db.execute(
            select(ChannelAddress).where(
                ChannelAddress.user_id == user.id, ChannelAddress.channel == body.channel
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChannelAddress(user_id=user.id, channel=body.channel)
        db.add(row)
    addr = body.address.strip()
    if body.channel in ("whatsapp", "sms"):
        addr = "+" + "".join(ch for ch in addr if ch.isdigit()) if addr else ""
    row.address, row.opted_in = addr, body.opted_in
    await db.commit()
    return Message(detail="Saved")


@router.post("/channels/telegram/link")
async def telegram_link(user: CurrentUser, db: DB) -> dict[str, str]:
    if not get_settings().telegram_bot_token:
        raise HTTPException(501, "Telegram bot is not configured")
    row = (
        await db.execute(
            select(ChannelAddress).where(
                ChannelAddress.user_id == user.id, ChannelAddress.channel == "telegram"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChannelAddress(user_id=user.id, channel="telegram")
        db.add(row)
    row.link_code = secrets.token_urlsafe(8)
    await db.commit()
    return {
        "code": row.link_code,
        "instructions": f"Open your bot in Telegram and send: /start {row.link_code}",
    }


@router.get("/devices")
async def devices(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    rows = (await db.execute(select(DeviceToken).where(DeviceToken.user_id == user.id))).scalars()
    return [
        {"id": str(r.id), "kind": r.kind, "label": r.label, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.post("/devices", status_code=201)
async def register_device(body: DeviceIn, user: CurrentUser, db: DB) -> dict[str, str]:
    if body.kind == "webpush":
        try:
            if "endpoint" not in json.loads(body.token):
                raise ValueError
        except ValueError:
            raise HTTPException(422, "webpush token must be the JSON push subscription") from None
    existing = (
        await db.execute(select(DeviceToken).where(DeviceToken.token == body.token))
    ).scalar_one_or_none()
    if existing is not None:
        existing.user_id, existing.label = (
            user.id,
            body.label,
        )  # token moved to this account (re-login on same device)
        await db.commit()
        return {"id": str(existing.id)}
    d = DeviceToken(user_id=user.id, **body.model_dump())
    db.add(d)
    await db.commit()
    return {"id": str(d.id)}


@router.delete("/devices/{did}", response_model=Message)
async def remove_device(did: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, DeviceToken, did, user.id))
    await db.commit()
    return Message(detail="Removed")


@router.get("/vapid-key")
async def vapid_key() -> dict[str, str]:
    return {"public_key": get_settings().vapid_public_key}


@router.post("/test")
async def test_notification(user: CurrentUser, db: DB, channel: str = "in_app") -> dict[str, Any]:
    """Send a test notification to one channel, bypassing preferences, so users can verify setup."""
    if channel not in svc.CHANNEL_NAMES:
        raise HTTPException(422, "Unknown channel")
    ev = NotificationEvent(
        user_id=user.id,
        type="sync_failure",
        title="Test notification",
        body="If you can read this, this channel works.",
        url="/settings",
        dedupe_key=f"test:{uuid.uuid4().hex}",
        priority="high",
    )
    db.add(ev)
    await db.flush()
    d = NotificationDelivery(event_id=ev.id, user_id=user.id, channel=channel)
    if channel == "in_app":
        d.status, d.sent_at = "sent", datetime.now(UTC)
        db.add(d)
    else:
        if await svc.address_for(db, user, channel) is None:
            raise HTTPException(
                409, f"No destination for {channel} (missing address, device, or opt-in)"
            )
        db.add(d)
        await db.flush()
        await svc.attempt(db, d, ev, user)
    await db.commit()
    return {"status": d.status, "error": d.error}
