from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.services import analytics as svc

router = APIRouter(tags=["analytics"])


class GoalsIn(BaseModel):
    monthly_income: float = Field(default=0, ge=0)
    yearly_income: float = Field(default=0, ge=0)
    weekly_hours: float = Field(default=40, gt=0, le=168)


@router.get("/analytics/overview")
async def overview(
    user: CurrentUser, db: DB, days: int = 30, granularity: str = "day"
) -> dict[str, Any]:
    if not 1 <= days <= 366:
        raise HTTPException(422, "days must be between 1 and 366")
    if granularity not in ("day", "week", "month"):
        raise HTTPException(422, "granularity must be day, week or month")
    return await svc.overview(db, user, days, granularity)


@router.get("/goals")
async def get_goals(user: CurrentUser, db: DB) -> dict[str, Any]:
    return await svc.goal_progress(db, user)


@router.put("/goals")
async def put_goals(body: GoalsIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    user.settings = {**(user.settings or {}), "goals": body.model_dump()}
    await db.commit()
    return await svc.goal_progress(db, user)


@router.get("/analytics/report.pdf")
async def report_pdf(user: CurrentUser, db: DB, days: int = 30) -> Response:
    if not 1 <= days <= 366:
        raise HTTPException(422, "days must be between 1 and 366")
    ov = await svc.overview(db, user, days, "week" if days > 60 else "day")
    gp = await svc.goal_progress(db, user)
    return Response(
        svc.report_pdf(user, ov, gp),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="business-report.pdf"'},
    )
