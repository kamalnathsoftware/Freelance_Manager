import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters.registry import ADAPTERS
from app.api.deps import DB, CurrentUser
from app.api.deps_ingest import IngestUser
from app.api.v1.jobs import JobIn, JobOut
from app.core.config import get_settings
from app.core.crypto import encrypt
from app.models import ApiKey, MailConnection, PlatformEvent
from app.schemas import ORM, Message
from app.services import ingest as svc
from app.services.common import get_owned
from app.services.email_parser import parse_email
from app.services.gcal import google_token

router = APIRouter(tags=["ingest"])


class EmailIn(BaseModel):
    sender: str = Field(alias="from")
    subject: str
    body: str = ""
    message_id: str = ""

    model_config = {"populate_by_name": True}


class CaptureIn(BaseModel):
    """What the browser extension sends for the page the user is looking at."""

    kind: str = Field(default="job", pattern="^(job|message)$")
    platform: str
    url: str
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    job: JobIn | None = None
    meta: dict[str, Any] = {}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    revoked: bool
    created_at: datetime


class EventOut(ORM):
    id: uuid.UUID
    platform: str
    kind: str
    title: str
    summary: str
    url: str
    source: str
    meta: dict[str, Any]
    handled: bool
    received_at: datetime


@router.post("/ingest/email")
async def ingest_email(body: EmailIn, user: IngestUser, db: DB) -> dict[str, Any]:
    """Parse a forwarded/connected notification email. Unknown senders/subjects are ignored (never stored)."""
    parsed = parse_email(body.sender, body.subject, body.body, body.message_id)
    if parsed is None:
        return {"ignored": True}
    out = await svc.ingest_parsed_email(db, user.id, parsed)
    await db.commit()
    return out


@router.post("/ingest/capture", response_model=JobOut | EventOut)
async def capture(body: CaptureIn, user: IngestUser, db: DB) -> Any:
    """Save the job post/message the user is viewing (browser extension). User-initiated, one page at a time."""
    if body.platform not in ADAPTERS:
        raise HTTPException(422, f"Unknown platform '{body.platform}'")
    if body.kind == "job":
        data = (body.job.model_dump() if body.job else {}) | {
            "platform": body.platform, "url": body.url, "title": body.title,
            "description": body.description or (body.job.description if body.job else ""),
        }  # fmt: skip
        data["external_id"] = data.get("external_id") or body.url
        job, _ = await svc.upsert_job(db, user.id, data, "extension")
        await db.commit()
        return JobOut.model_validate(job)
    ev, _ = await svc.record_event(
        db, user.id, platform=body.platform, kind="message", title=body.title, summary=body.description[:2000],
        url=body.url, source="extension", dedupe_key=f"ext:{body.url}:{hashlib.sha1(body.description.encode()).hexdigest()[:10]}", meta=body.meta,
    )  # fmt: skip
    await db.commit()
    return EventOut.model_validate(ev)


@router.get("/events", response_model=list[EventOut])
async def events(
    user: CurrentUser, db: DB, kind: str | None = None, platform: str | None = None, limit: int = 50
) -> list[PlatformEvent]:
    stmt = select(PlatformEvent).where(PlatformEvent.user_id == user.id)
    if kind:
        stmt = stmt.where(PlatformEvent.kind == kind)
    if platform:
        stmt = stmt.where(PlatformEvent.platform == platform)
    return list(
        (
            await db.execute(stmt.order_by(PlatformEvent.received_at.desc()).limit(min(limit, 200)))
        ).scalars()
    )


@router.post("/events/{eid}/handled", response_model=EventOut)
async def mark_handled(eid: uuid.UUID, user: CurrentUser, db: DB) -> PlatformEvent:
    ev = await get_owned(db, PlatformEvent, eid, user.id)
    ev.handled = True
    await db.commit()
    return ev


# ---------- API keys ----------
@router.get("/api-keys", response_model=list[KeyOut])
async def list_keys(user: CurrentUser, db: DB) -> list[ApiKey]:
    return list(
        (
            await db.execute(
                select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
            )
        ).scalars()
    )


@router.post("/api-keys", status_code=201)
async def create_key(body: KeyIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    key, raw = await svc.create_api_key(db, user.id, body.name)
    await db.commit()
    return {
        "id": str(key.id),
        "name": key.name,
        "key": raw,
        "note": "Copy this key now - it will not be shown again.",
    }


@router.delete("/api-keys/{kid}", response_model=Message)
async def revoke_key(kid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    (await get_owned(db, ApiKey, kid, user.id)).revoked = True
    await db.commit()
    return Message(detail="Revoked")


# ---------- Gmail connection (OAuth, read-only scope) ----------
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SENDERS_Q = "from:(fiverr.com OR upwork.com OR freelancer.com OR peopleperhour.com OR toptal.com OR guru.com OR linkedin.com OR contra.com)"


def _redirect_uri() -> str:
    return f"{get_settings().web_base_url}/settings/gmail/callback"


@router.get("/ingest/gmail/auth-url")
async def gmail_auth_url(user: CurrentUser) -> dict[str, str]:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(501, "Google OAuth is not configured")
    qs = urlencode({
        "client_id": s.google_client_id, "redirect_uri": _redirect_uri(), "response_type": "code",
        "scope": GMAIL_SCOPE, "access_type": "offline", "prompt": "consent", "state": str(user.id),
    })  # fmt: skip
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"}


class CodeIn(BaseModel):
    code: str


@router.post("/ingest/gmail/connect", response_model=Message)
async def gmail_connect(body: CodeIn, user: CurrentUser, db: DB) -> Message:
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise HTTPException(501, "Google OAuth is not configured")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={
            "code": body.code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": _redirect_uri(), "grant_type": "authorization_code",
        })  # fmt: skip
    if r.status_code != 200:
        raise HTTPException(400, "Google rejected the authorization code")
    t = r.json()
    conn = (
        await db.execute(select(MailConnection).where(MailConnection.user_id == user.id))
    ).scalar_one_or_none()
    if conn is None:
        conn = MailConnection(user_id=user.id, access_token_enc="")
        db.add(conn)
    conn.access_token_enc = encrypt(t["access_token"])
    if t.get("refresh_token"):
        conn.refresh_token_enc = encrypt(t["refresh_token"])
    conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(t.get("expires_in", 3600)))
    await db.commit()
    return Message(detail="Gmail connected")


@router.post("/ingest/gmail/poll")
async def gmail_poll(user: CurrentUser, db: DB) -> dict[str, int]:
    conn = (
        await db.execute(select(MailConnection).where(MailConnection.user_id == user.id))
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(404, "Gmail is not connected")
    n = await poll_gmail(db, conn)
    await db.commit()
    return n


async def poll_gmail(db: Any, conn: MailConnection) -> dict[str, int]:
    """Fetch recent platform notification emails (metadata + snippet only) and ingest them."""
    token = await google_token(db, conn)
    headers = {"Authorization": f"Bearer {token}"}
    base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    seen = ingested = 0
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        r = await c.get(base, params={"q": f"{SENDERS_Q} newer_than:2d", "maxResults": 50})
        if r.status_code == 401:
            raise HTTPException(401, "Gmail token expired; reconnect Gmail")
        r.raise_for_status()
        for m in r.json().get("messages", []):
            mr = await c.get(
                f"{base}/{m['id']}",
                params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
            )
            mr.raise_for_status()
            msg = mr.json()
            hdr = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            seen += 1
            parsed = parse_email(
                hdr.get("from", ""),
                hdr.get("subject", ""),
                msg.get("snippet", ""),
                f"gmail:{m['id']}",
            )
            if parsed:
                res = await svc.ingest_parsed_email(db, conn.user_id, parsed)
                ingested += 0 if res["duplicate"] else 1
    conn.last_polled_at = datetime.now(UTC)
    return {"seen": seen, "ingested": ingested}
