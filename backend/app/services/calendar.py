# mypy: disable-error-code="arg-type,operator"
"""Calendar aggregation (deadlines + events), ICS rendering, and deadline scans."""

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CalendarEvent,
    CalendarFeedToken,
    Invoice,
    Job,
    Milestone,
    Order,
    Proposal,
    Stage,
    Task,
)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def items(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(
        id_: str,
        kind: str,
        title: str,
        when: datetime,
        href: str,
        all_day: bool = False,
        end_: datetime | None = None,
    ) -> None:
        w = aware(when)
        if start <= w <= end:
            out.append(
                {
                    "id": id_,
                    "kind": kind,
                    "title": title,
                    "start": w,
                    "end": end_,
                    "all_day": all_day,
                    "href": href,
                }
            )

    for o in (
        await db.execute(
            select(Order).where(
                Order.user_id == user_id,
                Order.due_at.is_not(None),
                Order.status.notin_(["completed", "cancelled"]),
            )
        )
    ).scalars():
        add(f"order:{o.id}", "order_due", f"Due: {o.title}", o.due_at, f"/orders?id={o.id}")
    rows = await db.execute(
        select(Milestone, Order)
        .join(Order, Order.id == Milestone.order_id)
        .where(Order.user_id == user_id, Milestone.due_at.is_not(None), Milestone.status != "paid")
    )
    for m, o in rows.all():
        add(
            f"milestone:{m.id}",
            "milestone_due",
            f"Milestone: {m.title} ({o.title})",
            m.due_at,
            f"/orders?id={o.id}",
        )
    for t in (
        await db.execute(
            select(Task).where(
                Task.user_id == user_id, Task.due_at.is_not(None), Task.status != "done"
            )
        )
    ).scalars():
        add(
            f"task:{t.id}", "task_due", f"Task: {t.title}", t.due_at, f"/projects?id={t.project_id}"
        )
    for i in (
        await db.execute(
            select(Invoice).where(
                Invoice.user_id == user_id, Invoice.status == "sent", Invoice.due_date.is_not(None)
            )
        )
    ).scalars():
        add(
            f"invoice:{i.id}",
            "invoice_due",
            f"Invoice {i.number} due",
            datetime.combine(i.due_date, datetime.min.time(), UTC),
            "/finance",
            all_day=True,
        )
    pr = await db.execute(
        select(Proposal, Job)
        .join(Job, Job.id == Proposal.job_id)
        .where(
            Proposal.user_id == user_id,
            Proposal.follow_up_at.is_not(None),
            Proposal.stage.in_([Stage.submitted, Stage.viewed, Stage.interview]),
        )
    )
    for p, j in pr.all():
        add(
            f"followup:{p.id}",
            "follow_up",
            f"Follow up: {j.title}",
            p.follow_up_at,
            f"/proposals/{p.id}",
        )
    for e in (
        await db.execute(select(CalendarEvent).where(CalendarEvent.user_id == user_id))
    ).scalars():
        add(f"event:{e.id}", e.kind, e.title, e.starts_at, "/calendar", end_=e.ends_at)
    return sorted(out, key=lambda x: x["start"])


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\n", "\\n")


def _fmt(dt: datetime) -> str:
    return aware(dt).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def to_ics(entries: list[dict[str, Any]], name: str = "Freelance Manager") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Freelance Manager//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_esc(name)}",
    ]
    stamp = _fmt(datetime.now(UTC))
    for e in entries:
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@freelancemanager", f"DTSTAMP:{stamp}"]
        if e["all_day"]:
            d: date = aware(e["start"]).date()
            lines += [
                f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
            ]
        else:
            end = e["end"] or (aware(e["start"]) + timedelta(hours=1))
            lines += [f"DTSTART:{_fmt(e['start'])}", f"DTEND:{_fmt(end)}"]
        lines += [f"SUMMARY:{_esc(e['title'])}", f"CATEGORIES:{_esc(e['kind'])}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


async def feed_token(db: AsyncSession, user_id: uuid.UUID, rotate: bool = False) -> str:
    row = (
        await db.execute(select(CalendarFeedToken).where(CalendarFeedToken.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = CalendarFeedToken(user_id=user_id, token=secrets.token_urlsafe(24))
        db.add(row)
    elif rotate:
        row.token = secrets.token_urlsafe(24)
    await db.flush()
    return row.token


async def due_soon(
    db: AsyncSession, now: datetime, horizon: timedelta = timedelta(hours=24)
) -> list[dict[str, Any]]:
    """Cross-user scan used by the reminder job: things due within `horizon` + overdue invoices."""
    out: list[dict[str, Any]] = []
    lim = now + horizon
    for o in (
        await db.execute(
            select(Order).where(
                Order.due_at.is_not(None), Order.status.in_(["active", "revision", "pending"])
            )
        )
    ).scalars():
        if aware(o.due_at) <= lim:
            out.append(
                {
                    "user_id": o.user_id,
                    "key": f"order:{o.id}:{aware(o.due_at).date()}",
                    "title": f"Order due: {o.title}",
                    "url": f"/orders?id={o.id}",
                    "data": {"order_id": str(o.id)},
                }
            )
    rows = await db.execute(
        select(Milestone, Order)
        .join(Order, Order.id == Milestone.order_id)
        .where(Milestone.due_at.is_not(None), Milestone.status == "pending")
    )
    for m, o in rows.all():
        if aware(m.due_at) <= lim:
            out.append(
                {
                    "user_id": o.user_id,
                    "key": f"ms:{m.id}:{aware(m.due_at).date()}",
                    "title": f"Milestone due: {m.title}",
                    "url": f"/orders?id={o.id}",
                    "data": {},
                }
            )
    for t in (
        await db.execute(select(Task).where(Task.due_at.is_not(None), Task.status != "done"))
    ).scalars():
        if aware(t.due_at) <= lim:
            out.append(
                {
                    "user_id": t.user_id,
                    "key": f"task:{t.id}:{aware(t.due_at).date()}",
                    "title": f"Task due: {t.title}",
                    "url": f"/projects?id={t.project_id}",
                    "data": {},
                }
            )
    for i in (
        await db.execute(
            select(Invoice).where(Invoice.status == "sent", Invoice.due_date.is_not(None))
        )
    ).scalars():
        if i.due_date < now.date():
            out.append(
                {
                    "user_id": i.user_id,
                    "key": f"inv-overdue:{i.id}",
                    "title": f"Invoice {i.number} is overdue",
                    "url": "/finance",
                    "data": {},
                }
            )
    return out
