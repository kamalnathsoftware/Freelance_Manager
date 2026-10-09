import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.crypto import encrypt
from app.models import CalendarConnection, CalendarEvent, CalendarFeedToken
from app.schemas import ORM, Message
from app.services import calendar as svc
from app.services import gcal
from app.services.common import get_owned

router = APIRouter(prefix="/calendar", tags=["calendar"])

SCOPE = "https://www.googleapis.com/auth/calendar"


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="other", pattern="^(interview|followup|meeting|other)$")
    starts_at: datetime
    ends_at: datetime | None = None
    notes: str = ""


class EventOut(EventIn, ORM):
    id: uuid.UUID
    google_event_id: str


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    s = start or datetime.now(UTC) - timedelta(days=7)
    return svc.aware(s), svc.aware(end or s + timedelta(days=60))


@router.get("")
async def agenda(
    user: CurrentUser, db: DB, start: datetime | None = None, end: datetime | None = None
) -> list[dict[str, Any]]:
    s, e = _range(start, end)
    return [
        {**i, "start": i["start"].isoformat(), "end": i["end"].isoformat() if i["end"] else None}
        for i in await svc.items(db, user.id, s, e)
    ]


@router.post("/events", response_model=EventOut, status_code=201)
async def add_event(body: EventIn, user: CurrentUser, db: DB) -> CalendarEvent:
    ev = CalendarEvent(user_id=user.id, **body.model_dump())
    db.add(ev)
    await db.commit()
    return ev


@router.put("/events/{eid}", response_model=EventOut)
async def edit_event(eid: uuid.UUID, body: EventIn, user: CurrentUser, db: DB) -> CalendarEvent:
    ev = await get_owned(db, CalendarEvent, eid, user.id)
    for k, v in body.model_dump().items():
        setattr(ev, k, v)
    await db.commit()
    return ev


@router.delete("/events/{eid}", response_model=Message)
async def del_event(eid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, CalendarEvent, eid, user.id))
    await db.commit()
    return Message(detail="Deleted")


# ---- ICS ----
@router.get("/feed-url")
async def feed_url(user: CurrentUser, db: DB, rotate: bool = False) -> dict[str, str]:
    tok = await svc.feed_token(db, user.id, rotate)
    await db.commit()
    return {"url": f"{get_settings().public_api_url}/api/v1/calendar/feed/{tok}.ics"}


@router.get("/export.ics")
async def export_ics(user: CurrentUser, db: DB) -> Response:
    now = datetime.now(UTC)
    body = svc.to_ics(
        await svc.items(db, user.id, now - timedelta(days=30), now + timedelta(days=365))
    )
    return Response(
        body,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="freelance-manager.ics"'},
    )


@router.get("/feed/{token}.ics")
async def public_feed(token: str, db: DB) -> Response:
    row = (
        await db.execute(select(CalendarFeedToken).where(CalendarFeedToken.token == token))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Not found")
    now = datetime.now(UTC)
    return Response(
        svc.to_ics(
            await svc.items(db, row.user_id, now - timedelta(days=30), now + timedelta(days=365))
        ),
        media_type="text/calendar",
    )


# ---- Google Calendar (two-way) ----
def _redirect() -> str:
    return f"{get_settings().web_base_url}/calendar/google/callback"


@router.get("/google/auth-url")
async def google_auth_url(user: CurrentUser) -> dict[str, str]:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(501, "Google OAuth is not configured")
    qs = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": _redirect(),
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": str(user.id),
        }
    )
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"}


class CodeIn(BaseModel):
    code: str


@router.post("/google/connect", response_model=Message)
async def google_connect(body: CodeIn, user: CurrentUser, db: DB) -> Message:
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise HTTPException(501, "Google OAuth is not configured")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": _redirect(),
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise HTTPException(400, "Google rejected the authorization code")
    t = r.json()
    conn = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    ).scalar_one_or_none()
    if conn is None:
        conn = CalendarConnection(user_id=user.id, access_token_enc="")
        db.add(conn)
    conn.access_token_enc = encrypt(t["access_token"])
    if t.get("refresh_token"):
        conn.refresh_token_enc = encrypt(t["refresh_token"])
    conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(t.get("expires_in", 3600)))
    await db.commit()
    return Message(detail="Google Calendar connected")


@router.post("/google/sync")
async def google_sync(user: CurrentUser, db: DB) -> dict[str, int]:
    conn = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(404, "Google Calendar is not connected")
    now = datetime.now(UTC)
    deadlines = [
        i
        for i in await svc.items(db, user.id, now, now + timedelta(days=90))
        if i["kind"].endswith("_due") or i["kind"] == "follow_up"
    ]
    res = await gcal.sync(db, conn, user.id, deadlines)
    await db.commit()
    return res


@router.delete("/google", response_model=Message)
async def google_disconnect(user: CurrentUser, db: DB) -> Message:
    conn = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.user_id == user.id))
    ).scalar_one_or_none()
    if conn:
        await db.delete(conn)
        await db.commit()
    return Message(detail="Disconnected")
