import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.leads import LeadOut
from app.api.v1.project_finder.leads import out as lead_out
from app.models import PFJob, PFLead
from app.schemas import ORM
from app.services.common import get_owned
from app.services.project_finder import refresh as svc
from app.services.project_finder.feeds import SPEC_BY_KEY
from app.services.project_finder.outreach import today_for

router = APIRouter(tags=["project-finder"])


class JobOut(ORM):
    id: uuid.UUID
    source_key: str
    source_name: str = ""
    title: str
    company: str
    description: str
    budget: str
    budget_min: float | None
    budget_max: float | None
    currency: str
    url: str
    posted_at: datetime | None
    remote: bool
    skills: list[str]
    fit_score: int
    score_reasons: list[str]
    status: str
    created_at: datetime


class JobPatch(BaseModel):
    status: Literal["new", "saved", "dismissed"]


class RefreshIn(BaseModel):
    source: str | None = None


class ResultOut(BaseModel):
    key: str
    name: str
    status: str
    fetched: int
    new: int
    message: str


def out(j: PFJob) -> JobOut:
    o = JobOut.model_validate(j)
    spec = SPEC_BY_KEY.get(j.source_key)
    o.source_name = spec.name if spec else j.source_key
    return o


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    user: CurrentUser,
    db: DB,
    q: str | None = None,
    keywords: str | None = Query(None, description="Comma-separated; a job matches if it has any"),
    source: str | None = None,
    min_score: int = Query(0, ge=0, le=100),
    remote: bool | None = None,
    status: Literal["active", "new", "saved", "dismissed"] = "active",
    sort: Literal["score", "date"] = "score",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[JobOut]:
    stmt = select(PFJob).where(PFJob.user_id == user.id, PFJob.fit_score >= min_score)
    stmt = stmt.where(PFJob.status != "dismissed" if status == "active" else PFJob.status == status)
    if source:
        stmt = stmt.where(PFJob.source_key == source)
    if remote is not None:
        stmt = stmt.where(PFJob.remote.is_(remote))

    def hit(term: str):  # type: ignore[no-untyped-def]
        like = f"%{term.strip()}%"
        return or_(
            PFJob.title.ilike(like), PFJob.company.ilike(like), PFJob.description.ilike(like)
        )

    if q and q.strip():
        stmt = stmt.where(hit(q))
    terms = [k for k in (keywords or "").split(",") if k.strip()][:10]
    if terms:
        stmt = stmt.where(or_(*[hit(k) for k in terms]))
    order: list[Any] = (
        [PFJob.fit_score.desc(), PFJob.posted_at.desc()]
        if sort == "score"
        else [PFJob.posted_at.is_(None), PFJob.posted_at.desc(), PFJob.created_at.desc()]
    )
    rows = (await db.execute(stmt.order_by(*order).limit(limit).offset(offset))).scalars()
    return [out(r) for r in rows]


@router.post("/jobs/refresh", response_model=list[ResultOut])
async def refresh(body: RefreshIn, user: CurrentUser, db: DB) -> list[ResultOut]:
    """Fetch the public feeds now. Each source is rate-limited, so repeated clicks are harmless."""
    if body.source:
        spec = SPEC_BY_KEY.get(body.source)
        if spec is None or spec.fetch is None:
            raise HTTPException(404, "That source has no automatic feed")
    results = await svc.refresh_user(db, user, only=body.source)
    await db.commit()
    return [ResultOut(**r.__dict__) for r in results]


@router.post("/jobs/rescore")
async def rescore(user: CurrentUser, db: DB) -> dict[str, int]:
    n = await svc.rescore_user(db, user.id)
    await db.commit()
    return {"rescored": n}


@router.patch("/jobs/{job_id}", response_model=JobOut)
async def update_job(job_id: uuid.UUID, body: JobPatch, user: CurrentUser, db: DB) -> JobOut:
    j = await get_owned(db, PFJob, job_id, user.id)
    j.status = body.status
    await db.commit()
    return out(j)


@router.post("/jobs/{job_id}/to-lead", response_model=LeadOut, status_code=201)
async def job_to_lead(job_id: uuid.UUID, user: CurrentUser, db: DB) -> LeadOut:
    """Turn a job into a lead you can work in the CRM. Idempotent: returns the existing lead if there is one."""
    j = await get_owned(db, PFJob, job_id, user.id)
    lead = (
        (await db.execute(select(PFLead).where(PFLead.user_id == user.id, PFLead.job_id == j.id)))
        .scalars()
        .first()
    )
    if lead is None:
        spec = SPEC_BY_KEY.get(j.source_key)
        lead = PFLead(
            user_id=user.id, business_name=(j.company or j.title)[:200], source=(spec.name if spec else j.source_key)[:80],
            problem=j.title[:5000], notes=f"{j.url}\n\n{j.description[:1500]}".strip(), job_id=j.id,
            currency=j.currency if j.budget else "",
        )  # fmt: skip
        db.add(lead)
    if j.status == "new":
        j.status = "saved"
    await db.commit()
    return lead_out(lead, today_for(user))
