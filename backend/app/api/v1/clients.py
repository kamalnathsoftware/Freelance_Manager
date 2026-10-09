import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app.api.deps import DB, CurrentUser
from app.models import (
    Client,
    ClientIdentity,
    Conversation,
    Job,
    Proposal,
    Stage,
)
from app.schemas import ORM, Message
from app.services import inbox
from app.services.common import get_owned

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = ""
    company: str = ""
    country: str = ""
    timezone: str = ""
    notes: str = ""
    tags: list[str] = []
    vip: bool = False
    total_earned: float = Field(default=0, ge=0)
    completed_orders: int = Field(default=0, ge=0)


class IdentityIn(BaseModel):
    platform: str
    handle: str = Field(min_length=1, max_length=200)


class IdentityOut(IdentityIn, ORM):
    id: uuid.UUID


class ClientOut(ClientIn, ORM):
    id: uuid.UUID
    created_at: datetime
    identities: list[IdentityOut] = []
    lifetime_value: float = 0
    repeat_client: bool = False
    won_proposals: int = 0


class MergeIn(BaseModel):
    source_id: uuid.UUID


async def _out(db: DB, c: Client) -> ClientOut:
    o = ClientOut.model_validate(c)
    o.identities = [
        IdentityOut.model_validate(i)
        for i in (
            await db.execute(select(ClientIdentity).where(ClientIdentity.client_id == c.id))
        ).scalars()
    ]
    won = (
        await db.execute(
            select(func.count(Proposal.id))
            .join(Job, Job.id == Proposal.job_id)
            .where(Job.client_id == c.id, Proposal.stage == Stage.won)
        )
    ).scalar_one()
    o.won_proposals, o.lifetime_value = int(won), c.total_earned
    o.repeat_client = (c.completed_orders + int(won)) >= 2
    return o


@router.get("", response_model=list[ClientOut])
async def list_clients(
    user: CurrentUser,
    db: DB,
    q: str | None = None,
    tag: str | None = None,
    vip: bool | None = None,
    limit: int = 100,
) -> list[ClientOut]:
    stmt = select(Client).where(Client.user_id == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Client.name.ilike(like), Client.email.ilike(like), Client.company.ilike(like))
        )
    if vip is not None:
        stmt = stmt.where(Client.vip.is_(vip))
    rows = list((await db.execute(stmt.order_by(Client.name).limit(min(limit, 500)))).scalars())
    if tag:
        rows = [r for r in rows if tag in r.tags]
    return [await _out(db, c) for c in rows]


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(body: ClientIn, user: CurrentUser, db: DB) -> ClientOut:
    c = Client(user_id=user.id, **body.model_dump())
    db.add(c)
    await db.commit()
    return await _out(db, c)


@router.get("/{cid}", response_model=ClientOut)
async def get_client(cid: uuid.UUID, user: CurrentUser, db: DB) -> ClientOut:
    return await _out(db, await get_owned(db, Client, cid, user.id))


@router.put("/{cid}", response_model=ClientOut)
async def update_client(cid: uuid.UUID, body: ClientIn, user: CurrentUser, db: DB) -> ClientOut:
    c = await get_owned(db, Client, cid, user.id)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    await db.commit()
    return await _out(db, c)


@router.delete("/{cid}", response_model=Message)
async def delete_client(cid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Client, cid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/{cid}/identities", response_model=ClientOut, status_code=201)
async def add_identity(cid: uuid.UUID, body: IdentityIn, user: CurrentUser, db: DB) -> ClientOut:
    c = await get_owned(db, Client, cid, user.id)
    handle = body.handle.strip().lower()
    taken = (
        await db.execute(
            select(ClientIdentity).where(
                ClientIdentity.user_id == user.id,
                ClientIdentity.platform == body.platform,
                ClientIdentity.handle == handle,
            )
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise HTTPException(
            409, "That identity already belongs to a client - merge the clients instead"
        )
    db.add(ClientIdentity(user_id=user.id, client_id=c.id, platform=body.platform, handle=handle))
    await db.commit()
    return await _out(db, c)


@router.post("/{cid}/merge", response_model=ClientOut)
async def merge(cid: uuid.UUID, body: MergeIn, user: CurrentUser, db: DB) -> ClientOut:
    """Fold `source` into this client: identities, conversations, jobs, totals and tags move over."""
    target = await get_owned(db, Client, cid, user.id)
    source = await get_owned(db, Client, body.source_id, user.id)
    if source.id == target.id:
        raise HTTPException(422, "Cannot merge a client into itself")
    for model in (ClientIdentity, Conversation, Job):
        await db.execute(
            update(model).where(model.client_id == source.id).values(client_id=target.id)
        )
    target.tags = sorted(set(target.tags) | set(source.tags))
    target.total_earned += source.total_earned
    target.completed_orders += source.completed_orders
    target.vip = target.vip or source.vip
    target.email = target.email or source.email
    target.company = target.company or source.company
    target.notes = "\n\n".join(x for x in (target.notes, source.notes) if x)
    await db.flush()
    await db.refresh(source)
    await db.delete(source)
    await db.commit()
    return await _out(db, target)


@router.get("/{cid}/history")
async def history(cid: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    c = await get_owned(db, Client, cid, user.id)
    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.client_id == c.id)
            .order_by(Conversation.last_message_at.desc())
        )
    ).scalars()
    jobs = (
        await db.execute(select(Job).where(Job.client_id == c.id).order_by(Job.created_at.desc()))
    ).scalars()
    return {
        "conversations": [
            {
                "id": str(x.id),
                "platform": x.platform,
                "subject": x.subject,
                "last_message_at": x.last_message_at.isoformat(),
            }
            for x in convs
        ],
        "jobs": [{"id": str(j.id), "platform": j.platform, "title": j.title} for j in jobs],
    }


@router.post("/from-job/{job_id}", response_model=ClientOut, status_code=201)
async def from_job(job_id: uuid.UUID, user: CurrentUser, db: DB) -> ClientOut:
    job = await get_owned(db, Job, job_id, user.id)
    name = str((job.client or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(422, "This job has no client name")
    c = await inbox.resolve_client(db, user.id, job.platform, name, name=name)
    job.client_id = c.id
    await db.commit()
    return await _out(db, c)
