import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import (
    Client,
    Job,
    Milestone,
    Order,
    OrderFile,
    PlatformAccount,
    Project,
    Proposal,
    Stage,
)
from app.models.work import ORDER_STATUSES
from app.schemas import ORM, Message
from app.services import orders as svc
from app.services.common import get_owned

router = APIRouter(prefix="/orders", tags=["orders"])

DEFAULT_CHECKLIST = [
    "Requirements confirmed",
    "Work completed",
    "Self-review / QA",
    "Files exported & attached",
    "Delivery message written",
]


class MilestoneIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(default=0, ge=0)
    due_at: datetime | None = None


class MilestoneOut(MilestoneIn, ORM):
    id: uuid.UUID
    status: str
    paid_at: datetime | None


class OrderIn(BaseModel):
    platform: str
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    amount: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    client_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    due_at: datetime | None = None
    revisions_allowed: int = Field(default=1, ge=0)
    external_ref: str = ""
    checklist: list[dict[str, Any]] | None = None


class OrderPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    amount: float | None = Field(default=None, ge=0)
    due_at: datetime | None = None
    revisions_allowed: int | None = Field(default=None, ge=0)
    checklist: list[dict[str, Any]] | None = None
    client_id: uuid.UUID | None = None


class FileIn(BaseModel):
    filename: str = Field(max_length=300)
    url: str = Field(max_length=1000)
    kind: str = Field(default="deliverable", pattern="^(deliverable|reference)$")


class FileOut(FileIn, ORM):
    id: uuid.UUID


class OrderOut(ORM):
    id: uuid.UUID
    platform: str
    external_ref: str | None
    title: str
    description: str
    amount: float
    currency: str
    status: str
    client_id: uuid.UUID | None
    account_id: uuid.UUID | None
    due_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None
    revisions_allowed: int
    revisions_used: int
    checklist: list[dict[str, Any]]
    source: str
    created_at: datetime
    milestones: list[MilestoneOut] = []
    files: list[FileOut] = []
    client_name: str = ""
    project_id: uuid.UUID | None = None
    over_revision_limit: bool = False


async def _out(db: DB, o: Order) -> OrderOut:
    out = OrderOut.model_validate(o)
    out.milestones = [
        MilestoneOut.model_validate(m)
        for m in (
            await db.execute(
                select(Milestone).where(Milestone.order_id == o.id).order_by(Milestone.due_at)
            )
        ).scalars()
    ]
    out.files = [
        FileOut.model_validate(f)
        for f in (await db.execute(select(OrderFile).where(OrderFile.order_id == o.id))).scalars()
    ]
    if o.client_id and (c := await db.get(Client, o.client_id)):
        out.client_name = c.name
    p = (await db.execute(select(Project.id).where(Project.order_id == o.id))).scalars().first()
    out.project_id = p
    out.over_revision_limit = o.revisions_used > o.revisions_allowed
    return out


@router.get("", response_model=list[OrderOut])
async def list_orders(
    user: CurrentUser,
    db: DB,
    status: str | None = None,
    platform: str | None = None,
    client_id: uuid.UUID | None = None,
) -> list[OrderOut]:
    stmt = select(Order).where(Order.user_id == user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    if platform:
        stmt = stmt.where(Order.platform == platform)
    if client_id:
        stmt = stmt.where(Order.client_id == client_id)
    return [
        await _out(db, o)
        for o in (
            await db.execute(
                stmt.order_by(Order.due_at.is_(None), Order.due_at, Order.created_at.desc())
            )
        ).scalars()
    ]


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(body: OrderIn, user: CurrentUser, db: DB) -> OrderOut:
    if body.client_id:
        await get_owned(db, Client, body.client_id, user.id)
    if body.account_id:
        await get_owned(db, PlatformAccount, body.account_id, user.id)
    data = body.model_dump(exclude={"checklist"})
    data["external_ref"] = body.external_ref or None
    o = Order(
        user_id=user.id,
        checklist=body.checklist
        if body.checklist is not None
        else [{"item": i, "done": False} for i in DEFAULT_CHECKLIST],
        **data,
    )
    db.add(o)
    await db.commit()
    return await _out(db, o)


@router.post("/from-proposal/{pid}", response_model=OrderOut, status_code=201)
async def from_proposal(pid: uuid.UUID, user: CurrentUser, db: DB) -> OrderOut:
    p = await get_owned(db, Proposal, pid, user.id)
    if p.stage != Stage.won:
        raise HTTPException(409, "Only won proposals can become orders")
    if (await db.execute(select(Order.id).where(Order.proposal_id == p.id))).first():
        raise HTTPException(409, "An order already exists for this proposal")
    job = await db.get(Job, p.job_id)
    assert job is not None
    o = Order(
        user_id=user.id, proposal_id=p.id, platform=job.platform, title=job.title, description=job.description[:2000], amount=p.bid_amount or 0,
        currency=p.currency, client_id=job.client_id, account_id=p.account_id, source="proposal", checklist=[{"item": i, "done": False} for i in DEFAULT_CHECKLIST],
    )  # fmt: skip
    db.add(o)
    await db.commit()
    return await _out(db, o)


@router.get("/{oid}", response_model=OrderOut)
async def get_order(oid: uuid.UUID, user: CurrentUser, db: DB) -> OrderOut:
    return await _out(db, await get_owned(db, Order, oid, user.id))


@router.patch("/{oid}", response_model=OrderOut)
async def patch_order(oid: uuid.UUID, body: OrderPatch, user: CurrentUser, db: DB) -> OrderOut:
    o = await get_owned(db, Order, oid, user.id)
    d = body.model_dump(exclude_unset=True)
    if d.get("client_id"):
        await get_owned(db, Client, d["client_id"], user.id)
    for k, v in d.items():
        setattr(o, k, v)
    await db.commit()
    return await _out(db, o)


@router.post("/{oid}/status", response_model=OrderOut)
async def change_status(oid: uuid.UUID, status: str, user: CurrentUser, db: DB) -> OrderOut:
    o = await get_owned(db, Order, oid, user.id)
    if status not in ORDER_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(ORDER_STATUSES)}")
    if status == "completed" and o.status in ("completed", "cancelled"):
        raise HTTPException(409, f"Order is already {o.status}")
    await svc.set_status(db, o, status)
    await db.commit()
    return await _out(db, o)


@router.delete("/{oid}", response_model=Message)
async def delete_order(oid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Order, oid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/{oid}/milestones", response_model=OrderOut, status_code=201)
async def add_milestone(oid: uuid.UUID, body: MilestoneIn, user: CurrentUser, db: DB) -> OrderOut:
    o = await get_owned(db, Order, oid, user.id)
    db.add(Milestone(order_id=o.id, **body.model_dump()))
    await db.commit()
    return await _out(db, o)


@router.post("/{oid}/milestones/{mid}/{action}", response_model=OrderOut)
async def milestone_action(
    oid: uuid.UUID, mid: uuid.UUID, action: str, user: CurrentUser, db: DB
) -> OrderOut:
    o = await get_owned(db, Order, oid, user.id)
    m = await db.get(Milestone, mid)
    if m is None or m.order_id != o.id:
        raise HTTPException(404, "Milestone not found")
    if action == "submit":
        m.status = "submitted" if m.status == "pending" else m.status
    elif action == "pay":
        await svc.pay_milestone(db, o, m)
    else:
        raise HTTPException(422, "action must be submit or pay")
    await db.commit()
    return await _out(db, o)


@router.post("/{oid}/files", response_model=OrderOut, status_code=201)
async def add_file(oid: uuid.UUID, body: FileIn, user: CurrentUser, db: DB) -> OrderOut:
    o = await get_owned(db, Order, oid, user.id)
    db.add(OrderFile(order_id=o.id, **body.model_dump()))
    await db.commit()
    return await _out(db, o)


@router.post("/{oid}/project", status_code=201)
async def create_project(oid: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, str]:
    o = await get_owned(db, Order, oid, user.id)
    existing = (
        (await db.execute(select(Project.id).where(Project.order_id == o.id))).scalars().first()
    )
    if existing:
        return {"project_id": str(existing)}
    p = Project(
        user_id=user.id, order_id=o.id, client_id=o.client_id, name=o.title, currency=o.currency
    )
    db.add(p)
    await db.commit()
    return {"project_id": str(p.id)}
