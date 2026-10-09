"""Turn parsed emails / extension captures into jobs and platform events (idempotent)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models import (
    ApiKey,
    Job,
    MasterProfile,
    PlatformAccount,
    PlatformEvent,
    Proposal,
    SavedSearch,
    Stage,
)
from app.services import inbox, notifications, orders
from app.services.email_parser import ParsedEmail
from app.services.matching import score_job


async def won_platforms(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    rows = await db.execute(
        select(Job.platform)
        .join(Proposal, Proposal.job_id == Job.id)
        .where(Proposal.user_id == user_id, Proposal.stage == Stage.won)
    )
    return set(rows.scalars())


async def rescore(db: AsyncSession, user_id: uuid.UUID, jobs: list[Job]) -> None:
    master = (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == user_id))
    ).scalar_one_or_none()
    searches = list(
        (await db.execute(select(SavedSearch).where(SavedSearch.user_id == user_id))).scalars()
    )
    wins = await won_platforms(db, user_id)
    for j in jobs:
        j.score, j.score_reasons = score_job(j, master, searches, wins)


async def upsert_job(
    db: AsyncSession, user_id: uuid.UUID, data: dict[str, Any], source: str
) -> tuple[Job, bool]:
    ext = (
        data.get("external_id")
        or data.get("url")
        or hashlib.sha1(f"{data['title']}".encode()).hexdigest()[:16]
    )
    job = (
        await db.execute(
            select(Job).where(
                Job.user_id == user_id, Job.platform == data["platform"], Job.external_id == ext
            )
        )
    ).scalar_one_or_none()
    created = job is None
    if job is None:
        job = Job(
            user_id=user_id,
            platform=data["platform"],
            external_id=ext,
            title=data["title"],
            source=source,
        )
        db.add(job)
    for k in (
        "title",
        "description",
        "budget_min",
        "budget_max",
        "budget_type",
        "currency",
        "skills",
        "client",
        "url",
        "posted_at",
    ):
        if data.get(k) is not None:
            setattr(job, k, data[k])
    await rescore(db, user_id, [job])
    await db.flush()
    if created:
        await maybe_alert(db, user_id, job)
    return job, created


async def maybe_alert(db: AsyncSession, user_id: uuid.UUID, job: Job) -> None:
    """Emit a job_match event when a new job clears an active saved search's alert threshold."""
    searches = (
        await db.execute(
            select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.active.is_(True))
        )
    ).scalars()
    for s in searches:
        if s.platforms and job.platform not in s.platforms:
            continue
        if s.min_budget and (job.budget_max or job.budget_min or 0) < s.min_budget:
            continue
        text = f"{job.title} {job.description}".lower()
        if (
            not s.keywords or any(k.lower() in text for k in s.keywords)
        ) and job.score >= s.alert_min_score:
            await record_event(
                db, user_id, platform=job.platform, kind="job_match", title=job.title, summary=f"{job.score}% match for '{s.name}'",
                url=job.url, source="match", dedupe_key=f"jobmatch:{job.id}:{s.id}", meta={"job_id": str(job.id), "score": job.score},
            )  # fmt: skip


async def record_event(db: AsyncSession, user_id: uuid.UUID, *, platform: str, kind: str, title: str, summary: str = "",
                       url: str = "", source: str = "email", dedupe_key: str, meta: dict[str, Any] | None = None) -> tuple[PlatformEvent, bool]:  # fmt: skip
    ev = (
        await db.execute(
            select(PlatformEvent).where(
                PlatformEvent.user_id == user_id, PlatformEvent.dedupe_key == dedupe_key
            )
        )
    ).scalar_one_or_none()
    if ev is not None:
        return ev, False
    acc = (
        await db.execute(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user_id, PlatformAccount.platform == platform)
            .limit(1)
        )
    ).scalar_one_or_none()
    ev = PlatformEvent(user_id=user_id, account_id=acc.id if acc else None, platform=platform, kind=kind, title=title,
                       summary=summary, url=url, source=source, dedupe_key=dedupe_key, meta=meta or {})  # fmt: skip
    db.add(ev)
    if kind == "message":
        await route_message_event(db, user_id, ev)
    if acc is not None and kind in ("message", "order", "offer"):
        stats = dict(acc.stats or {})
        field = {"message": "unread", "order": "active_orders", "offer": "pending_bids"}[kind]
        stats[field] = int(stats.get(field, 0)) + 1
        acc.stats = stats
    await db.flush()
    await orders.apply_platform_event(db, user_id, ev)
    ntype = notifications.PLATFORM_EVENT_TYPE.get(kind)
    if ntype:
        await notifications.emit(
            db, user_id, ntype, title or kind.replace("_", " ").title(), body=summary[:300], url=url or "/jobs",
            data={"platform": platform, "event_id": str(ev.id), **(meta or {})}, dedupe_key=f"pev:{ev.id}",
        )  # fmt: skip
    return ev, True


async def ingest_parsed_email(
    db: AsyncSession, user_id: uuid.UUID, p: ParsedEmail
) -> dict[str, Any]:
    ev, created = await record_event(
        db, user_id, platform=p.platform, kind=p.kind, title=p.title, summary=p.summary, url=p.url,
        dedupe_key=p.dedupe_key, meta=p.meta,
    )  # fmt: skip
    out: dict[str, Any] = {
        "event_id": str(ev.id),
        "kind": p.kind,
        "platform": p.platform,
        "duplicate": not created,
    }
    if p.kind == "job_invite" and created:
        job, _ = await upsert_job(
            db, user_id, {"platform": p.platform, "title": p.title, "description": p.summary, "url": p.url,
                          "external_id": p.url or p.dedupe_key, "posted_at": datetime.now(UTC)}, "email",
        )  # fmt: skip
        out["job_id"] = str(job.id)
    return out


# ---- API keys (extension) ----
async def create_api_key(db: AsyncSession, user_id: uuid.UUID, name: str) -> tuple[ApiKey, str]:
    raw = "fmk_" + secrets.token_urlsafe(32)
    key = ApiKey(user_id=user_id, name=name, prefix=raw[:8], key_hash=hash_token(raw))
    db.add(key)
    await db.flush()
    return key, raw


async def resolve_api_key(db: AsyncSession, raw: str) -> ApiKey | None:
    key = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if key is None or key.revoked:
        return None
    key.last_used_at = datetime.now(UTC)
    return key


async def route_message_event(db: AsyncSession, user_id: uuid.UUID, ev: PlatformEvent) -> None:
    """Every inbound platform message becomes (part of) a conversation in the unified inbox."""
    who = str(ev.meta.get("counterparty") or "").strip()
    handle = who or ev.url or ev.title
    client = await inbox.resolve_client(db, user_id, ev.platform, handle, name=who)
    key = (f"{who.lower()}" if who else ev.url or ev.title)[:200]
    conv, _ = await inbox.get_or_create_conversation(
        db, user_id, ev.platform, key, subject=ev.title, client=client, platform_url=ev.url
    )
    await inbox.add_inbound(
        db,
        conv,
        ev.summary or ev.title,
        sender=who,
        source=ev.source,
        external_key=ev.dedupe_key[:100],
    )
