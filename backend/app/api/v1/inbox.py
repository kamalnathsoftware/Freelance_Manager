import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.adapters.base import Capability, NotConfiguredError, NotSupportedError
from app.adapters.registry import ADAPTERS, get_adapter
from app.api.deps import DB, CurrentUser
from app.models import (
    Attachment,
    CannedResponse,
    Client,
    Conversation,
    ConvStatus,
    Message,
    PlatformAccount,
    TeamMember,
)
from app.schemas import ORM
from app.schemas import Message as Msg
from app.services import ai, inbox
from app.services.common import get_owned
from app.services.sync import context_for

router = APIRouter(tags=["inbox"])


class ConvOut(ORM):
    id: uuid.UUID
    platform: str
    subject: str
    platform_url: str
    client_id: uuid.UUID | None
    status: ConvStatus
    starred: bool
    labels: list[str]
    assignee_id: uuid.UUID | None
    snoozed_until: datetime | None
    unread_count: int
    last_message_at: datetime
    last_preview: str
    awaiting_reply_since: datetime | None
    client_name: str = ""
    client_vip: bool = False


class AttachmentIn(BaseModel):
    filename: str = Field(max_length=300)
    url: str = Field(max_length=1000)
    content_type: str = ""
    size: int = 0


class MessageOut(ORM):
    id: uuid.UUID
    direction: str
    sender_name: str
    body: str
    source: str
    delivery: str
    ai_generated: bool
    response_seconds: int | None
    created_at: datetime
    attachments: list[AttachmentIn] = []


class ConvPatch(BaseModel):
    starred: bool | None = None
    labels: list[str] | None = None
    status: ConvStatus | None = None
    snooze_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 90)
    assignee_id: uuid.UUID | None = None
    unassign: bool = False
    client_id: uuid.UUID | None = None


class NewConv(BaseModel):
    platform: str
    subject: str = Field(min_length=1, max_length=300)
    client_id: uuid.UUID | None = None
    client_name: str = ""
    body: str = ""  # optional first inbound message (paste from the platform)
    platform_url: str = ""


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    idempotency_key: str | None = Field(default=None, max_length=100)
    ai_generated: bool = False
    approved: bool = False  # required when ai_generated
    attachments: list[AttachmentIn] = []


class CannedIn(BaseModel):
    shortcut: str = Field(min_length=1, max_length=40)
    body: str = Field(min_length=1)


class CannedOut(CannedIn, ORM):
    id: uuid.UUID


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    target_language: str = "English"
    tone: str = "professional"


async def _conv_out(db: DB, c: Conversation) -> ConvOut:
    o = ConvOut.model_validate(c)
    if c.client_id:
        cl = await db.get(Client, c.client_id)
        if cl:
            o.client_name, o.client_vip = cl.name, cl.vip
    return o


async def _msg_out(db: DB, m: Message) -> MessageOut:
    o = MessageOut.model_validate(m)
    atts = (await db.execute(select(Attachment).where(Attachment.message_id == m.id))).scalars()
    o.attachments = [
        AttachmentIn(filename=a.filename, url=a.url, content_type=a.content_type, size=a.size)
        for a in atts
    ]
    return o


@router.get("/conversations", response_model=list[ConvOut])
async def list_conversations(
    user: CurrentUser, db: DB, status: ConvStatus = ConvStatus.open, platform: str | None = None, label: str | None = None,
    starred: bool | None = None, unread: bool = False, assignee_id: uuid.UUID | None = None, client_id: uuid.UUID | None = None,
    q: str | None = None, limit: int = 50, offset: int = 0,
) -> list[ConvOut]:  # fmt: skip
    all_rows = list(
        (
            await db.execute(
                select(Conversation).where(
                    Conversation.user_id == user.id, Conversation.status == ConvStatus.snoozed
                )
            )
        ).scalars()
    )
    inbox.unsnooze_due(all_rows)
    stmt = select(Conversation).where(
        Conversation.user_id == user.id, Conversation.status == status
    )
    if platform:
        stmt = stmt.where(Conversation.platform == platform)
    if starred is not None:
        stmt = stmt.where(Conversation.starred.is_(starred))
    if unread:
        stmt = stmt.where(Conversation.unread_count > 0)
    if assignee_id:
        stmt = stmt.where(Conversation.assignee_id == assignee_id)
    if client_id:
        stmt = stmt.where(Conversation.client_id == client_id)
    if q:
        like = f"%{q}%"
        in_body = select(Message.conversation_id).where(Message.body.ilike(like))
        stmt = stmt.where(
            or_(
                Conversation.subject.ilike(like),
                Conversation.last_preview.ilike(like),
                Conversation.id.in_(in_body),
            )
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(Conversation.last_message_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        ).scalars()
    )
    if label:
        rows = [r for r in rows if label in r.labels]
    await db.commit()  # persists unsnooze
    return [await _conv_out(db, r) for r in rows]


@router.get("/conversations/unread-counts")
async def unread_counts(user: CurrentUser, db: DB) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(Conversation.platform, func.sum(Conversation.unread_count))
            .where(Conversation.user_id == user.id, Conversation.status == ConvStatus.open)
            .group_by(Conversation.platform)
        )
    ).all()
    by = {p: int(n or 0) for p, n in rows}
    return {"total": sum(by.values()), "by_platform": by}


@router.get("/conversations/sla-alerts")
async def sla_alerts(user: CurrentUser, db: DB) -> dict[str, Any]:
    return {"sla_minutes": inbox.sla_minutes(user), "alerts": await inbox.sla_alerts(db, user)}


@router.get("/conversations/response-times")
async def response_times(user: CurrentUser, db: DB) -> list[dict[str, Any]]:
    return await inbox.response_stats(db, user.id)


@router.post("/conversations", response_model=ConvOut, status_code=201)
async def create_conversation(body: NewConv, user: CurrentUser, db: DB) -> ConvOut:
    """Start (or paste in) a thread manually: for platforms without sync, and for direct clients."""
    if body.platform not in ADAPTERS:
        raise HTTPException(422, f"Unknown platform '{body.platform}'")
    client = await get_owned(db, Client, body.client_id, user.id) if body.client_id else None
    if client is None and body.client_name:
        client = await inbox.resolve_client(
            db, user.id, body.platform, body.client_name, name=body.client_name
        )
    conv, created = await inbox.get_or_create_conversation(
        db,
        user.id,
        body.platform,
        f"manual:{uuid.uuid4().hex[:12]}",
        subject=body.subject,
        client=client,
        platform_url=body.platform_url,
    )
    if body.body:
        await inbox.add_inbound(
            db, conv, body.body, sender=client.name if client else "", source="manual"
        )
    await db.commit()
    return await _conv_out(db, conv)


@router.get("/conversations/{cid}", response_model=ConvOut)
async def get_conversation(cid: uuid.UUID, user: CurrentUser, db: DB) -> ConvOut:
    return await _conv_out(db, await get_owned(db, Conversation, cid, user.id))


@router.patch("/conversations/{cid}", response_model=ConvOut)
async def patch_conversation(cid: uuid.UUID, body: ConvPatch, user: CurrentUser, db: DB) -> ConvOut:
    c = await get_owned(db, Conversation, cid, user.id)
    d = body.model_dump(exclude_unset=True)
    if "starred" in d and body.starred is not None:
        c.starred = body.starred
    if body.labels is not None:
        c.labels = sorted({label.strip() for label in body.labels if label.strip()})
    if body.status is not None:
        c.status = body.status
        c.snoozed_until = None
    if body.snooze_minutes:
        c.status, c.snoozed_until = (
            ConvStatus.snoozed,
            datetime.now(UTC) + timedelta(minutes=body.snooze_minutes),
        )
    if body.unassign:
        c.assignee_id = None
    elif body.assignee_id:
        ok = (
            body.assignee_id == user.id
            or (
                await db.execute(
                    select(TeamMember.id).where(
                        TeamMember.owner_id == user.id,
                        TeamMember.member_user_id == body.assignee_id,
                    )
                )
            ).first()
        )
        if not ok:
            raise HTTPException(422, "Assignee must be you or one of your team members")
        c.assignee_id = body.assignee_id
    if body.client_id:
        await get_owned(db, Client, body.client_id, user.id)
        c.client_id = body.client_id
    await db.commit()
    return await _conv_out(db, c)


@router.delete("/conversations/{cid}", response_model=Msg)
async def delete_conversation(cid: uuid.UUID, user: CurrentUser, db: DB) -> Msg:
    await db.delete(await get_owned(db, Conversation, cid, user.id))
    await db.commit()
    return Msg(detail="Deleted")


@router.get("/conversations/{cid}/messages", response_model=list[MessageOut])
async def messages(
    cid: uuid.UUID, user: CurrentUser, db: DB, mark_read: bool = True
) -> list[MessageOut]:
    c = await get_owned(db, Conversation, cid, user.id)
    rows = list(
        (
            await db.execute(
                select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
            )
        ).scalars()
    )
    if mark_read and c.unread_count:
        c.unread_count = 0
        await db.commit()
    return [await _msg_out(db, m) for m in rows]


@router.post("/conversations/{cid}/messages")
async def send_message(cid: uuid.UUID, body: SendIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    """Reply. Sends via API only where the platform allows it; otherwise returns the assisted
    'reply on platform' flow and the message stays `pending_manual` until the user confirms."""
    c = await get_owned(db, Conversation, cid, user.id)
    if body.ai_generated and not body.approved:
        raise HTTPException(422, "AI-generated replies require explicit approval")
    adapter = get_adapter(c.platform)
    acc = await db.get(PlatformAccount, c.account_id) if c.account_id else None
    delivery = "pending_manual"
    if c.platform == "direct":
        delivery = "sent"
    elif acc is not None and acc.mode.value == "api" and adapter.supports(Capability.send_message):
        try:
            await adapter.send_message(await context_for(db, acc), c.thread_key, body.body)
            delivery = "sent"
        except (NotConfiguredError, NotSupportedError):
            delivery = "pending_manual"
    msg, created = await inbox.add_outbound(
        db,
        c,
        body.body,
        delivery=delivery,
        ai_generated=body.ai_generated,
        idempotency_key=body.idempotency_key,
    )
    if created:
        for a in body.attachments:
            db.add(Attachment(user_id=user.id, message_id=msg.id, **a.model_dump()))
    await db.commit()
    link = c.platform_url or adapter.deep_link("inbox") or adapter.base_url
    return {
        "message": (await _msg_out(db, msg)).model_dump(mode="json"),
        "duplicate": not created,
        "requires_manual_paste": msg.delivery == "pending_manual",
        "reply_on_platform_url": link if msg.delivery == "pending_manual" else None,
    }


@router.post("/messages/{mid}/confirm-sent", response_model=MessageOut)
async def confirm_sent(mid: uuid.UUID, user: CurrentUser, db: DB) -> MessageOut:
    m = await db.get(Message, mid)
    c = await db.get(Conversation, m.conversation_id) if m else None
    if m is None or c is None or c.user_id != user.id or m.direction != "out":
        raise HTTPException(404, "Message not found")
    await inbox.confirm_manual_delivery(db, c, m)
    await db.commit()
    return await _msg_out(db, m)


# ---- canned responses ----
@router.get("/canned-responses", response_model=list[CannedOut])
async def list_canned(user: CurrentUser, db: DB) -> list[CannedResponse]:
    return list(
        (
            await db.execute(select(CannedResponse).where(CannedResponse.user_id == user.id))
        ).scalars()
    )


@router.post("/canned-responses", response_model=CannedOut, status_code=201)
async def add_canned(body: CannedIn, user: CurrentUser, db: DB) -> CannedResponse:
    r = CannedResponse(user_id=user.id, **body.model_dump())
    db.add(r)
    await db.commit()
    return r


@router.delete("/canned-responses/{rid}", response_model=Msg)
async def del_canned(rid: uuid.UUID, user: CurrentUser, db: DB) -> Msg:
    await db.delete(await get_owned(db, CannedResponse, rid, user.id))
    await db.commit()
    return Msg(detail="Deleted")


# ---- AI helpers (suggestions only) ----
@router.post("/conversations/{cid}/suggest-reply")
async def suggest_reply(
    cid: uuid.UUID, user: CurrentUser, db: DB, tone: str = "professional"
) -> dict[str, Any]:
    c = await get_owned(db, Conversation, cid, user.id)
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )[::-1]
    transcript = "\n".join(f"{'ME' if m.direction == 'out' else 'CLIENT'}: {m.body}" for m in rows)
    text = await ai.complete(
        "You draft replies for a freelancer. Be concise, specific and honest; never promise what the transcript doesn't support. "
        "Return only the reply text.",
        f"Tone: {tone}. Platform: {c.platform}.\n\nConversation:\n{transcript}\n\nWrite my next reply.",
        500,
    )
    return {"text": text, "ai_generated": True, "requires_approval": True}


@router.post("/conversations/{cid}/summary")
async def summarize(cid: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    c = await get_owned(db, Conversation, cid, user.id)
    rows = list(
        (
            await db.execute(
                select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
            )
        ).scalars()
    )
    transcript = "\n".join(f"{'ME' if m.direction == 'out' else 'CLIENT'}: {m.body}" for m in rows)[
        -8000:
    ]
    text = await ai.complete(
        "Summarise this client thread in 3-5 bullets: requirements, deadlines/budget, open questions, next step.",
        transcript, 400,
    )  # fmt: skip
    return {"text": text, "ai_generated": True}


@router.post("/ai/translate")
async def translate(body: TextIn, _: CurrentUser) -> dict[str, Any]:
    text = await ai.complete(
        "Translate faithfully. Return only the translation.",
        f"Target language: {body.target_language}\n\n{body.text}",
        1000,
    )
    return {"text": text, "ai_generated": True}


@router.post("/ai/tone-check")
async def tone_check(body: TextIn, _: CurrentUser) -> dict[str, Any]:
    text = await ai.complete(
        "You are an editor. Fix spelling/grammar and point out any tone problems for a client message. "
        "Reply as: CORRECTED: <text>\\nNOTES: <one or two short bullets>.",
        f"Desired tone: {body.tone}\n\n{body.text}", 700,
    )  # fmt: skip
    return {"text": text, "ai_generated": True}
