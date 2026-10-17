from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.services.project_finder import stats as svc

router = APIRouter(tags=["project-finder"])


@router.get("/stats")
async def stats(
    user: CurrentUser, db: DB, days: int | None = Query(None, ge=1, le=3650)
) -> dict[str, Any]:
    """Proposal reply/win rates, earnings and best-performing source, lead funnel and outreach activity.
    `days` limits proposals to those sent in the last N days (default: all time)."""
    out = await svc.compute(db, user, days)
    await db.commit()  # persists the default settings row when first read
    return out
