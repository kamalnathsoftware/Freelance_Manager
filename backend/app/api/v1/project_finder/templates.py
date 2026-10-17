import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import PFLead, PFTemplate
from app.schemas import ORM, Message
from app.services.common import get_owned
from app.services.project_finder import get_pf_settings
from app.services.project_finder import templates as svc

router = APIRouter(tags=["project-finder"])
Kind = Literal["cold_email", "linkedin_dm", "proposal"]


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Kind
    subject: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("name", "body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Kind | None = None
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=10000)


class TemplateOut(ORM):
    id: uuid.UUID
    name: str
    kind: str
    subject: str
    body: str
    created_at: datetime


class RenderIn(BaseModel):
    lead_id: uuid.UUID | None = None


class GenerateIn(BaseModel):
    lead_id: uuid.UUID
    instructions: str = Field(default="", max_length=500)


class DraftOut(BaseModel):
    subject: str
    body: str
    missing: list[str] = []
    unknown: list[str] = []
    ai_generated: bool = False


@router.get("/templates/variables")
async def variables(user: CurrentUser) -> dict[str, str]:
    return svc.VARIABLES


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(user: CurrentUser, db: DB, kind: Kind | None = None) -> list[PFTemplate]:
    stmt = select(PFTemplate).where(PFTemplate.user_id == user.id)
    if kind:
        stmt = stmt.where(PFTemplate.kind == kind)
    return list((await db.execute(stmt.order_by(PFTemplate.kind, PFTemplate.name))).scalars())


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(body: TemplateIn, user: CurrentUser, db: DB) -> PFTemplate:
    t = PFTemplate(user_id=user.id, **body.model_dump())
    db.add(t)
    await db.commit()
    return t


@router.post("/templates/starters", response_model=list[TemplateOut], status_code=201)
async def add_starters(user: CurrentUser, db: DB) -> list[PFTemplate]:
    """Add the starter templates that don't exist yet (matched by name), so it's safe to click twice."""
    have = set(
        (await db.execute(select(PFTemplate.name).where(PFTemplate.user_id == user.id))).scalars()
    )
    created = [PFTemplate(user_id=user.id, **s) for s in svc.STARTERS if s["name"] not in have]
    db.add_all(created)
    await db.commit()
    return created


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: uuid.UUID, body: TemplatePatch, user: CurrentUser, db: DB
) -> PFTemplate:
    t = await get_owned(db, PFTemplate, template_id, user.id)
    for k, v in body.model_dump(exclude_unset=True, exclude_none=True).items():
        if k in ("name", "body") and not v.strip():
            raise HTTPException(422, f"{k} must not be blank")
        setattr(t, k, v)
    await db.commit()
    return t


@router.delete("/templates/{template_id}", response_model=Message)
async def delete_template(template_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, PFTemplate, template_id, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/templates/{template_id}/render", response_model=DraftOut)
async def render_template(
    template_id: uuid.UUID, body: RenderIn, user: CurrentUser, db: DB
) -> DraftOut:
    """Fill {{placeholders}} from a lead and your settings. No AI involved; placeholders that can't be
    filled stay visible and are listed in `missing` / `unknown`."""
    t = await get_owned(db, PFTemplate, template_id, user.id)
    lead = await get_owned(db, PFLead, body.lead_id, user.id) if body.lead_id else None
    vals = svc.build_vars(lead, await get_pf_settings(db, user.id))
    subject, m1, u1 = svc.render(t.subject, vals)
    text, m2, u2 = svc.render(t.body, vals)
    await db.commit()
    return DraftOut(
        subject=subject,
        body=text,
        missing=list(dict.fromkeys(m1 + m2)),
        unknown=list(dict.fromkeys(u1 + u2)),
    )


@router.post("/templates/{template_id}/generate", response_model=DraftOut)
async def generate_draft(
    template_id: uuid.UUID, body: GenerateIn, user: CurrentUser, db: DB
) -> DraftOut:
    """LLM-personalised draft from the lead's notes. Needs ANTHROPIC_API_KEY. Returns text only -
    the app never sends messages."""
    t = await get_owned(db, PFTemplate, template_id, user.id)
    lead = await get_owned(db, PFLead, body.lead_id, user.id)
    cfg = await get_pf_settings(db, user.id)
    subject, text = await svc.generate(t.kind, t.body, lead, cfg, body.instructions.strip())
    await db.commit()
    return DraftOut(subject=subject or t.subject, body=text, ai_generated=True)
