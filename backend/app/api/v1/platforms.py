import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters.registry import ADAPTERS, get_adapter
from app.adapters.rules import RULES
from app.api.deps import DB, CurrentUser
from app.core.crypto import encrypt
from app.models import (
    AccountStatus,
    IntegrationMode,
    IntegrationToken,
    PlatformAccount,
    SyncLog,
)
from app.schemas import ORM, Message
from app.services.audit import audit
from app.services.common import get_owned
from app.services.sync import sync_account

router = APIRouter(prefix="/platforms", tags=["platforms"])


class PlatformInfo(BaseModel):
    key: str
    name: str
    tier: str
    capabilities: list[str]
    rules: dict[str, int]
    deep_links: dict[str, str]


class AccountIn(BaseModel):
    platform: str
    label: str = Field(default="", max_length=120)
    username: str = Field(default="", max_length=120)
    profile_url: str = Field(default="", max_length=500)


class AccountUpdate(BaseModel):
    label: str | None = None
    username: str | None = None
    profile_url: str | None = None
    stats: dict[str, Any] | None = (
        None  # manual entry: unread, active_orders, pending_bids, earnings
    )


class ConnectIn(BaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    scopes: str = ""


class AccountOut(ORM):
    id: uuid.UUID
    platform: str
    label: str
    username: str
    profile_url: str
    mode: IntegrationMode
    status: AccountStatus
    last_synced_at: datetime | None
    last_error: str
    stats: dict[str, Any]
    integration_status: str = ""


class SyncLogOut(ORM):
    id: uuid.UUID
    kind: str
    status: str
    message: str
    started_at: datetime
    finished_at: datetime | None


_STATUS_TEXT = {
    IntegrationMode.api: "Connected via API",
    IntegrationMode.email: "Via email",
    IntegrationMode.manual: "Manual",
}


def _out(a: PlatformAccount) -> AccountOut:
    o = AccountOut.model_validate(a)
    o.integration_status = _STATUS_TEXT[a.mode]
    return o


@router.get("/catalog", response_model=list[PlatformInfo])
async def catalog() -> list[PlatformInfo]:
    return [
        PlatformInfo(
            key=a.key,
            name=a.display_name,
            tier=a.tier,
            capabilities=sorted(c.value for c in a.capabilities()),
            rules=RULES[a.key].as_dict(),
            deep_links=a.deep_links,
        )
        for a in ADAPTERS.values()
    ]


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(user: CurrentUser, db: DB) -> list[AccountOut]:
    rows = (
        await db.execute(
            select(PlatformAccount)
            .where(PlatformAccount.user_id == user.id)
            .order_by(PlatformAccount.created_at)
        )
    ).scalars()
    return [_out(a) for a in rows]


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def add_account(body: AccountIn, user: CurrentUser, db: DB) -> AccountOut:
    if body.platform not in ADAPTERS:
        raise HTTPException(422, f"Unknown platform '{body.platform}'")
    adapter = get_adapter(body.platform)
    mode = {"api": IntegrationMode.manual, "email": IntegrationMode.email}.get(
        adapter.tier, IntegrationMode.manual
    )  # api accounts become 'api' once a token is connected
    acc = PlatformAccount(
        user_id=user.id,
        platform=body.platform,
        label=body.label or adapter.display_name,
        username=body.username,
        profile_url=body.profile_url,
        mode=mode,
        status=AccountStatus.connected if mode != IntegrationMode.manual else AccountStatus.pending,
    )
    db.add(acc)
    await db.flush()
    await audit(db, user.id, "platform.account_added", platform=body.platform)
    await db.commit()
    return _out(acc)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID, body: AccountUpdate, user: CurrentUser, db: DB
) -> AccountOut:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(acc, k, v)
    await db.commit()
    return _out(acc)


@router.put("/accounts/{account_id}/token", response_model=AccountOut)
async def connect_token(
    account_id: uuid.UUID, body: ConnectIn, user: CurrentUser, db: DB
) -> AccountOut:
    """Store an OAuth/API token (encrypted). Only API-tier platforms accept tokens."""
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    if get_adapter(acc.platform).tier != "api":
        raise HTTPException(
            400, f"{acc.platform} has no public API; use email ingestion or manual mode"
        )
    tok = (
        await db.execute(select(IntegrationToken).where(IntegrationToken.account_id == acc.id))
    ).scalar_one_or_none()
    if tok is None:
        tok = IntegrationToken(account_id=acc.id, access_token_enc="")
        db.add(tok)
    tok.access_token_enc = encrypt(body.access_token)
    tok.refresh_token_enc = encrypt(body.refresh_token) if body.refresh_token else None
    tok.scopes = body.scopes
    acc.mode, acc.status = IntegrationMode.api, AccountStatus.connected
    await audit(db, user.id, "platform.token_connected", platform=acc.platform)
    await db.commit()
    return _out(acc)


@router.delete("/accounts/{account_id}", response_model=Message)
async def disconnect(account_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    await audit(db, user.id, "platform.account_removed", platform=acc.platform)
    await db.delete(acc)
    await db.commit()
    return Message(detail="Account removed")


@router.post("/accounts/{account_id}/sync", response_model=SyncLogOut)
async def sync_now(account_id: uuid.UUID, user: CurrentUser, db: DB) -> SyncLog:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    entry = await sync_account(db, acc)
    await db.commit()
    return entry


@router.get("/accounts/{account_id}/logs", response_model=list[SyncLogOut])
async def sync_logs(account_id: uuid.UUID, user: CurrentUser, db: DB) -> list[SyncLogOut]:
    await get_owned(db, PlatformAccount, account_id, user.id)
    rows = (
        await db.execute(
            select(SyncLog)
            .where(SyncLog.account_id == account_id)
            .order_by(SyncLog.started_at.desc())
            .limit(50)
        )
    ).scalars()
    return [SyncLogOut.model_validate(r) for r in rows]
