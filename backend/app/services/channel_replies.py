"""Inbound replies arriving on messaging channels (WhatsApp/Telegram) -> the right inbox thread."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChannelAddress,
    Conversation,
    NotificationDelivery,
    NotificationEvent,
    User,
)
from app.services import inbox, notifications

CODE_RE = re.compile(r"^\s*#?([0-9A-Fa-f]{4})\b[\s:,-]*(.*)$", re.S)


async def user_for_address(
    db: AsyncSession, channel: str, address: str
) -> tuple[User, ChannelAddress] | None:
    digits = "".join(c for c in address if c.isdigit())
    rows = (
        await db.execute(select(ChannelAddress).where(ChannelAddress.channel == channel))
    ).scalars()
    for r in rows:
        if "".join(c for c in r.address if c.isdigit()) == digits and digits:
            u = await db.get(User, r.user_id)
            if u:
                return u, r
    return None


async def _conversation_from_context(
    db: AsyncSession, user_id: uuid.UUID, context_id: str | None, code: str | None
) -> Conversation | None:
    ev: NotificationEvent | None = None
    if context_id:
        d = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.user_id == user_id,
                        NotificationDelivery.provider_id == context_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if d:
            ev = await db.get(NotificationEvent, d.event_id)
    if ev is None and code:
        evs = (
            await db.execute(
                select(NotificationEvent)
                .where(NotificationEvent.user_id == user_id)
                .order_by(NotificationEvent.created_at.desc())
                .limit(200)
            )
        ).scalars()
        ev = next((e for e in evs if e.data.get("reply_code", "").upper() == code.upper()), None)
    cid = ev.data.get("conversation_id") if ev else None
    return await db.get(Conversation, uuid.UUID(cid)) if cid else None


async def handle_inbound_text(
    db: AsyncSession, channel: str, sender: str, text: str, context_id: str | None = None
) -> str:
    """Returns a short status string (used in tests/logs): opted_out | opted_in | replied | unmatched | unknown_sender."""
    found = await user_for_address(db, channel, sender)
    if found is None:
        return "unknown_sender"
    user, addr = found
    word = text.strip().lower()
    if word in ("stop", "unsubscribe", "cancel", "end", "quit"):
        addr.opted_in = False
        return "opted_out"
    if word in ("start", "unstop", "subscribe"):
        addr.opted_in = True
        return "opted_in"
    code = None
    body = text.strip()
    if m := CODE_RE.match(text):
        code, body = m.group(1), m.group(2).strip()
    conv = await _conversation_from_context(db, user.id, context_id, code)
    if conv is None or not body:
        await notifications.emit(db, user.id, "sync_failure", "Could not route your WhatsApp reply",
                                 body="Reply directly to a notification, or start with its code, e.g. 'A7F2 Thanks!'", url="/inbox")  # fmt: skip
        return "unmatched"
    delivery = "sent" if conv.platform == "direct" else "pending_manual"
    msg, _ = await inbox.add_outbound(
        db,
        conv,
        body,
        delivery=delivery,
        idempotency_key=f"{channel}:{context_id or code}:{hash_text(body)}",
    )
    if delivery == "pending_manual":
        await notifications.emit(
            db, user.id, "new_message", f"Reply saved for {conv.subject or conv.platform}",
            body="This platform has no messaging API - open the thread and paste your reply there.",
            url=f"/inbox?c={conv.id}", dedupe_key=f"chanreply:{msg.id}", data={"conversation_id": str(conv.id)},
        )  # fmt: skip
    return "replied"


def hash_text(s: str) -> str:
    import hashlib

    return hashlib.sha1(s.encode()).hexdigest()[:10]
