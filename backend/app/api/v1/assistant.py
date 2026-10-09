import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import Conversation, FormSubmission, Job, Message
from app.services import assistant as svc
from app.services.common import get_owned

router = APIRouter(prefix="/assistant", tags=["assistant"])

LABEL = {"ai_generated": True, "requires_approval": True}


class ExtractIn(BaseModel):
    text: str | None = Field(default=None, max_length=20000)
    conversation_id: uuid.UUID | None = None
    submission_id: uuid.UUID | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict[str, str]] = Field(default=[], max_length=20)


@router.get("/briefing")
async def briefing(user: CurrentUser, db: DB, narrative: bool = False) -> dict[str, Any]:
    """Deterministic facts + one-line headline. `narrative=true` adds a Claude-written summary (labelled)."""
    facts = await svc.briefing_facts(db, user)
    out: dict[str, Any] = {"headline": svc.headline(facts), "facts": facts, "narrative": None}
    if narrative:
        text = await svc.narrative(facts)
        out["narrative"] = {"text": text, **LABEL} if text else None
    return out


@router.post("/extract-requirements")
async def extract(body: ExtractIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    text = body.text or ""
    if body.conversation_id:
        c = await get_owned(db, Conversation, body.conversation_id, user.id)
        rows = (
            await db.execute(
                select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
            )
        ).scalars()
        text += "\n".join(f"{'ME' if m.direction == 'out' else 'CLIENT'}: {m.body}" for m in rows)
    if body.submission_id:
        s = await get_owned(db, FormSubmission, body.submission_id, user.id)
        text += "\n".join(f"{k}: {v}" for k, v in s.answers.items())
    if not text.strip():
        raise HTTPException(422, "Provide text, conversation_id or submission_id")
    return {**await svc.extract_requirements(text), **LABEL}


@router.get("/pricing/{job_id}")
async def pricing(job_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    job = await get_owned(db, Job, job_id, user.id)
    return {**await svc.pricing_advice(db, user, job), **LABEL}


@router.post("/chat")
async def chat(body: ChatIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    return {"text": await svc.chat(db, user, body.message, body.history), **LABEL}
