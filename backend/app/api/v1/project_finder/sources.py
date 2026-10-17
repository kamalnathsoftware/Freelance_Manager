import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.common import HttpUrlStr
from app.models import PFSource
from app.schemas import ORM, Message
from app.services.common import get_owned
from app.services.project_finder.feeds import SPEC_BY_KEY
from app.services.project_finder.refresh import ensure_default_sources

router = APIRouter(tags=["project-finder"])


class SourceOut(ORM):
    id: uuid.UUID
    key: str
    name: str
    url: str
    kind: str
    builtin: bool
    status: str
    last_checked_at: datetime | None
    last_result: str
    notes: str
    hint: str = ""


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrlStr = Field(min_length=1)
    notes: str = Field(default="", max_length=2000)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: HttpUrlStr | None = Field(default=None, min_length=1)
    status: Literal["active", "paused"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


def out(s: PFSource) -> SourceOut:
    o = SourceOut.model_validate(s)
    spec = SPEC_BY_KEY.get(s.key)
    o.hint = spec.hint if spec else ""
    return o


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(user: CurrentUser, db: DB) -> list[SourceOut]:
    rows = await ensure_default_sources(db, user.id)
    await db.commit()
    return [out(r) for r in rows]


@router.post("/sources", response_model=SourceOut, status_code=201)
async def add_source(body: SourceIn, user: CurrentUser, db: DB) -> SourceOut:
    """A custom, manual source (a link you check yourself). Custom sources are never fetched."""
    s = PFSource(
        user_id=user.id,
        key=f"custom-{uuid.uuid4().hex[:10]}",
        kind="manual",
        builtin=False,
        **body.model_dump(),
    )
    db.add(s)
    await db.commit()
    return out(s)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID, body: SourcePatch, user: CurrentUser, db: DB
) -> SourceOut:
    s = await get_owned(db, PFSource, source_id, user.id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if s.builtin and ({"name", "url"} & changes.keys()):
        raise HTTPException(
            400, "Built-in sources keep their name and address; you can pause them or add notes"
        )
    for k, v in changes.items():
        setattr(s, k, v)
    await db.commit()
    return out(s)


@router.post("/sources/{source_id}/mark-checked", response_model=SourceOut)
async def mark_checked(source_id: uuid.UUID, user: CurrentUser, db: DB) -> SourceOut:
    """For manual sources: record that you looked at the site today."""
    s = await get_owned(db, PFSource, source_id, user.id)
    s.last_checked_at = datetime.now(UTC)
    s.last_result = "checked manually"
    await db.commit()
    return out(s)


@router.delete("/sources/{source_id}", response_model=Message)
async def delete_source(source_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    s = await get_owned(db, PFSource, source_id, user.id)
    if s.builtin:
        raise HTTPException(400, "Built-in sources can be paused but not deleted")
    await db.delete(s)
    await db.commit()
    return Message(detail="Deleted")
