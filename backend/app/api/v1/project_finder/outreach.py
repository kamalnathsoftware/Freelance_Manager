import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import PFLead, PFOutreachLog
from app.services.common import get_owned
from app.services.project_finder.outreach import (
    apply_status,
    default_channel,
    goal_status,
    log_outreach,
    today_for,
)

router = APIRouter(tags=["project-finder"])


class DayOut(BaseModel):
    date: date
    count: int
    met: bool


class GoalOut(BaseModel):
    goal: int
    today: int
    remaining: int
    goal_met: bool
    streak: int
    best_streak: int
    days: list[DayOut]


class LogIn(BaseModel):
    lead_id: uuid.UUID | None = None
    channel: Literal["email", "linkedin", "other"] | None = None


@router.get("/outreach/goal", response_model=GoalOut)
async def get_goal(user: CurrentUser, db: DB) -> dict[str, object]:
    g = await goal_status(db, user)
    await db.commit()  # persists the default settings row on first use
    return g


@router.post("/outreach/log", response_model=GoalOut, status_code=201)
async def add_log(body: LogIn, user: CurrentUser, db: DB) -> dict[str, object]:
    """Record one outreach message you sent (manually). Logging against a "new" lead moves it to
    "contacted". Nothing is ever sent by the app."""
    lead = await get_owned(db, PFLead, body.lead_id, user.id) if body.lead_id else None
    if lead is not None and lead.status == "new" and lead.last_contacted_at is None:
        # first contact: apply_status logs the message and schedules the default follow-up
        await apply_status(db, user, lead, "contacted", follow_up_given=False, channel=body.channel)
    else:
        channel = body.channel or (default_channel(lead) if lead else "other")
        await log_outreach(db, user, lead, channel)
    g = await goal_status(db, user)
    await db.commit()
    return g


@router.delete("/outreach/log/latest", response_model=GoalOut)
async def undo_latest(user: CurrentUser, db: DB) -> dict[str, object]:
    """Undo the most recent entry logged today (a mis-click)."""
    row = (
        await db.execute(
            select(PFOutreachLog)
            .where(PFOutreachLog.user_id == user.id, PFOutreachLog.sent_on == today_for(user))
            .order_by(PFOutreachLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Nothing logged today")
    await db.delete(row)
    await db.flush()
    g = await goal_status(db, user)
    await db.commit()
    return g
