from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.models import Client, Conversation, Gig, Job, Message

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    user: CurrentUser, db: DB, q: str = Query(min_length=2, max_length=100), limit: int = 5
) -> dict[str, list[dict[str, Any]]]:
    """Global search for the Cmd/Ctrl+K palette. Everything is scoped to the signed-in user."""
    like, n = f"%{q}%", min(limit, 20)
    clients = (
        await db.execute(
            select(Client)
            .where(
                Client.user_id == user.id,
                or_(Client.name.ilike(like), Client.company.ilike(like), Client.email.ilike(like)),
            )
            .limit(n)
        )
    ).scalars()
    convs = (
        await db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                or_(Conversation.subject.ilike(like), Conversation.last_preview.ilike(like)),
            )
            .limit(n)
        )
    ).scalars()
    msgs = (
        await db.execute(
            select(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user.id, Message.body.ilike(like))
            .limit(n)
        )
    ).all()
    jobs = (
        await db.execute(
            select(Job)
            .where(Job.user_id == user.id, or_(Job.title.ilike(like), Job.description.ilike(like)))
            .limit(n)
        )
    ).scalars()
    gigs = (
        await db.execute(
            select(Gig)
            .where(Gig.user_id == user.id, or_(Gig.title.ilike(like), Gig.description.ilike(like)))
            .limit(n)
        )
    ).scalars()
    return {
        "clients": [
            {"id": str(c.id), "title": c.name, "subtitle": c.company, "href": f"/clients?id={c.id}"}
            for c in clients
        ],
        "conversations": [
            {
                "id": str(c.id),
                "title": c.subject,
                "subtitle": c.platform,
                "href": f"/inbox?c={c.id}",
            }
            for c in convs
        ],
        "messages": [
            {
                "id": str(m.id),
                "title": m.body[:80],
                "subtitle": c.subject,
                "href": f"/inbox?c={c.id}",
            }
            for m, c in msgs
        ],
        "jobs": [
            {"id": str(j.id), "title": j.title, "subtitle": j.platform, "href": "/jobs"}
            for j in jobs
        ],
        "gigs": [
            {"id": str(g.id), "title": g.title, "subtitle": g.status.value, "href": "/gigs"}
            for g in gigs
        ],
    }
