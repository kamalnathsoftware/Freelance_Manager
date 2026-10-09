import asyncio

from celery import Celery
from sqlalchemy import select

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("fm", broker=s.redis_url, backend=s.redis_url)
celery_app.conf.update(
    task_serializer="json",
    timezone="UTC",
    beat_schedule={
        "sync-api-accounts": {"task": "fm.sync_all_api_accounts", "schedule": 15 * 60.0},
    },
)


@celery_app.task(name="fm.ping")
def ping() -> str:
    return "pong"


async def _sync_one(account_id: str) -> str:
    import uuid

    from app.core.db import SessionLocal
    from app.models import PlatformAccount
    from app.services.sync import sync_account

    async with SessionLocal() as db:
        acc = await db.get(PlatformAccount, uuid.UUID(account_id))
        if acc is None:
            return "missing"
        entry = await sync_account(db, acc)
        await db.commit()
        return entry.status


@celery_app.task(
    name="fm.sync_account", autoretry_for=(Exception,), retry_backoff=True, max_retries=3
)
def sync_account_task(account_id: str) -> str:
    return asyncio.run(_sync_one(account_id))


async def _api_account_ids() -> list[str]:
    from app.core.db import SessionLocal
    from app.models import IntegrationMode, PlatformAccount

    async with SessionLocal() as db:
        rows = await db.execute(
            select(PlatformAccount.id).where(PlatformAccount.mode == IntegrationMode.api)
        )
        return [str(r) for r in rows.scalars()]


@celery_app.task(name="fm.sync_all_api_accounts")
def sync_all_api_accounts() -> int:
    ids = asyncio.run(_api_account_ids())
    for i in ids:
        sync_account_task.delay(i)
    return len(ids)
