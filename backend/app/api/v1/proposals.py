import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters.base import Capability, NotConfiguredError, NotSupportedError
from app.adapters.registry import get_adapter
from app.api.deps import DB, CurrentUser
from app.models import (
    CreditEntry,
    Job,
    MasterProfile,
    PlatformAccount,
    Proposal,
    ProposalTemplate,
    Stage,
)
from app.schemas import ORM, Message
from app.services import ai
from app.services import proposals as svc
from app.services.common import get_owned
from app.services.sync import context_for

router = APIRouter(tags=["proposals"])


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1)
    platform: str = ""


class TemplateOut(TemplateIn, ORM):
    id: uuid.UUID


class ProposalIn(BaseModel):
    job_id: uuid.UUID
    account_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    stage: Stage = Stage.drafted


class ProposalUpdate(BaseModel):
    body: str | None = None
    bid_amount: float | None = Field(default=None, ge=0)
    account_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    credits_used: int | None = Field(default=None, ge=0)
    portfolio_ids: list[str] | None = None
    attachments: list[str] | None = None
    follow_up_at: datetime | None = None


class ProposalOut(ORM):
    id: uuid.UUID
    job_id: uuid.UUID
    account_id: uuid.UUID | None
    template_id: uuid.UUID | None
    stage: Stage
    position: int
    body: str
    bid_amount: float | None
    currency: str
    credits_used: int
    portfolio_ids: list[str]
    attachments: list[str]
    ai_generated: bool
    approved_at: datetime | None
    submitted_at: datetime | None
    submitted_via: str
    lost_reason: str
    follow_up_at: datetime | None
    stage_changed_at: datetime
    job_title: str = ""
    platform: str = ""
    unresolved_variables: list[str] = []


class MoveIn(BaseModel):
    stage: Stage
    lost_reason: str = ""


class DraftIn(BaseModel):
    template_id: uuid.UUID | None = None
    use_ai: bool = False
    tone: str = "professional"


class CreditIn(BaseModel):
    delta: int
    note: str = ""


async def _out(db: DB, p: Proposal, job: Job | None = None) -> ProposalOut:
    job = job or await db.get(Job, p.job_id)
    o = ProposalOut.model_validate(p)
    o.job_title, o.platform = (job.title, job.platform) if job else ("", "")
    o.unresolved_variables = svc.unresolved(p.body)
    return o


async def _master(db: DB, uid: uuid.UUID) -> MasterProfile | None:
    return (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == uid))
    ).scalar_one_or_none()


# ---------- templates ----------
@router.get("/proposal-templates", response_model=list[TemplateOut])
async def list_templates(user: CurrentUser, db: DB) -> list[ProposalTemplate]:
    return list(
        (
            await db.execute(select(ProposalTemplate).where(ProposalTemplate.user_id == user.id))
        ).scalars()
    )


@router.post("/proposal-templates", response_model=TemplateOut, status_code=201)
async def add_template(body: TemplateIn, user: CurrentUser, db: DB) -> ProposalTemplate:
    t = ProposalTemplate(user_id=user.id, **body.model_dump())
    db.add(t)
    await db.commit()
    return t


@router.put("/proposal-templates/{tid}", response_model=TemplateOut)
async def edit_template(
    tid: uuid.UUID, body: TemplateIn, user: CurrentUser, db: DB
) -> ProposalTemplate:
    t = await get_owned(db, ProposalTemplate, tid, user.id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    return t


@router.delete("/proposal-templates/{tid}", response_model=Message)
async def del_template(tid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, ProposalTemplate, tid, user.id))
    await db.commit()
    return Message(detail="Deleted")


# ---------- proposals ----------
@router.post("/proposals", response_model=ProposalOut, status_code=201)
async def create_proposal(body: ProposalIn, user: CurrentUser, db: DB) -> ProposalOut:
    job = await get_owned(db, Job, body.job_id, user.id)
    if body.account_id:
        await get_owned(db, PlatformAccount, body.account_id, user.id)
    p = Proposal(
        user_id=user.id, job_id=job.id, account_id=body.account_id, template_id=body.template_id
    )
    db.add(p)
    await db.flush()
    await svc.move(db, p, body.stage)
    await db.commit()
    return await _out(db, p, job)


@router.get("/proposals/{pid}", response_model=ProposalOut)
async def get_proposal(pid: uuid.UUID, user: CurrentUser, db: DB) -> ProposalOut:
    return await _out(db, await get_owned(db, Proposal, pid, user.id))


@router.patch("/proposals/{pid}", response_model=ProposalOut)
async def update_proposal(
    pid: uuid.UUID, body: ProposalUpdate, user: CurrentUser, db: DB
) -> ProposalOut:
    p = await get_owned(db, Proposal, pid, user.id)
    data = body.model_dump(exclude_unset=True)
    if data.get("account_id"):
        await get_owned(db, PlatformAccount, data["account_id"], user.id)
    if "body" in data and data["body"] != p.body:
        p.approved_at = None  # any edit invalidates a prior approval
    for k, v in data.items():
        setattr(p, k, v)
    await db.commit()
    return await _out(db, p)


@router.delete("/proposals/{pid}", response_model=Message)
async def delete_proposal(pid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Proposal, pid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/proposals/{pid}/draft", response_model=ProposalOut)
async def draft(pid: uuid.UUID, body: DraftIn, user: CurrentUser, db: DB) -> ProposalOut:
    """Fill the proposal body from a template, or an AI draft. Never auto-approved or sent."""
    p = await get_owned(db, Proposal, pid, user.id)
    job = await db.get(Job, p.job_id)
    assert job is not None
    master = await _master(db, user.id)
    variables = svc.variables_for(job, master)
    if body.use_ai:
        sk = ", ".join((master.skills if master else [])[:12])
        text = await ai.complete(
            "You write concise, specific freelance proposals. No fluff, no invented credentials or past clients. "
            "Return only the proposal text.",
            f"Tone: {body.tone}. Platform: {job.platform}.\nJOB TITLE: {job.title}\nJOB: {job.description[:3000]}\n"
            f"MY NAME: {variables['my_name']}\nMY HEADLINE: {master.headline if master else ''}\nMY SKILLS: {sk}\n"
            f"MY BIO: {(master.bio if master else '')[:1500]}",
            900,
        )
        p.body, p.ai_generated = text, True
    elif body.template_id:
        t = await get_owned(db, ProposalTemplate, body.template_id, user.id)
        p.body, p.template_id, p.ai_generated = svc.render(t.body, variables), t.id, False
    else:
        raise HTTPException(422, "Provide template_id or use_ai")
    p.approved_at = None
    if p.stage in (Stage.found, Stage.shortlisted):
        await svc.move(db, p, Stage.drafted)
    await db.commit()
    return await _out(db, p, job)


@router.post("/proposals/{pid}/approve", response_model=ProposalOut)
async def approve(pid: uuid.UUID, user: CurrentUser, db: DB) -> ProposalOut:
    """Explicit human approval. Required before any submission, API or manual."""
    p = await get_owned(db, Proposal, pid, user.id)
    if not p.body.strip():
        raise HTTPException(422, "Proposal is empty")
    left = svc.unresolved(p.body)
    if left:
        raise HTTPException(422, f"Unresolved variables: {', '.join('{' + v + '}' for v in left)}")
    p.approved_at = datetime.now(UTC)
    await db.commit()
    return await _out(db, p)


@router.post("/proposals/{pid}/submit")
async def submit(pid: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    p = await get_owned(db, Proposal, pid, user.id)
    if p.approved_at is None:
        raise HTTPException(409, "Approve the proposal before submitting")
    job = await db.get(Job, p.job_id)
    assert job is not None
    acc = await db.get(PlatformAccount, p.account_id) if p.account_id else None
    adapter = get_adapter(job.platform)
    if (
        acc is not None
        and acc.platform == job.platform
        and acc.mode.value == "api"
        and adapter.supports(Capability.submit_proposal)
    ):
        try:
            await adapter.submit_proposal(
                await context_for(db, acc), job.external_id,
                {"body": p.body, "bid_amount": p.bid_amount, "currency": p.currency, "attachments": p.attachments},
            )  # fmt: skip
            await _mark_submitted(db, p, acc, "api")
            await db.commit()
            return {"submitted": True, "via": "api"}
        except (NotConfiguredError, NotSupportedError):
            pass  # fall back to assisted flow below
    link = adapter.deep_link("job", job_id=job.external_id)
    return {
        "submitted": False,
        "via": "manual",
        "proposal_text": p.body,
        "bid_amount": p.bid_amount,
        "open_url": job.url or link or adapter.base_url,
        "instructions": "Paste the proposal on the platform yourself, then click 'Mark as submitted'.",
    }


async def _mark_submitted(db: DB, p: Proposal, acc: PlatformAccount | None, via: str) -> None:
    await svc.move(db, p, Stage.submitted)
    p.submitted_at, p.submitted_via = datetime.now(UTC), via
    p.follow_up_at = p.follow_up_at or datetime.now(UTC) + timedelta(days=3)
    await svc.spend_credits(db, acc, p.credits_used, "Proposal submitted")


@router.post("/proposals/{pid}/mark-submitted", response_model=ProposalOut)
async def mark_submitted(pid: uuid.UUID, user: CurrentUser, db: DB) -> ProposalOut:
    p = await get_owned(db, Proposal, pid, user.id)
    if p.approved_at is None:
        raise HTTPException(409, "Approve the proposal before submitting")
    if p.stage in (Stage.submitted, Stage.viewed, Stage.interview, Stage.won):
        raise HTTPException(409, "Already submitted")
    acc = await db.get(PlatformAccount, p.account_id) if p.account_id else None
    await _mark_submitted(db, p, acc, "manual")
    await db.commit()
    return await _out(db, p)


@router.patch("/proposals/{pid}/move", response_model=ProposalOut)
async def move(pid: uuid.UUID, body: MoveIn, user: CurrentUser, db: DB) -> ProposalOut:
    p = await get_owned(db, Proposal, pid, user.id)
    if body.stage == Stage.submitted and p.approved_at is None:
        raise HTTPException(409, "Approve the proposal before moving it to Submitted")
    try:
        await svc.move(db, p, body.stage, body.lost_reason)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    await db.commit()
    return await _out(db, p)


# ---------- pipeline ----------
@router.get("/pipeline")
async def pipeline(user: CurrentUser, db: DB) -> dict[str, list[ProposalOut]]:
    rows = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(Proposal.user_id == user.id)
            .order_by(Proposal.position)
        )
    ).all()
    board: dict[str, list[ProposalOut]] = {s.value: [] for s in Stage}
    for p, j in rows:
        board[p.stage.value].append(await _out(db, p, j))
    return board


@router.get("/pipeline/follow-ups", response_model=list[ProposalOut])
async def follow_ups(user: CurrentUser, db: DB) -> list[ProposalOut]:
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(
                Proposal.user_id == user.id,
                Proposal.stage.in_([Stage.submitted, Stage.viewed, Stage.interview]),
                Proposal.follow_up_at.is_not(None),
            )
        )
    ).all()
    due = [(p, j) for p, j in rows if p.follow_up_at and svc.aware(p.follow_up_at) <= now]
    return [await _out(db, p, j) for p, j in due]


@router.get("/analytics/proposals")
async def proposal_analytics(user: CurrentUser, db: DB) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(Proposal.user_id == user.id)
        )
    ).all()
    templates = {
        t.id: t.name
        for t in (
            await db.execute(select(ProposalTemplate).where(ProposalTemplate.user_id == user.id))
        ).scalars()
    }
    return svc.proposal_analytics([(p, j) for p, j in rows], templates)


# ---------- credits ----------
@router.get("/platforms/accounts/{account_id}/credits")
async def credits(account_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    entries = (
        await db.execute(
            select(CreditEntry)
            .where(CreditEntry.account_id == acc.id)
            .order_by(CreditEntry.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return {
        "balance": await svc.credit_balance(db, acc.id),
        "entries": [
            {"delta": e.delta, "note": e.note, "at": e.created_at.isoformat()} for e in entries
        ],
    }


@router.post("/platforms/accounts/{account_id}/credits")
async def adjust_credits(
    account_id: uuid.UUID, body: CreditIn, user: CurrentUser, db: DB
) -> dict[str, Any]:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    db.add(CreditEntry(account_id=acc.id, delta=body.delta, note=body.note))
    await db.flush()
    balance = await svc.credit_balance(db, acc.id)
    stats = dict(acc.stats or {})
    stats["credits"] = balance
    acc.stats = stats
    await db.commit()
    return {"balance": balance, "low": balance < 10}
