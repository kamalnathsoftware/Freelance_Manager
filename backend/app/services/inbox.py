"""Unified inbox: conversations/messages, response-time tracking, SLA, client resolution."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime import hub
from app.core.security import hash_token
from app.models import (
    Client,
    ClientIdentity,
    Conversation,
    ConvStatus,
    Message,
    PlatformAccount,
    User,
)

DEFAULT_SLA_MINUTES = 20


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def resolve_client(
    db: AsyncSession,
    user_id: uuid.UUID,
    platform: str,
    handle: str,
    name: str = "",
    email: str = "",
) -> Client:
    """Find the client for a platform handle, creating the client + identity on first sight."""
    handle = handle.strip().lower() or name.strip().lower()
    ident = (
        await db.execute(
            select(ClientIdentity).where(
                ClientIdentity.user_id == user_id,
                ClientIdentity.platform == platform,
                ClientIdentity.handle == handle,
            )
        )
    ).scalar_one_or_none()
    if ident is not None:
        client = await db.get(Client, ident.client_id)
        assert client is not None
        return client
    client = Client(user_id=user_id, name=name or handle, email=email)
    db.add(client)
    await db.flush()
    db.add(ClientIdentity(user_id=user_id, client_id=client.id, platform=platform, handle=handle))
    await db.flush()
    return client


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    platform: str,
    thread_key: str,
    *,
    subject: str = "",
    client: Client | None = None,
    platform_url: str = "",
) -> tuple[Conversation, bool]:
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.platform == platform,
                Conversation.thread_key == thread_key,
            )
        )
    ).scalar_one_or_none()
    if conv is not None:
        return conv, False
    acc = (
        await db.execute(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user_id, PlatformAccount.platform == platform)
            .limit(1)
        )
    ).scalar_one_or_none()
    conv = Conversation(
        user_id=user_id, platform=platform, thread_key=thread_key[:300], subject=subject[:300],
        client_id=client.id if client else None, account_id=acc.id if acc else None, platform_url=platform_url,
    )  # fmt: skip
    db.add(conv)
    await db.flush()
    return conv, True


async def add_inbound(
    db: AsyncSession,
    conv: Conversation,
    body: str,
    sender: str = "",
    source: str = "email",
    external_key: str | None = None,
) -> Message | None:
    """Append a client message. Idempotent on `external_key`. Reopens snoozed/archived threads."""
    if external_key:
        dup = (
            await db.execute(
                select(Message.id).where(
                    Message.conversation_id == conv.id, Message.idempotency_key == external_key
                )
            )
        ).first()
        if dup:
            return None
    msg = Message(
        conversation_id=conv.id,
        direction="in",
        sender_name=sender,
        body=body,
        source=source,
        idempotency_key=external_key,
    )
    db.add(msg)
    now = datetime.now(UTC)
    conv.last_message_at, conv.last_preview = now, body[:300]
    conv.unread_count += 1
    conv.awaiting_reply_since = conv.awaiting_reply_since or now
    if conv.status != ConvStatus.open:
        conv.status, conv.snoozed_until = ConvStatus.open, None
    await db.flush()
    hub.publish(
        conv.user_id,
        "message.new",
        {
            "conversation_id": str(conv.id),
            "message_id": str(msg.id),
            "platform": conv.platform,
            "preview": body[:120],
        },
    )
    return msg


async def add_outbound(
    db: AsyncSession,
    conv: Conversation,
    body: str,
    *,
    delivery: str,
    ai_generated: bool = False,
    idempotency_key: str | None = None,
) -> tuple[Message, bool]:
    """Record a reply. Returns (message, created). Response time is measured when the reply is sent."""
    if idempotency_key:
        existing = (
            await db.execute(
                select(Message).where(
                    Message.conversation_id == conv.id, Message.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    msg = Message(
        conversation_id=conv.id,
        direction="out",
        body=body,
        source="manual",
        delivery=delivery,
        ai_generated=ai_generated,
        idempotency_key=idempotency_key,
    )
    db.add(msg)
    now = datetime.now(UTC)
    conv.last_message_at, conv.last_preview = now, body[:300]
    conv.unread_count = 0
    if delivery == "sent":
        _stamp_response(conv, msg, now)
    await db.flush()
    hub.publish(conv.user_id, "conversation.updated", {"conversation_id": str(conv.id)})
    return msg, True


def _stamp_response(conv: Conversation, msg: Message, now: datetime) -> None:
    if conv.awaiting_reply_since is not None:
        msg.response_seconds = max(0, int((now - aware(conv.awaiting_reply_since)).total_seconds()))
        conv.awaiting_reply_since = None


async def confirm_manual_delivery(db: AsyncSession, conv: Conversation, msg: Message) -> None:
    """User pasted the reply on the platform: now it counts as sent (and stops the SLA clock)."""
    msg.delivery = "sent"
    _stamp_response(conv, msg, datetime.now(UTC))
    await db.flush()
    hub.publish(conv.user_id, "conversation.updated", {"conversation_id": str(conv.id)})


def unsnooze_due(convs: list[Conversation]) -> None:
    now = datetime.now(UTC)
    for c in convs:
        if c.status == ConvStatus.snoozed and c.snoozed_until and aware(c.snoozed_until) <= now:
            c.status, c.snoozed_until = ConvStatus.open, None


def sla_minutes(user: User) -> int:
    try:
        return max(1, int((user.settings or {}).get("sla_minutes", DEFAULT_SLA_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_SLA_MINUTES


async def sla_alerts(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    limit = timedelta(minutes=sla_minutes(user))
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.awaiting_reply_since.is_not(None),
                Conversation.status != ConvStatus.archived,
            )
        )
    ).scalars()
    out = []
    for c in rows:
        waited = now - aware(c.awaiting_reply_since)  # type: ignore[arg-type]
        if waited >= limit:
            vip = False
            if c.client_id:
                cl = await db.get(Client, c.client_id)
                vip = bool(cl and cl.vip)
            out.append({
                "conversation_id": str(c.id), "platform": c.platform, "subject": c.subject,
                "waiting_minutes": int(waited.total_seconds() // 60), "vip": vip,
            })  # fmt: skip
    return sorted(out, key=lambda a: (not a["vip"], -a["waiting_minutes"]))


async def response_stats(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                Conversation.platform, func.count(Message.id), func.avg(Message.response_seconds)
            )
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id, Message.response_seconds.is_not(None))
            .group_by(Conversation.platform)
        )
    ).all()
    return [
        {"platform": p, "replies": n, "avg_response_minutes": round(float(avg) / 60, 1)}
        for p, n, avg in rows
    ]


# ---- chat widget visitors ----
def new_visitor_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(24)
    return raw, hash_token(raw)


def widget_thread_key(visitor_id: str) -> str:
    return "widget:" + hashlib.sha1(visitor_id.encode()).hexdigest()[:24]
