import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterContext, Capability, NotConfiguredError, NotSupportedError
from app.adapters.registry import get_adapter
from app.core.crypto import decrypt
from app.models import AccountStatus, IntegrationMode, IntegrationToken, PlatformAccount, SyncLog

log = logging.getLogger(__name__)


async def context_for(db: AsyncSession, acc: PlatformAccount) -> AdapterContext:
    tok = (
        await db.execute(select(IntegrationToken).where(IntegrationToken.account_id == acc.id))
    ).scalar_one_or_none()
    return AdapterContext(
        account_id=str(acc.id),
        access_token=decrypt(tok.access_token_enc) if tok else None,
        refresh_token=decrypt(tok.refresh_token_enc) if tok and tok.refresh_token_enc else None,
        extra={"username": acc.username},
    )


async def sync_account(db: AsyncSession, acc: PlatformAccount) -> SyncLog:
    """Run a profile sync for one account, recording a SyncLog. Never raises for adapter errors."""
    adapter = get_adapter(acc.platform)
    entry = SyncLog(account_id=acc.id, kind="profile", status="running")
    db.add(entry)
    try:
        if acc.mode != IntegrationMode.api or not adapter.supports(Capability.sync_profile):
            entry.status, entry.message = (
                "skipped",
                "No API sync for this account (email/manual mode)",
            )
        else:
            data = await adapter.sync_profile(await context_for(db, acc))
            acc.username = data.username or acc.username
            acc.profile_url = data.profile_url or acc.profile_url
            acc.status, acc.last_error = AccountStatus.connected, ""
            entry.status, entry.message = "ok", "Profile synced"
    except (NotConfiguredError, NotSupportedError) as e:
        entry.status, entry.message = "skipped", str(e)
    except Exception as e:  # network / provider errors surface in the UI with retry
        log.exception("sync failed account=%s", acc.id)
        acc.status, acc.last_error = AccountStatus.error, str(e)[:500]
        entry.status, entry.message = "error", str(e)[:500]
    entry.finished_at = datetime.now(UTC)
    acc.last_synced_at = entry.finished_at
    await db.flush()
    return entry
