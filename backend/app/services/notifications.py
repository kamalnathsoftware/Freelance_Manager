"""Notification engine: preferences -> deliveries -> channel send, with quiet hours, digests,
retries with backoff, per-channel fallback, de-duplication and delivery logs."""

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime import hub
from app.models import (
    ChannelAddress,
    DeviceToken,
    NotificationDelivery,
    NotificationEvent,
    NotificationPreference,
    User,
)
from app.notify.channels import CHANNELS, ChannelError, Message

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4

EVENT_TYPES: dict[str, str] = {
    "new_message": "New client message",
    "new_order": "New order or offer",
    "order_status": "Order status change",
    "job_match": "New job match",
    "bid_viewed": "Bid viewed",
    "bid_accepted": "Bid accepted",
    "bid_declined": "Bid declined",
    "deadline": "Deadline approaching",
    "revision_requested": "Revision requested",
    "payment_received": "Payment received",
    "review_received": "Review received",
    "sync_failure": "Sync failure",
    "low_credits": "Low credits",
    "sla_breach": "Client waiting too long",
    "follow_up_due": "Proposal follow-up due",
}
CHANNEL_NAMES = ["in_app", "push", "email", "whatsapp", "sms", "telegram"]
# Defaults are conservative: noisy or paid channels (WhatsApp/SMS/Telegram) are opt-in per event.
_DEFAULT_ON: dict[str, set[str]] = {
    "in_app": set(EVENT_TYPES),
    "push": {"new_message", "new_order", "order_status", "bid_accepted", "deadline", "revision_requested", "payment_received", "sla_breach"},
    "email": {"new_order", "bid_accepted", "deadline", "revision_requested", "payment_received", "review_received", "sync_failure", "low_credits"},
    "whatsapp": set(), "sms": set(), "telegram": set(),
}  # fmt: skip
DEFAULT_FALLBACK = {"whatsapp": "email", "sms": "email", "telegram": "email", "push": "email"}

PLATFORM_EVENT_TYPE = {
    "order": "new_order", "offer": "new_order", "order_delivered": "order_status", "revision": "revision_requested",
    "payment": "payment_received", "review": "review_received", "bid_viewed": "bid_viewed", "bid_accepted": "bid_accepted",
    "bid_declined": "bid_declined", "job_match": "job_match", "job_invite": "job_match",
}  # fmt: skip


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def settings_of(user: User) -> dict[str, Any]:
    raw = (user.settings or {}).get("notif", {})
    return {
        "quiet_start": raw.get("quiet_start", ""), "quiet_end": raw.get("quiet_end", ""),
        "digest_hour": int(raw.get("digest_hour", 8)),
        "fallback": {**DEFAULT_FALLBACK, **raw.get("fallback", {})},
    }  # fmt: skip


def _tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _parse_hm(v: str) -> time | None:
    try:
        h, m = v.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def quiet_until(user: User, now: datetime) -> datetime | None:
    """If `now` is inside the user's quiet hours, return when they end (UTC), else None."""
    s = settings_of(user)
    qs, qe = _parse_hm(s["quiet_start"]), _parse_hm(s["quiet_end"])
    if not qs or not qe or qs == qe:
        return None
    local = now.astimezone(_tz(user))
    t = local.time()
    inside = (qs <= t < qe) if qs < qe else (t >= qs or t < qe)
    if not inside:
        return None
    end = local.replace(hour=qe.hour, minute=qe.minute, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)


async def preference(
    db: AsyncSession, user_id: uuid.UUID, etype: str, channel: str
) -> tuple[bool, str]:
    row = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.event_type == etype,
                NotificationPreference.channel == channel,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.enabled, row.mode
    return etype in _DEFAULT_ON.get(channel, set()), "instant"


async def address_for(db: AsyncSession, user: User, channel: str) -> str | list[str] | None:
    if channel == "email":
        row = await _addr(db, user.id, "email")
        return row.address if row and row.address else user.email
    if channel == "push":
        toks = list(
            (await db.execute(select(DeviceToken).where(DeviceToken.user_id == user.id))).scalars()
        )
        return [t.token for t in toks] or None
    row = await _addr(db, user.id, channel)
    if row is None or not row.address:
        return None
    if channel in ("whatsapp", "sms") and not row.opted_in:
        return None  # never message a number that hasn't opted in
    return row.address


async def _addr(db: AsyncSession, user_id: uuid.UUID, channel: str) -> ChannelAddress | None:
    return (
        await db.execute(
            select(ChannelAddress).where(
                ChannelAddress.user_id == user_id, ChannelAddress.channel == channel
            )
        )
    ).scalar_one_or_none()


def reply_code_for(event_id: uuid.UUID) -> str:
    return event_id.hex[:4].upper()


async def notify(
    db: AsyncSession,
    user: User,
    type_: str,
    title: str,
    body: str = "",
    url: str = "",
    *,
    priority: str = "normal",
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    attempt_now: bool = True,
) -> NotificationEvent | None:
    """Create a notification and plan its deliveries. Returns None when `dedupe_key` was already used."""
    if type_ not in EVENT_TYPES:
        raise ValueError(f"Unknown notification type {type_}")
    key = dedupe_key or f"{type_}:{uuid.uuid4().hex}"
    if (
        await db.execute(
            select(NotificationEvent.id).where(
                NotificationEvent.user_id == user.id, NotificationEvent.dedupe_key == key
            )
        )
    ).first():
        return None
    ev = NotificationEvent(
        user_id=user.id,
        type=type_,
        title=title[:200],
        body=body,
        url=url,
        priority=priority,
        data=dict(data or {}),
        dedupe_key=key,
    )
    db.add(ev)
    await db.flush()
    if ev.data.get("conversation_id"):
        ev.data = {**ev.data, "reply_code": reply_code_for(ev.id)}
    now = datetime.now(UTC)
    deliveries: list[NotificationDelivery] = []
    for ch in CHANNEL_NAMES:
        enabled, mode = await preference(db, user.id, type_, ch)
        if not enabled:
            continue
        if ch == "in_app":
            deliveries.append(
                NotificationDelivery(
                    event_id=ev.id,
                    user_id=user.id,
                    channel=ch,
                    status="sent",
                    sent_at=now,
                    attempts=1,
                )
            )
            continue
        if await address_for(db, user, ch) is None:
            deliveries.append(
                NotificationDelivery(
                    event_id=ev.id,
                    user_id=user.id,
                    channel=ch,
                    status="skipped",
                    error="no destination / not opted in",
                )
            )
            continue
        d = NotificationDelivery(event_id=ev.id, user_id=user.id, channel=ch, mode=mode)
        urgent = priority == "high"
        if not urgent:
            qu = quiet_until(user, now)
            if qu is not None:
                d.next_attempt_at = qu
            elif mode in ("hourly", "daily"):
                d.status = "digest"
        deliveries.append(d)
    db.add_all(deliveries)
    await db.flush()
    hub.publish(
        user.id,
        "notification.new",
        {"id": str(ev.id), "type": type_, "title": title, "url": url, "priority": priority},
    )
    if attempt_now:
        for d in deliveries:
            if d.status == "pending" and d.next_attempt_at is None:
                await attempt(db, d, ev, user)
    return ev


async def emit(
    db: AsyncSession, user_id: uuid.UUID, type_: str, title: str, **kw: Any
) -> NotificationEvent | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    try:
        return await notify(db, user, type_, title, **kw)
    except Exception:  # notifications must never break the business operation that triggered them
        log.exception("notify failed type=%s", type_)
        return None


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=2**attempts)  # 2, 4, 8 minutes


async def attempt(
    db: AsyncSession,
    d: NotificationDelivery,
    ev: NotificationEvent | None = None,
    user: User | None = None,
) -> None:
    ev = ev or await db.get(NotificationEvent, d.event_id)
    user = user or await db.get(User, d.user_id)
    assert ev is not None and user is not None
    ch = CHANNELS.get("push_expo" if d.channel == "push" else d.channel)
    target = await address_for(db, user, d.channel)
    d.attempts += 1
    d.next_attempt_at = None
    msg = Message(
        title=ev.title,
        body=ev.body,
        url=ev.url,
        code=ev.data.get("reply_code", ""),
        data={"type": ev.type},
    )
    try:
        if ch is None or target is None:
            raise ChannelError("destination unavailable", retryable=False)
        if d.channel == "push":
            toks = list(
                (
                    await db.execute(select(DeviceToken).where(DeviceToken.user_id == user.id))
                ).scalars()
            )
            ids = []
            expo = [t.token for t in toks if t.kind == "expo"]
            web = [t.token for t in toks if t.kind == "webpush"]
            if expo:
                ids.append(await CHANNELS["push_expo"].send(expo, msg))
            if web:
                if not CHANNELS["push_web"].configured():
                    if not expo:
                        raise ChannelError("web push not configured", retryable=False)
                else:
                    ids.append(await CHANNELS["push_web"].send(web, msg))
            if not ids:
                raise ChannelError("no push destination", retryable=False)
            d.provider_id = ids[0]
        else:
            if not ch.configured():
                raise ChannelError(f"{d.channel} is not configured on this server", retryable=False)
            d.provider_id = await ch.send(target, msg)
        d.status, d.sent_at, d.error = "sent", datetime.now(UTC), ""
    except ChannelError as e:
        d.error = str(e)[:500]
        if e.retryable and d.attempts < MAX_ATTEMPTS:
            d.status, d.next_attempt_at = "pending", datetime.now(UTC) + _backoff(d.attempts)
        else:
            d.status = "failed"
            await _fallback(db, d, ev, user)
    except Exception as e:  # unexpected provider bug: treat as retryable once, then fail
        log.exception("delivery crashed channel=%s", d.channel)
        d.error = f"{type(e).__name__}: {e}"[:500]
        if d.attempts < MAX_ATTEMPTS:
            d.status, d.next_attempt_at = "pending", datetime.now(UTC) + _backoff(d.attempts)
        else:
            d.status = "failed"
            await _fallback(db, d, ev, user)
    await db.flush()


async def _fallback(
    db: AsyncSession, failed: NotificationDelivery, ev: NotificationEvent, user: User
) -> None:
    fb = settings_of(user)["fallback"].get(failed.channel)
    if not fb or fb == failed.channel:
        return
    exists = (
        await db.execute(
            select(NotificationDelivery.id).where(
                NotificationDelivery.event_id == ev.id, NotificationDelivery.channel == fb
            )
        )
    ).first()
    if exists or await address_for(db, user, fb) is None:
        return
    nd = NotificationDelivery(event_id=ev.id, user_id=user.id, channel=fb, fallback_of=failed.id)
    db.add(nd)
    await db.flush()
    await attempt(db, nd, ev, user)


async def process_due(db: AsyncSession, now: datetime | None = None) -> int:
    """Retry pending deliveries whose time has come. Run every minute by Celery beat."""
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(NotificationDelivery).where(NotificationDelivery.status == "pending")
        )
    ).scalars()
    n = 0
    for d in list(rows):
        if d.next_attempt_at is None or aware(d.next_attempt_at) <= now:
            await attempt(db, d)
            n += 1
    return n


async def flush_digests(db: AsyncSession, now: datetime | None = None) -> int:
    """Send one digest per (user, channel) for deliveries parked in 'digest'. Hourly mode flushes every run;
    daily mode flushes when the user's local hour equals their digest hour."""
    now = now or datetime.now(UTC)
    rows = list(
        (
            await db.execute(
                select(NotificationDelivery).where(NotificationDelivery.status == "digest")
            )
        ).scalars()
    )
    groups: dict[tuple[uuid.UUID, str], list[NotificationDelivery]] = {}
    for d in rows:
        groups.setdefault((d.user_id, d.channel), []).append(d)
    sent = 0
    for (uid, ch), items in groups.items():
        user = await db.get(User, uid)
        if user is None:
            continue
        due = [
            d
            for d in items
            if d.mode == "hourly"
            or (
                d.mode == "daily"
                and now.astimezone(_tz(user)).hour == settings_of(user)["digest_hour"]
            )
        ]
        if not due:
            continue
        events = [await db.get(NotificationEvent, d.event_id) for d in due]
        lines = [f"- {e.title}" + (f": {e.body[:80]}" if e.body else "") for e in events if e]
        target = await address_for(db, user, ch)
        msg = Message(
            title=f"Digest: {len(lines)} update(s)",
            body="\n".join(lines),
            url=f"{_web()}/notifications",
        )
        provider = CHANNELS.get("push_expo" if ch == "push" else ch)
        try:
            if target is None or provider is None or not provider.configured():
                raise ChannelError("digest destination unavailable", retryable=False)
            pid = await provider.send(target, msg)
            for d in due:
                d.status, d.sent_at, d.provider_id, d.attempts = "sent", now, pid, d.attempts + 1
            sent += 1
        except ChannelError as e:
            for d in due:
                d.status, d.error, d.attempts = "failed", str(e)[:300], d.attempts + 1
    await db.flush()
    return sent


def _web() -> str:
    from app.core.config import get_settings

    return get_settings().web_base_url


# ---- periodic scans (reminders that no user action triggers) ----
async def scan_reminders(db: AsyncSession, now: datetime | None = None) -> int:
    from app.models import Conversation, Job, Proposal, Stage
    from app.services import inbox

    now = now or datetime.now(UTC)
    n = 0
    due = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(
                Proposal.stage.in_([Stage.submitted, Stage.viewed, Stage.interview]),
                Proposal.follow_up_at.is_not(None),
            )
        )
    ).all()
    for p, j in due:
        if p.follow_up_at and aware(p.follow_up_at) <= now:
            ev = await emit(db, p.user_id, "follow_up_due", f"Follow up: {j.title}", body=f"Submitted on {j.platform}; no outcome yet.",
                            url=f"/proposals/{p.id}", dedupe_key=f"followup:{p.id}:{p.follow_up_at.date()}")  # fmt: skip
            n += 1 if ev else 0
    from app.services import calendar as cal

    for d in await cal.due_soon(db, now):
        ev = await emit(
            db,
            d["user_id"],
            "deadline",
            d["title"],
            url=d["url"],
            dedupe_key=d["key"],
            data=d["data"],
        )
        n += 1 if ev else 0
    convs = (
        await db.execute(select(Conversation).where(Conversation.awaiting_reply_since.is_not(None)))
    ).scalars()
    for c in list(convs):
        user = await db.get(User, c.user_id)
        if user is None or c.awaiting_reply_since is None:
            continue
        waited = now - aware(c.awaiting_reply_since)
        if waited >= timedelta(minutes=inbox.sla_minutes(user)):
            ev = await emit(db, c.user_id, "sla_breach", f"Client waiting {int(waited.total_seconds() // 60)} min", body=c.subject,
                            url=f"/inbox?c={c.id}", priority="high", data={"conversation_id": str(c.id)},
                            dedupe_key=f"sla:{c.id}:{aware(c.awaiting_reply_since).isoformat()}")  # fmt: skip
            n += 1 if ev else 0
    return n
