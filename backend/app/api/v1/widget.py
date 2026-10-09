import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.security import hash_token
from app.models import ChatWidget, Conversation, Message
from app.schemas import ORM
from app.services import inbox

router = APIRouter(tags=["widget"])


class WidgetIn(BaseModel):
    greeting: str = Field(default="Hi! How can I help?", max_length=300)
    enabled: bool = True


class WidgetOut(WidgetIn, ORM):
    public_key: str
    embed_snippet: str = ""


class VisitorMessage(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    body: str = Field(min_length=1, max_length=4000)
    name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)


class VisitorMsgOut(BaseModel):
    id: uuid.UUID
    direction: str
    body: str
    created_at: datetime


def _snippet(w: ChatWidget) -> str:
    s = get_settings()
    return f'<script src="{s.web_base_url}/widget.js" data-key="{w.public_key}" data-api="{s.public_api_url}" defer></script>'


async def _widget_for(db: DB, user_id: uuid.UUID) -> ChatWidget:
    w = (
        await db.execute(select(ChatWidget).where(ChatWidget.user_id == user_id))
    ).scalar_one_or_none()
    if w is None:
        w = ChatWidget(user_id=user_id, public_key="cw_" + secrets.token_urlsafe(18))
        db.add(w)
        await db.flush()
    return w


@router.get("/widget", response_model=WidgetOut)
async def get_widget(user: CurrentUser, db: DB) -> WidgetOut:
    w = await _widget_for(db, user.id)
    await db.commit()
    o = WidgetOut.model_validate(w)
    o.embed_snippet = _snippet(w)
    return o


@router.put("/widget", response_model=WidgetOut)
async def put_widget(body: WidgetIn, user: CurrentUser, db: DB) -> WidgetOut:
    w = await _widget_for(db, user.id)
    w.greeting, w.enabled = body.greeting, body.enabled
    await db.commit()
    o = WidgetOut.model_validate(w)
    o.embed_snippet = _snippet(w)
    return o


async def _public_widget(db: DB, key: str) -> ChatWidget:
    w = (
        await db.execute(
            select(ChatWidget).where(ChatWidget.public_key == key, ChatWidget.enabled.is_(True))
        )
    ).scalar_one_or_none()
    if w is None:
        raise HTTPException(404, "Chat is not available")
    return w


@router.get("/public/widget/{key}")
async def widget_config(key: str, db: DB) -> dict[str, str]:
    w = await _public_widget(db, key)
    return {"greeting": w.greeting}


@router.post("/public/widget/{key}/messages")
async def visitor_send(
    key: str, body: VisitorMessage, db: DB, x_visitor_token: str | None = Header(default=None)
) -> dict[str, str | None]:
    """Anonymous visitor posts a message. The first message mints a secret token; later calls must present it."""
    w = await _public_widget(db, key)
    thread_key = inbox.widget_thread_key(body.visitor_id)
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.user_id == w.user_id,
                Conversation.platform == "direct",
                Conversation.thread_key == thread_key,
            )
        )
    ).scalar_one_or_none()
    token: str | None = None
    if conv is None:
        client = await inbox.resolve_client(
            db,
            w.user_id,
            "direct",
            f"widget:{body.visitor_id}",
            name=body.name or "Website visitor",
            email=body.email,
        )
        conv, _ = await inbox.get_or_create_conversation(
            db,
            w.user_id,
            "direct",
            thread_key,
            subject=f"Website chat - {body.name or 'visitor'}",
            client=client,
        )
        token, conv.visitor_token_hash = inbox.new_visitor_token()
    elif not x_visitor_token or hash_token(x_visitor_token) != conv.visitor_token_hash:
        raise HTTPException(403, "Invalid visitor token")
    await inbox.add_inbound(
        db, conv, body.body, sender=body.name or "Website visitor", source="widget"
    )
    await db.commit()
    return {"visitor_token": token}


@router.get("/public/widget/{key}/messages", response_model=list[VisitorMsgOut])
async def visitor_poll(
    key: str, visitor_id: str, db: DB, x_visitor_token: str | None = Header(default=None)
) -> list[Message]:
    w = await _public_widget(db, key)
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.user_id == w.user_id,
                Conversation.platform == "direct",
                Conversation.thread_key == inbox.widget_thread_key(visitor_id),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        return []
    if not x_visitor_token or hash_token(x_visitor_token) != conv.visitor_token_hash:
        raise HTTPException(403, "Invalid visitor token")
    return list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.delivery == "sent")
                .order_by(Message.created_at)
            )
        ).scalars()
    )
