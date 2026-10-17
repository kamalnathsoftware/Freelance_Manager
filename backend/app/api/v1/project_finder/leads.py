import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.common import (
    CurrencyStr,
    EmailOrBlank,
    HttpUrlStr,
    TzStr,
)
from app.models import PFJob, PFLead
from app.schemas import ORM, Message
from app.services.common import get_owned
from app.services.project_finder.outreach import STATUSES, apply_status, today_for

router = APIRouter(tags=["project-finder"])

LeadStatus = Literal["new", "contacted", "replied", "call_booked", "proposal_sent", "won", "lost"]
assert set(LeadStatus.__args__) == set(STATUSES)  # type: ignore[attr-defined]


class LeadIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(default="", max_length=200)
    email: EmailOrBlank = ""
    linkedin_url: HttpUrlStr = ""
    website: HttpUrlStr = ""
    problem: str = Field(default="", max_length=5000)
    notes: str = Field(default="", max_length=5000)
    source: str = Field(default="", max_length=80)
    status: LeadStatus = "new"
    next_follow_up: date | None = None
    country: str = Field(default="", max_length=80)
    timezone: TzStr = ""
    currency: CurrencyStr = ""
    job_id: uuid.UUID | None = None


class LeadPatch(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailOrBlank | None = None
    linkedin_url: HttpUrlStr | None = None
    website: HttpUrlStr | None = None
    problem: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)
    source: str | None = Field(default=None, max_length=80)
    status: LeadStatus | None = None
    next_follow_up: date | None = None  # send null to clear
    country: str | None = Field(default=None, max_length=80)
    timezone: TzStr | None = None
    currency: CurrencyStr | None = None


class LeadOut(ORM):
    id: uuid.UUID
    business_name: str
    contact_name: str
    email: str
    linkedin_url: str
    website: str
    problem: str
    notes: str
    source: str
    status: str
    next_follow_up: date | None
    last_contacted_at: datetime | None
    country: str
    timezone: str
    currency: str
    job_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    follow_up_due: bool = False


def out(lead: PFLead, today: date) -> LeadOut:
    o = LeadOut.model_validate(lead)
    o.follow_up_due = (
        lead.next_follow_up is not None
        and lead.next_follow_up <= today
        and lead.status not in ("won", "lost")
    )
    return o


async def _check_job(db: DB, user_id: uuid.UUID, job_id: uuid.UUID | None) -> None:
    if job_id is not None:
        await get_owned(db, PFJob, job_id, user_id)


@router.get("/leads", response_model=list[LeadOut])
async def list_leads(
    user: CurrentUser,
    db: DB,
    status: LeadStatus | None = None,
    q: str | None = None,
    due: bool = False,
    country: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[LeadOut]:
    today = today_for(user)
    stmt = select(PFLead).where(PFLead.user_id == user.id)
    if status:
        stmt = stmt.where(PFLead.status == status)
    if country:
        stmt = stmt.where(PFLead.country.ilike(country))
    if due:
        stmt = stmt.where(
            PFLead.next_follow_up.is_not(None),
            PFLead.next_follow_up <= today,
            PFLead.status.notin_(["won", "lost"]),
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                PFLead.business_name.ilike(like),
                PFLead.contact_name.ilike(like),
                PFLead.problem.ilike(like),
                PFLead.email.ilike(like),
            )
        )
    stmt = stmt.order_by(
        PFLead.next_follow_up.is_(None), PFLead.next_follow_up, PFLead.created_at.desc()
    )
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars()
    return [out(r, today) for r in rows]


@router.post("/leads", response_model=LeadOut, status_code=201)
async def create_lead(body: LeadIn, user: CurrentUser, db: DB) -> LeadOut:
    await _check_job(db, user.id, body.job_id)
    data = body.model_dump()
    status = data.pop("status")
    follow_up_given = data["next_follow_up"] is not None
    lead = PFLead(user_id=user.id, **data)
    db.add(lead)
    await db.flush()
    if status != "new":
        await apply_status(db, user, lead, status, follow_up_given=follow_up_given)
    await db.commit()
    return out(lead, today_for(user))


@router.get("/leads/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: uuid.UUID, user: CurrentUser, db: DB) -> LeadOut:
    return out(await get_owned(db, PFLead, lead_id, user.id), today_for(user))


@router.patch("/leads/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: uuid.UUID, body: LeadPatch, user: CurrentUser, db: DB) -> LeadOut:
    lead = await get_owned(db, PFLead, lead_id, user.id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("business_name",):
        if required in changes and changes[required] is None:
            raise HTTPException(422, f"{required} cannot be null")
    status = changes.pop("status", None)
    follow_up_given = "next_follow_up" in changes
    for k, v in changes.items():
        if v is None and k != "next_follow_up":
            continue  # null means "leave as is" for every field except the follow-up date
        setattr(lead, k, v)
    if status and status != lead.status:
        await apply_status(db, user, lead, status, follow_up_given=follow_up_given)
    elif lead.status in ("won", "lost"):
        lead.next_follow_up = None
    await db.commit()
    return out(lead, today_for(user))


@router.delete("/leads/{lead_id}", response_model=Message)
async def delete_lead(lead_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, PFLead, lead_id, user.id))
    await db.commit()
    return Message(detail="Deleted")
