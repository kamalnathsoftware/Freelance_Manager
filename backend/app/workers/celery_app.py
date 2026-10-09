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
        "deliver-due-notifications": {"task": "fm.deliver_due", "schedule": 60.0},
        "flush-digests": {"task": "fm.flush_digests", "schedule": 3600.0},
        "scan-reminders": {"task": "fm.scan_reminders", "schedule": 5 * 60.0},
        "scan-automations": {"task": "fm.scan_automations", "schedule": 10 * 60.0},
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


async def _with_db(fn):  # type: ignore[no-untyped-def]
    from app.core.db import SessionLocal

    async with SessionLocal() as db:
        out = await fn(db)
        await db.commit()
        return out


@celery_app.task(name="fm.deliver_due")
def deliver_due() -> int:
    from app.services.notifications import process_due

    return asyncio.run(_with_db(process_due))


@celery_app.task(name="fm.flush_digests")
def flush_digests_task() -> int:
    from app.services.notifications import flush_digests

    return asyncio.run(_with_db(flush_digests))


@celery_app.task(name="fm.scan_reminders")
def scan_reminders_task() -> int:
    from app.services.notifications import scan_reminders

    return asyncio.run(_with_db(scan_reminders))


@celery_app.task(name="fm.scan_automations")
def scan_automations_task() -> int:
    from app.services.automation import scan_stale

    return asyncio.run(_with_db(scan_stale))
