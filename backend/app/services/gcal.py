"""Google Calendar two-way sync with a dedicated 'Freelance Manager' calendar + Google token refresh."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.models import CalendarConnection, CalendarEvent

API = "https://www.googleapis.com/calendar/v3"


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def google_token(db: AsyncSession, conn: Any) -> str:
    """Return a valid access token for any connection row with access/refresh token columns, refreshing if needed."""
    if conn.expires_at is None or aware(conn.expires_at) > datetime.now(UTC) + timedelta(
        seconds=60
    ):
        return decrypt(conn.access_token_enc)
    if not conn.refresh_token_enc:
        raise HTTPException(401, "Google connection expired; reconnect")
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "refresh_token": decrypt(conn.refresh_token_enc),
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise HTTPException(401, "Google connection expired; reconnect")
    t = r.json()
    conn.access_token_enc = encrypt(t["access_token"])
    conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(t.get("expires_in", 3600)))
    await db.flush()
    return str(t["access_token"])


def _ev_id(local_id: uuid.UUID | str, prefix: str = "fm") -> str:
    return prefix + uuid.UUID(str(local_id)).hex  # Google ids: base32hex chars, 5-1024 long


def _g_body(
    title: str, start: datetime, end: datetime | None, notes: str, local_id: str
) -> dict[str, Any]:
    end = end or (start + timedelta(hours=1))
    return {
        "summary": title, "description": notes,
        "start": {"dateTime": aware(start).isoformat()}, "end": {"dateTime": aware(end).isoformat()},
        "extendedProperties": {"private": {"fm_id": local_id}},
    }  # fmt: skip


async def sync(
    db: AsyncSession, conn: CalendarConnection, user_id: uuid.UUID, deadlines: list[dict[str, Any]]
) -> dict[str, int]:
    """Push local events + deadlines, then pull Google-side changes (last-writer-wins on `updated`)."""
    token = await google_token(db, conn)
    pushed = pulled = 0
    async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {token}"}) as c:
        if not conn.calendar_id:
            r = await c.post(f"{API}/calendars", json={"summary": "Freelance Manager"})
            r.raise_for_status()
            conn.calendar_id = r.json()["id"]
        cal = conn.calendar_id
        since = conn.last_synced_at

        async def upsert(gid: str, body: dict[str, Any]) -> None:
            r = await c.patch(f"{API}/calendars/{cal}/events/{gid}", json=body)
            if r.status_code == 404:
                r = await c.post(f"{API}/calendars/{cal}/events", json={**body, "id": gid})
            r.raise_for_status()

        locals_ = list(
            (
                await db.execute(select(CalendarEvent).where(CalendarEvent.user_id == user_id))
            ).scalars()
        )
        # pull first so Google edits win over stale local data
        params: dict[str, Any] = {"showDeleted": "true", "maxResults": 250}
        if since:
            params["updatedMin"] = aware(since).isoformat()
        r = await c.get(f"{API}/calendars/{cal}/events", params=params)
        r.raise_for_status()
        by_gid = {e.google_event_id: e for e in locals_ if e.google_event_id}
        for ge in r.json().get("items", []):
            fm_id = (ge.get("extendedProperties", {}).get("private", {}) or {}).get("fm_id", "")
            if fm_id.startswith("deadline:"):
                continue  # deadlines are one-way (app -> Google)
            local = by_gid.get(ge["id"])
            if ge.get("status") == "cancelled":
                if local is not None:
                    await db.delete(local)
                    pulled += 1
                continue
            start = ge.get("start", {}).get("dateTime")
            if not start:
                continue  # all-day Google events are not imported
            s_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e_raw = ge.get("end", {}).get("dateTime")
            e_dt = datetime.fromisoformat(e_raw.replace("Z", "+00:00")) if e_raw else None
            g_updated = (
                datetime.fromisoformat(ge["updated"].replace("Z", "+00:00"))
                if ge.get("updated")
                else datetime.now(UTC)
            )
            if local is None:
                new = CalendarEvent(
                    user_id=user_id,
                    title=ge.get("summary", "(no title)"),
                    starts_at=s_dt,
                    ends_at=e_dt,
                    notes=ge.get("description", ""),
                    google_event_id=ge["id"],
                )
                db.add(new)
                locals_.append(new)
                pulled += 1
            elif g_updated > aware(local.updated_at):
                local.title, local.starts_at, local.ends_at, local.notes = (
                    ge.get("summary", local.title),
                    s_dt,
                    e_dt,
                    ge.get("description", ""),
                )
                pulled += 1
        await db.flush()
        for e in locals_:
            if e.google_event_id and since and aware(e.updated_at) <= aware(since):
                continue  # unchanged since last sync
            gid = e.google_event_id or _ev_id(e.id)
            await upsert(gid, _g_body(e.title, e.starts_at, e.ends_at, e.notes, str(e.id)))
            e.google_event_id = gid
            pushed += 1
        for d in deadlines:
            await upsert(
                _ev_id(uuid.uuid5(uuid.NAMESPACE_URL, d["id"]), "fd"),
                _g_body(
                    d["title"],
                    d["start"],
                    None,
                    f"Freelance Manager: {d['kind']}",
                    f"deadline:{d['id']}",
                ),
            )
            pushed += 1
    conn.last_synced_at = datetime.now(UTC)
    await db.flush()
    return {"pushed": pushed, "pulled": pulled}
