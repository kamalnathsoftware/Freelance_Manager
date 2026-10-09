import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.models import AutomationRun, NotificationDelivery, SyncLog, User

router = APIRouter(prefix="/ops", tags=["ops"])


async def admin_user(user: CurrentUser) -> User:
    if user.email.lower() not in [e.lower() for e in get_settings().admin_emails]:
        raise HTTPException(403, "Admin only")
    return user


Admin = Annotated[User, Depends(admin_user)]


def _celery_workers() -> dict[str, Any]:
    try:
        from app.workers.celery_app import celery_app

        reply = celery_app.control.inspect(timeout=1.0).ping() or {}
        return {"online": len(reply), "workers": sorted(reply)}
    except Exception as e:
        return {"online": 0, "error": type(e).__name__}


@router.get("/overview")
async def overview(_: Admin, db: DB) -> dict[str, Any]:
    """Background-job dashboard: queue health, recent failures. Contains metadata only (no message content)."""
    since = datetime.now(UTC) - timedelta(hours=24)

    async def counts(col: Any, model: Any, time_col: Any) -> dict[str, int]:
        rows = await db.execute(select(col, func.count()).where(time_col >= since).group_by(col))
        return {k: int(n) for k, n in rows.all()}

    deliveries = await counts(
        NotificationDelivery.status, NotificationDelivery, NotificationDelivery.created_at
    )
    runs = await counts(AutomationRun.status, AutomationRun, AutomationRun.created_at)
    syncs = await counts(SyncLog.status, SyncLog, SyncLog.started_at)
    pending = (
        await db.execute(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(NotificationDelivery.status == "pending")
        )
    ).scalar_one()
    failed_d = (
        await db.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.status == "failed")
            .order_by(NotificationDelivery.created_at.desc())
            .limit(20)
        )
    ).scalars()
    bad_runs = (
        await db.execute(
            select(AutomationRun)
            .where(AutomationRun.status == "error")
            .order_by(AutomationRun.created_at.desc())
            .limit(20)
        )
    ).scalars()
    bad_sync = (
        await db.execute(
            select(SyncLog)
            .where(SyncLog.status == "error")
            .order_by(SyncLog.started_at.desc())
            .limit(20)
        )
    ).scalars()
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "db_ok": db_ok, "users": (await db.execute(select(func.count()).select_from(User))).scalar_one(),
        "last_24h": {"deliveries": deliveries, "automation_runs": runs, "syncs": syncs}, "pending_deliveries": pending,
        "celery": await asyncio.to_thread(_celery_workers),
        "recent_failures": {
            "deliveries": [{"id": str(d.id), "channel": d.channel, "attempts": d.attempts, "error": d.error[:200], "at": d.created_at.isoformat()} for d in failed_d],
            "automation_runs": [{"id": str(r.id), "rule_id": str(r.rule_id), "log": [x[:200] for x in r.log], "at": r.created_at.isoformat()} for r in bad_runs],
            "syncs": [{"id": str(s.id), "account_id": str(s.account_id), "message": s.message[:200], "at": s.started_at.isoformat()} for s in bad_sync],
        },
    }  # fmt: skip
