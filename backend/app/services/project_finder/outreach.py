"""Lead status rules, the daily outreach goal / streak, and due follow-up reminders."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PFLead, PFOutreachLog, User
from app.services.project_finder import get_pf_settings, valid_tz

STATUSES = ("new", "contacted", "replied", "call_booked", "proposal_sent", "won", "lost")
CLOSED = ("won", "lost")
CHANNELS = ("email", "linkedin", "other")
FOLLOW_UP_DAYS = 3  # default follow-up after first contact when no date was chosen


def today_for(user: User, now: datetime | None = None) -> date:
    """ "Today" in the user's own time zone (so the daily goal rolls over at their midnight)."""
    tz = ZoneInfo(user.timezone) if user.timezone and valid_tz(user.timezone) else UTC
    return (now or datetime.now(UTC)).astimezone(tz).date()


def default_channel(lead: PFLead) -> str:
    return "email" if lead.email else "linkedin" if lead.linkedin_url else "other"


async def log_outreach(
    db: AsyncSession, user: User, lead: PFLead | None, channel: str, now: datetime | None = None
) -> PFOutreachLog:
    now = now or datetime.now(UTC)
    row = PFOutreachLog(
        user_id=user.id,
        lead_id=lead.id if lead else None,
        channel=channel,
        sent_on=today_for(user, now),
    )
    db.add(row)
    if lead is not None:
        lead.last_contacted_at = now
    await db.flush()
    return row


async def apply_status(
    db: AsyncSession,
    user: User,
    lead: PFLead,
    new: str,
    *,
    follow_up_given: bool,
    channel: str | None = None,
    now: datetime | None = None,
) -> None:
    """Move a lead to `new`, applying the side effects of the CRM workflow.

    - first move to "contacted": counts as one outreach message and (unless a follow-up date was
      chosen) schedules a follow-up FOLLOW_UP_DAYS later;
    - won / lost: the lead is closed, so its follow-up reminder is cleared.
    """
    now = now or datetime.now(UTC)
    old, lead.status = lead.status, new
    if new == "contacted" and old != "contacted" and lead.last_contacted_at is None:
        await log_outreach(db, user, lead, channel or default_channel(lead), now)
        if not follow_up_given and lead.next_follow_up is None:
            lead.next_follow_up = today_for(user, now) + timedelta(days=FOLLOW_UP_DAYS)
    if new in CLOSED:
        lead.next_follow_up = None


def _streaks(days_met: set[date], today: date) -> tuple[int, int]:
    """(current, best) runs of consecutive days that met the goal. A streak that ended yesterday is
    still alive today (the day isn't over yet)."""
    cur, d = 0, today if today in days_met else today - timedelta(days=1)
    while d in days_met:
        cur, d = cur + 1, d - timedelta(days=1)
    best = run = 0
    prev: date | None = None
    for d in sorted(days_met):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return cur, best


async def goal_status(
    db: AsyncSession, user: User, now: datetime | None = None, window: int = 14
) -> dict[str, object]:
    cfg = await get_pf_settings(db, user.id)
    today = today_for(user, now)
    rows = (
        await db.execute(
            select(PFOutreachLog.sent_on, func.count())
            .where(PFOutreachLog.user_id == user.id)
            .group_by(PFOutreachLog.sent_on)
        )
    ).all()
    counts = {d: n for d, n in rows}
    met = {d for d, n in counts.items() if n >= cfg.daily_goal}
    streak, best = _streaks(met, today)
    n_today = counts.get(today, 0)
    return {
        "goal": cfg.daily_goal,
        "today": n_today,
        "remaining": max(cfg.daily_goal - n_today, 0),
        "goal_met": n_today >= cfg.daily_goal,
        "streak": streak,
        "best_streak": best,
        "days": [
            {"date": d, "count": counts.get(d, 0), "met": d in met}
            for d in (today - timedelta(days=i) for i in range(window - 1, -1, -1))
        ],
    }


async def scan_followups(db: AsyncSession, now: datetime | None = None) -> int:
    """Notify (in-app, plus email/push per the user's notification matrix) about leads whose follow-up
    date has arrived. Deduplicated per lead per date, so the 30-minute scan never repeats itself."""
    from app.services.notifications import emit

    now = now or datetime.now(UTC)
    horizon = (now + timedelta(days=1)).date()  # covers users ahead of UTC; exact check is per user
    leads = (
        await db.execute(
            select(PFLead).where(
                PFLead.next_follow_up.is_not(None),
                PFLead.next_follow_up <= horizon,
                PFLead.status.notin_(CLOSED),
            )
        )
    ).scalars()
    users: dict[uuid.UUID, User | None] = {}
    sent = 0
    for lead in list(leads):
        if lead.user_id not in users:
            users[lead.user_id] = await db.get(User, lead.user_id)
        user = users[lead.user_id]
        if user is None or not user.is_active or lead.next_follow_up is None:
            continue
        if lead.next_follow_up > today_for(user, now):
            continue
        ev = await emit(
            db,
            user.id,
            "follow_up_due",
            f"Follow up with {lead.business_name}",
            body=lead.problem[:200] or f"Status: {lead.status.replace('_', ' ')}",
            url=f"/project-finder/leads?lead={lead.id}",
            dedupe_key=f"pf_lead:{lead.id}:{lead.next_follow_up.isoformat()}",
        )
        sent += 1 if ev else 0
    return sent
