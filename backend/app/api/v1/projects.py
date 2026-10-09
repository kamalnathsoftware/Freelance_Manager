import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.models import Project, Task, TimeEntry
from app.schemas import ORM, Message
from app.services.common import get_owned

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    client_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    status: str = Field(default="active", pattern="^(active|paused|done)$")
    hourly_rate: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ProjectOut(ProjectIn, ORM):
    id: uuid.UUID
    created_at: datetime
    hours_tracked: float = 0
    tasks_total: int = 0
    tasks_done: int = 0


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    status: str = Field(default="todo", pattern="^(todo|doing|done)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_at: datetime | None = None


class TaskOut(TaskIn, ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    position: int


class StartIn(BaseModel):
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    note: str = ""
    billable: bool = True


class ManualTime(BaseModel):
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    started_at: datetime
    minutes: int = Field(gt=0, le=24 * 60)
    note: str = ""
    billable: bool = True


class TimeOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    started_at: datetime
    ended_at: datetime | None
    note: str
    billable: bool
    invoice_id: uuid.UUID | None
    minutes: float = 0


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def minutes_of(e: TimeEntry, now: datetime | None = None) -> float:
    end = _aware(e.ended_at) if e.ended_at else (now or datetime.now(UTC))
    return max(0.0, (end - _aware(e.started_at)).total_seconds() / 60)


def _t(e: TimeEntry) -> TimeOut:
    o = TimeOut.model_validate(e)
    o.minutes = round(minutes_of(e), 1)
    return o


async def _p_out(db: DB, p: Project) -> ProjectOut:
    o = ProjectOut.model_validate(p)
    entries = (await db.execute(select(TimeEntry).where(TimeEntry.project_id == p.id))).scalars()
    o.hours_tracked = round(sum(minutes_of(e) for e in entries) / 60, 2)
    tasks = list((await db.execute(select(Task.status).where(Task.project_id == p.id))).scalars())
    o.tasks_total, o.tasks_done = len(tasks), sum(1 for s in tasks if s == "done")
    return o


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DB, status: str | None = None) -> list[ProjectOut]:
    stmt = select(Project).where(Project.user_id == user.id)
    if status:
        stmt = stmt.where(Project.status == status)
    return [
        await _p_out(db, p)
        for p in (await db.execute(stmt.order_by(Project.created_at.desc()))).scalars()
    ]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectIn, user: CurrentUser, db: DB) -> ProjectOut:
    p = Project(user_id=user.id, **body.model_dump())
    db.add(p)
    await db.commit()
    return await _p_out(db, p)


@router.put("/projects/{pid}", response_model=ProjectOut)
async def update_project(pid: uuid.UUID, body: ProjectIn, user: CurrentUser, db: DB) -> ProjectOut:
    p = await get_owned(db, Project, pid, user.id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await db.commit()
    return await _p_out(db, p)


@router.delete("/projects/{pid}", response_model=Message)
async def delete_project(pid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Project, pid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.get("/projects/{pid}/tasks", response_model=list[TaskOut])
async def list_tasks(pid: uuid.UUID, user: CurrentUser, db: DB) -> list[Task]:
    await get_owned(db, Project, pid, user.id)
    return list(
        (
            await db.execute(
                select(Task).where(Task.project_id == pid).order_by(Task.position, Task.created_at)
            )
        ).scalars()
    )


@router.post("/projects/{pid}/tasks", response_model=TaskOut, status_code=201)
async def add_task(pid: uuid.UUID, body: TaskIn, user: CurrentUser, db: DB) -> Task:
    await get_owned(db, Project, pid, user.id)
    top = (
        await db.execute(
            select(func.max(Task.position)).where(
                Task.project_id == pid, Task.status == body.status
            )
        )
    ).scalar()
    t = Task(
        user_id=user.id,
        project_id=pid,
        position=(top if top is not None else -1) + 1,
        **body.model_dump(),
    )
    db.add(t)
    await db.commit()
    return t


@router.put("/tasks/{tid}", response_model=TaskOut)
async def update_task(tid: uuid.UUID, body: TaskIn, user: CurrentUser, db: DB) -> Task:
    t = await get_owned(db, Task, tid, user.id)
    if body.status != t.status:
        top = (
            await db.execute(
                select(func.max(Task.position)).where(
                    Task.project_id == t.project_id, Task.status == body.status
                )
            )
        ).scalar()
        t.position = (top if top is not None else -1) + 1
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    return t


@router.delete("/tasks/{tid}", response_model=Message)
async def delete_task(tid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Task, tid, user.id))
    await db.commit()
    return Message(detail="Deleted")


# ---------- time tracking ----------
async def _running(db: DB, user_id: uuid.UUID) -> TimeEntry | None:
    return (
        (
            await db.execute(
                select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None))
            )
        )
        .scalars()
        .first()
    )


@router.get("/time/running", response_model=TimeOut | None)
async def running(user: CurrentUser, db: DB) -> TimeOut | None:
    e = await _running(db, user.id)
    return _t(e) if e else None


@router.post("/time/start", response_model=TimeOut, status_code=201)
async def start_timer(body: StartIn, user: CurrentUser, db: DB) -> TimeOut:
    """One timer at a time: starting a new one stops the running one."""
    if body.project_id:
        await get_owned(db, Project, body.project_id, user.id)
    if body.task_id:
        await get_owned(db, Task, body.task_id, user.id)
    cur = await _running(db, user.id)
    if cur:
        cur.ended_at = datetime.now(UTC)
    e = TimeEntry(user_id=user.id, **body.model_dump())
    db.add(e)
    await db.commit()
    return _t(e)


@router.post("/time/stop", response_model=TimeOut)
async def stop_timer(user: CurrentUser, db: DB) -> TimeOut:
    e = await _running(db, user.id)
    if e is None:
        raise HTTPException(409, "No timer is running")
    e.ended_at = datetime.now(UTC)
    await db.commit()
    return _t(e)


@router.post("/time", response_model=TimeOut, status_code=201)
async def manual_entry(body: ManualTime, user: CurrentUser, db: DB) -> TimeOut:
    if body.project_id:
        await get_owned(db, Project, body.project_id, user.id)
    e = TimeEntry(
        user_id=user.id, project_id=body.project_id, task_id=body.task_id, started_at=body.started_at,
        ended_at=body.started_at + timedelta(minutes=body.minutes), note=body.note, billable=body.billable,
    )  # fmt: skip
    db.add(e)
    await db.commit()
    return _t(e)


@router.delete("/time/{eid}", response_model=Message)
async def delete_entry(eid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    e = await get_owned(db, TimeEntry, eid, user.id)
    if e.invoice_id:
        raise HTTPException(409, "This entry is already on an invoice")
    await db.delete(e)
    await db.commit()
    return Message(detail="Deleted")


async def _entries(
    db: DB, uid: uuid.UUID, project_id: uuid.UUID | None, start: date | None, end: date | None
) -> list[TimeEntry]:
    stmt = select(TimeEntry).where(TimeEntry.user_id == uid)
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)
    if start:
        stmt = stmt.where(TimeEntry.started_at >= datetime.combine(start, datetime.min.time(), UTC))
    if end:
        stmt = stmt.where(
            TimeEntry.started_at
            < datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
        )
    return list((await db.execute(stmt.order_by(TimeEntry.started_at.desc()))).scalars())


@router.get("/time", response_model=list[TimeOut])
async def list_time(
    user: CurrentUser,
    db: DB,
    project_id: uuid.UUID | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[TimeOut]:
    return [_t(e) for e in await _entries(db, user.id, project_id, start, end)]


@router.get("/time/summary")
async def time_summary(
    user: CurrentUser, db: DB, start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    entries = await _entries(db, user.id, None, start, end)
    projects = {
        p.id: p
        for p in (await db.execute(select(Project).where(Project.user_id == user.id))).scalars()
    }
    per: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = str(e.project_id) if e.project_id else "none"
        p = projects.get(e.project_id) if e.project_id else None
        row = per.setdefault(
            key,
            {
                "project_id": key,
                "name": p.name if p else "No project",
                "minutes": 0.0,
                "billable_minutes": 0.0,
                "billable_amount": 0.0,
            },
        )
        m = minutes_of(e)
        row["minutes"] += m
        if e.billable:
            row["billable_minutes"] += m
            row["billable_amount"] += m / 60 * (p.hourly_rate or 0 if p else 0)
    rows = [
        {
            **r,
            "minutes": round(r["minutes"]),
            "billable_minutes": round(r["billable_minutes"]),
            "billable_amount": round(r["billable_amount"], 2),
        }
        for r in per.values()
    ]
    return {"total_minutes": sum(r["minutes"] for r in rows), "projects": rows}


@router.get("/time/export")
async def timesheet_csv(
    user: CurrentUser,
    db: DB,
    project_id: uuid.UUID | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Response:
    projects = {
        p.id: p.name
        for p in (await db.execute(select(Project).where(Project.user_id == user.id))).scalars()
    }
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "project", "note", "start", "end", "hours", "billable", "invoiced"])
    for e in reversed(await _entries(db, user.id, project_id, start, end)):
        w.writerow([_aware(e.started_at).date().isoformat(), projects.get(e.project_id, "") if e.project_id else "", e.note, _aware(e.started_at).isoformat(timespec="minutes"),
                    _aware(e.ended_at).isoformat(timespec="minutes") if e.ended_at else "", round(minutes_of(e) / 60, 2), "yes" if e.billable else "no", "yes" if e.invoice_id else "no"])  # fmt: skip
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="timesheet.csv"'},
    )
