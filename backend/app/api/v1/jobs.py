import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.models import Job, MasterProfile, Proposal, SavedSearch, Stage
from app.schemas import ORM, Message
from app.services import ingest
from app.services.common import get_owned
from app.services.matching import suggest_bid

router = APIRouter(tags=["jobs"])


class JobIn(BaseModel):
    platform: str
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    external_id: str | None = None
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    budget_type: str = Field(default="fixed", pattern="^(fixed|hourly)$")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    skills: list[str] = []
    client: dict[str, Any] = {}
    url: str = ""
    posted_at: datetime | None = None


class JobOut(ORM):
    id: uuid.UUID
    platform: str
    title: str
    description: str
    budget_min: float | None
    budget_max: float | None
    budget_type: str
    currency: str
    skills: list[str]
    client: dict[str, Any]
    url: str
    posted_at: datetime | None
    source: str
    score: int
    score_reasons: list[str]
    dismissed: bool
    created_at: datetime


class SearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: list[str] = []
    skills: list[str] = []
    platforms: list[str] = []
    min_budget: float | None = None
    alert_min_score: int = Field(default=60, ge=0, le=100)
    active: bool = True


class SearchOut(SearchIn, ORM):
    id: uuid.UUID


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    user: CurrentUser, db: DB, platform: str | None = None, min_score: int = 0, source: str | None = None,
    q: str | None = None, include_dismissed: bool = False, limit: int = 50, offset: int = 0,
) -> list[Job]:  # fmt: skip
    stmt = select(Job).where(Job.user_id == user.id, Job.score >= min_score)
    if platform:
        stmt = stmt.where(Job.platform == platform)
    if source:
        stmt = stmt.where(Job.source == source)
    if not include_dismissed:
        stmt = stmt.where(Job.dismissed.is_(False))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.description.ilike(like)))
    stmt = (
        stmt.order_by(Job.score.desc(), Job.created_at.desc()).limit(min(limit, 200)).offset(offset)
    )
    return list((await db.execute(stmt)).scalars())


@router.post("/jobs", response_model=JobOut, status_code=201)
async def add_job(body: JobIn, user: CurrentUser, db: DB) -> Job:
    job, _ = await ingest.upsert_job(db, user.id, body.model_dump(), "manual")
    await db.commit()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, user: CurrentUser, db: DB) -> Job:
    return await get_owned(db, Job, job_id, user.id)


@router.patch("/jobs/{job_id}/dismiss", response_model=JobOut)
async def dismiss(job_id: uuid.UUID, user: CurrentUser, db: DB, dismissed: bool = True) -> Job:
    job = await get_owned(db, Job, job_id, user.id)
    job.dismissed = dismissed
    await db.commit()
    return job


@router.delete("/jobs/{job_id}", response_model=Message)
async def delete_job(job_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Job, job_id, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.get("/jobs/{job_id}/bid-suggestion")
async def bid_suggestion(job_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    job = await get_owned(db, Job, job_id, user.id)
    master = (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == user.id))
    ).scalar_one_or_none()
    return suggest_bid(job, master)


@router.post("/jobs/{job_id}/shortlist")
async def shortlist(job_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    job = await get_owned(db, Job, job_id, user.id)
    p = (
        await db.execute(
            select(Proposal).where(Proposal.job_id == job.id, Proposal.user_id == user.id)
        )
    ).scalar_one_or_none()
    if p is None:
        p = Proposal(user_id=user.id, job_id=job.id, stage=Stage.shortlisted)
        db.add(p)
        await db.flush()
    await db.commit()
    return {"proposal_id": str(p.id), "stage": p.stage.value}


@router.post("/jobs/rescore", response_model=Message)
async def rescore_all(user: CurrentUser, db: DB) -> Message:
    jobs = list((await db.execute(select(Job).where(Job.user_id == user.id))).scalars())
    await ingest.rescore(db, user.id, jobs)
    await db.commit()
    return Message(detail=f"Rescored {len(jobs)} jobs")


@router.get("/searches", response_model=list[SearchOut])
async def list_searches(user: CurrentUser, db: DB) -> list[SavedSearch]:
    return list(
        (await db.execute(select(SavedSearch).where(SavedSearch.user_id == user.id))).scalars()
    )


@router.post("/searches", response_model=SearchOut, status_code=201)
async def add_search(body: SearchIn, user: CurrentUser, db: DB) -> SavedSearch:
    s = SavedSearch(user_id=user.id, **body.model_dump())
    db.add(s)
    await db.commit()
    return s


@router.put("/searches/{sid}", response_model=SearchOut)
async def edit_search(sid: uuid.UUID, body: SearchIn, user: CurrentUser, db: DB) -> SavedSearch:
    s = await get_owned(db, SavedSearch, sid, user.id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    await db.commit()
    return s


@router.delete("/searches/{sid}", response_model=Message)
async def del_search(sid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, SavedSearch, sid, user.id))
    await db.commit()
    return Message(detail="Deleted")
