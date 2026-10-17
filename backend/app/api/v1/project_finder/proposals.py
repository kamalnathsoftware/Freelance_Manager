import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.common import CurrencyStr
from app.models import PFJob, PFLead, PFProposal
from app.schemas import ORM, Message
from app.services.common import get_owned
from app.services.project_finder.feeds import SPEC_BY_KEY
from app.services.project_finder.outreach import today_for
from app.services.project_finder.proposals import advance_lead, sync_reply

router = APIRouter(tags=["project-finder"])
PStatus = Literal["sent", "replied", "interview", "won", "lost", "no_response"]


class ProposalIn(BaseModel):
    title: str = Field(default="", max_length=300)
    lead_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=80)
    sent_on: date | None = None
    amount: float | None = Field(default=None, ge=0, le=1e9)
    currency: CurrencyStr = "USD"
    status: PStatus = "sent"
    replied_on: date | None = None
    outcome: str = Field(default="", max_length=3000)


class ProposalPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    source: str | None = Field(default=None, max_length=80)
    sent_on: date | None = None
    amount: float | None = Field(default=None, ge=0, le=1e9)  # send null to clear
    currency: CurrencyStr | None = None
    status: PStatus | None = None
    replied_on: date | None = None  # send null to clear
    outcome: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def _dates(self) -> "ProposalPatch":
        if self.sent_on and self.replied_on and self.replied_on < self.sent_on:
            raise ValueError("replied_on cannot be before sent_on")
        return self


class ProposalOut(ORM):
    id: uuid.UUID
    title: str
    lead_id: uuid.UUID | None
    lead_name: str = ""
    job_id: uuid.UUID | None
    source: str
    sent_on: date
    amount: float | None
    currency: str
    status: str
    replied_on: date | None
    outcome: str
    created_at: datetime
    replied: bool = False
    days_waiting: int | None = None  # only while still "sent"


async def _view(db: DB, rows: list[PFProposal], today: date) -> list[ProposalOut]:
    ids = {r.lead_id for r in rows if r.lead_id}
    names = (
        dict(
            (
                await db.execute(select(PFLead.id, PFLead.business_name).where(PFLead.id.in_(ids)))
            ).all()
        )
        if ids
        else {}
    )
    out = []
    for r in rows:
        o = ProposalOut.model_validate(r)
        o.lead_name = names.get(r.lead_id, "") if r.lead_id else ""
        o.replied = r.replied_on is not None
        o.days_waiting = (today - r.sent_on).days if r.status == "sent" else None
        out.append(o)
    return out


def _check_dates(sent_on: date, replied_on: date | None, today: date) -> None:
    if sent_on > today + timedelta(days=1):
        raise HTTPException(422, "sent_on cannot be in the future")
    if replied_on and replied_on < sent_on:
        raise HTTPException(422, "replied_on cannot be before sent_on")


@router.get("/proposals", response_model=list[ProposalOut])
async def list_proposals(
    user: CurrentUser,
    db: DB,
    status: PStatus | None = None,
    source: str | None = None,
    lead_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ProposalOut]:
    stmt = select(PFProposal).where(PFProposal.user_id == user.id)
    if status:
        stmt = stmt.where(PFProposal.status == status)
    if source:
        stmt = stmt.where(PFProposal.source == source)
    if lead_id:
        stmt = stmt.where(PFProposal.lead_id == lead_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PFProposal.title.ilike(like), PFProposal.outcome.ilike(like)))
    stmt = stmt.order_by(PFProposal.sent_on.desc(), PFProposal.created_at.desc())
    rows = list((await db.execute(stmt.limit(limit).offset(offset))).scalars())
    return await _view(db, rows, today_for(user))


@router.post("/proposals", response_model=ProposalOut, status_code=201)
async def create_proposal(body: ProposalIn, user: CurrentUser, db: DB) -> ProposalOut:
    lead = await get_owned(db, PFLead, body.lead_id, user.id) if body.lead_id else None
    job = await get_owned(db, PFJob, body.job_id, user.id) if body.job_id else None
    today = today_for(user)
    title = body.title.strip() or (job.title if job else "") or (lead.business_name if lead else "")
    if not title:
        raise HTTPException(422, "Give the proposal a title, or link it to a lead or job")
    source = body.source if body.source is not None else (
        (lead.source if lead and lead.source else "") or (SPEC_BY_KEY[job.source_key].name if job and job.source_key in SPEC_BY_KEY else "")
    )  # fmt: skip
    sent_on = body.sent_on or today
    _check_dates(sent_on, body.replied_on, today)
    p = PFProposal(
        user_id=user.id, title=title[:300], lead_id=body.lead_id, job_id=body.job_id, source=source[:80],
        sent_on=sent_on, amount=body.amount, currency=body.currency or "USD", status=body.status,
        replied_on=body.replied_on, outcome=body.outcome,
    )  # fmt: skip
    sync_reply(p, today)
    db.add(p)
    advance_lead(lead, p.status, created=True)
    await db.commit()
    return (await _view(db, [p], today))[0]


@router.patch("/proposals/{proposal_id}", response_model=ProposalOut)
async def update_proposal(
    proposal_id: uuid.UUID, body: ProposalPatch, user: CurrentUser, db: DB
) -> ProposalOut:
    p = await get_owned(db, PFProposal, proposal_id, user.id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None and k not in ("amount", "replied_on"):
            continue  # null clears only the amount and the reply date
        setattr(p, k, v)
    today = today_for(user)
    _check_dates(p.sent_on, p.replied_on, today)
    if "status" in changes and changes["status"]:
        if "replied_on" not in changes:
            sync_reply(p, today)
        lead = await db.get(PFLead, p.lead_id) if p.lead_id else None
        advance_lead(
            lead if lead is not None and lead.user_id == user.id else None, p.status, created=False
        )
    await db.commit()
    return (await _view(db, [p], today))[0]


@router.delete("/proposals/{proposal_id}", response_model=Message)
async def delete_proposal(proposal_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, PFProposal, proposal_id, user.id))
    await db.commit()
    return Message(detail="Deleted")
