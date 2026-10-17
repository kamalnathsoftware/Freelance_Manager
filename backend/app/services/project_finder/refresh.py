"""Refresh a user's job feed: fetch -> normalise -> score -> store the relevant new jobs."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PFJob, PFSettings, PFSource, User
from app.services.project_finder import feeds, get_pf_settings
from app.services.project_finder.errors import FeedError
from app.services.project_finder.scoring import score_job

log = logging.getLogger(__name__)
STRONG_MATCH = 70
RESCORE_LIMIT = 5000


@dataclass
class SourceResult:
    key: str
    name: str
    status: str  # ok | error | skipped | paused
    fetched: int = 0
    new: int = 0
    message: str = ""


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


async def ensure_default_sources(db: AsyncSession, user_id: uuid.UUID) -> list[PFSource]:
    """The built-in source list for this user; missing ones (e.g. added in a later release) are created."""
    rows = list((await db.execute(select(PFSource).where(PFSource.user_id == user_id))).scalars())
    have = {r.key for r in rows}
    for spec in feeds.SPECS:
        if spec.key not in have:
            row = PFSource(
                user_id=user_id, key=spec.key, name=spec.name, url=spec.url,
                kind="feed" if spec.fetch else "manual", builtin=True,
            )  # fmt: skip
            db.add(row)
            rows.append(row)
    await db.flush()
    order = {s.key: i for i, s in enumerate(feeds.SPECS)}
    return sorted(rows, key=lambda r: (not r.builtin, order.get(r.key, 999), r.name.lower()))


async def _store(
    db: AsyncSession,
    user_id: uuid.UUID,
    key: str,
    raw: list[feeds.RawJob],
    cfg: PFSettings,
    now: datetime,
) -> tuple[int, int]:
    """Insert new relevant jobs. Returns (new, strong). Existing jobs are left untouched so your
    saved / dismissed choices survive refreshes."""
    batch: dict[str, feeds.RawJob] = {}
    for r in raw:
        if r.external_id and r.title.strip():
            batch.setdefault(r.external_id[:300], r)
    known: set[str] = set()
    ids = list(batch)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        known |= set(
            (
                await db.execute(
                    select(PFJob.external_id).where(
                        PFJob.user_id == user_id,
                        PFJob.source_key == key,
                        PFJob.external_id.in_(chunk),
                    )
                )
            ).scalars()
        )
    new = strong = 0
    for ext_id, r in batch.items():
        if ext_id in known:
            continue
        score, reasons, matched = score_job(
            cfg, title=r.title, description=r.description, tags=r.tags, remote=r.remote,
            budget=r.budget, posted_at=r.posted_at, now=now,
        )  # fmt: skip
        if not matched or score < cfg.min_store_score:
            continue  # not relevant to your skills/keywords: don't clutter the feed
        tags = list(dict.fromkeys([t[:40] for t in r.tags[:15]] + matched))[:25]
        db.add(
            PFJob(
                user_id=user_id, source_key=key, external_id=ext_id, title=r.title[:300],
                company=r.company[:200], description=r.description, budget=r.budget[:120],
                budget_min=r.budget_min, budget_max=r.budget_max, currency=r.currency[:3],
                url=r.url, posted_at=r.posted_at, remote=r.remote, skills=tags,
                fit_score=score, score_reasons=reasons,
            )
        )  # fmt: skip
        new += 1
        strong += score >= STRONG_MATCH
    await db.flush()
    return new, strong


async def refresh_user(
    db: AsyncSession,
    user: User,
    *,
    only: str | None = None,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> list[SourceResult]:
    now = now or datetime.now(UTC)
    cfg = await get_pf_settings(db, user.id)
    sources = await ensure_default_sources(db, user.id)
    own_client = client is None
    http = client or feeds.make_client()
    results: list[SourceResult] = []
    strong_total = 0
    try:
        for src in sources:
            spec = feeds.SPEC_BY_KEY.get(src.key)
            if spec is None or spec.fetch is None or (only and src.key != only):
                continue
            if src.status != "active":
                results.append(
                    SourceResult(src.key, src.name, "paused", message="Source is paused")
                )
                continue
            if src.last_checked_at:
                wait = timedelta(hours=spec.min_interval_hours) - (
                    now - _aware(src.last_checked_at)
                )
                if wait > timedelta(0):
                    mins = int(wait.total_seconds() // 60) + 1
                    msg = f"Checked recently - next refresh allowed in {mins} min"
                    results.append(SourceResult(src.key, src.name, "skipped", message=msg))
                    continue
            try:
                raw = await spec.fetch(http)
                new, strong = await _store(db, user.id, src.key, raw, cfg, now)
            except FeedError as e:
                src.last_result, res = (
                    f"error: {e}"[:300],
                    SourceResult(src.key, src.name, "error", message=str(e)),
                )
            except Exception:  # one broken source must never stop the others
                log.exception("project finder: unexpected error refreshing %s", src.key)
                src.last_result, res = (
                    "error: unexpected failure",
                    SourceResult(src.key, src.name, "error", message="unexpected failure"),
                )
            else:
                strong_total += strong
                src.last_result = f"ok: {len(raw)} fetched, {new} new"[:300]
                res = SourceResult(src.key, src.name, "ok", fetched=len(raw), new=new)
            src.last_checked_at = now  # also after errors: don't hammer a failing site
            results.append(res)
    finally:
        if own_client:
            await http.aclose()
    await db.flush()
    if strong_total:
        from app.services.notifications import emit

        await emit(
            db, user.id, "job_match", f"{strong_total} new strong project match{'es' if strong_total > 1 else ''}",
            body="Open Project Finder to review them.", url="/project-finder/jobs",
            dedupe_key=f"pf_jobs:{user.id}:{now:%Y%m%d%H}",
        )  # fmt: skip
    return results


async def rescore_user(db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> int:
    """Re-score stored jobs after the skills/keywords changed. Never deletes anything."""
    cfg = await get_pf_settings(db, user_id)
    jobs = (
        await db.execute(
            select(PFJob)
            .where(PFJob.user_id == user_id)
            .order_by(PFJob.created_at.desc())
            .limit(RESCORE_LIMIT)
        )
    ).scalars()
    n = 0
    for j in jobs:
        j.fit_score, j.score_reasons, _ = score_job(
            cfg, title=j.title, description=j.description, tags=[t for t in j.skills if isinstance(t, str)],
            remote=j.remote, budget=j.budget, posted_at=j.posted_at, now=now,
        )  # fmt: skip
        n += 1
    await db.flush()
    return n


async def refresh_all(db: AsyncSession) -> int:
    """Scheduled run: every active user who has opened Project Finder. One user failing doesn't affect
    the others (each is committed on its own)."""
    ids = list((await db.execute(select(PFSource.user_id).distinct())).scalars())
    done = 0
    for uid in ids:
        user = await db.get(User, uid)
        if user is None or not user.is_active:
            continue
        try:
            await refresh_user(db, user)
            await db.commit()
            done += 1
        except Exception:
            await db.rollback()
            log.exception("project finder: scheduled refresh failed for user %s", uid)
    return done
