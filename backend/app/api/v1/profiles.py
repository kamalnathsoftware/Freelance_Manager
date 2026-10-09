import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters.rules import RULES
from app.api.deps import DB, CurrentUser
from app.core.crypto import decrypt, encrypt
from app.models import MasterProfile, PlatformAccount, PlatformProfile, PortfolioItem
from app.schemas import ORM, Message
from app.services import profiles as svc
from app.services.common import get_owned

router = APIRouter(tags=["profiles"])


class MasterIn(BaseModel):
    name: str = ""
    headline: str = Field(default="", max_length=300)
    bio: str = ""
    skills: list[str] = []
    languages: list[str] = []
    hourly_rate: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    location: str = ""
    timezone: str = ""
    availability: str = ""
    certifications: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    experience: list[dict[str, Any]] = []


class MasterOut(MasterIn, ORM):
    updated_at: datetime


class PlatformProfileIn(BaseModel):
    headline: str | None = None
    bio: str | None = None
    skills: list[str] | None = None
    hourly_rate: float | None = None


class PlatformProfileOut(BaseModel):
    account_id: uuid.UUID
    platform: str
    headline: str
    bio: str
    skills: list[str]
    hourly_rate: float | None
    sync_status: str
    rules: dict[str, int]
    violations: list[str]


class PortfolioIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="link", pattern="^(image|video|link|case_study)$")
    url: str = ""
    description: str = ""
    tags: list[str] = []


class PortfolioOut(PortfolioIn, ORM):
    id: uuid.UUID


async def _master(db: DB, user_id: uuid.UUID) -> MasterProfile | None:
    return (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == user_id))
    ).scalar_one_or_none()


def _violations(platform: str, pp: PlatformProfile) -> list[str]:
    r, v = RULES[platform], []
    if r.headline_max and len(pp.headline) > r.headline_max:
        v.append(f"Headline is {len(pp.headline)}/{r.headline_max} characters")
    if len(pp.bio) > r.bio_max:
        v.append(f"Bio is {len(pp.bio)}/{r.bio_max} characters")
    if len(pp.skills) > r.skills_max:
        v.append(f"{len(pp.skills)}/{r.skills_max} skills allowed")
    return v


def _pp_out(
    acc: PlatformAccount, pp: PlatformProfile, m: MasterProfile | None
) -> PlatformProfileOut:
    return PlatformProfileOut(
        account_id=acc.id, platform=acc.platform, headline=pp.headline, bio=pp.bio,
        skills=pp.skills, hourly_rate=pp.hourly_rate, sync_status=svc.sync_status(pp, m),
        rules=RULES[acc.platform].as_dict(), violations=_violations(acc.platform, pp),
    )  # fmt: skip


@router.get("/profile/master", response_model=MasterOut | None)
async def get_master(user: CurrentUser, db: DB) -> MasterProfile | None:
    return await _master(db, user.id)


@router.put("/profile/master", response_model=MasterOut)
async def put_master(body: MasterIn, user: CurrentUser, db: DB) -> MasterProfile:
    m = await _master(db, user.id)
    if m is None:
        m = MasterProfile(user_id=user.id)
        db.add(m)
    for k, v in body.model_dump().items():
        setattr(m, k, v)
    await db.commit()
    return m


@router.get("/profile/completeness")
async def completeness(user: CurrentUser, db: DB, platform: str | None = None) -> dict[str, Any]:
    return svc.completeness(await _master(db, user.id), platform)


@router.put("/profile/contact", response_model=Message)
async def put_contact(body: dict[str, str], user: CurrentUser, db: DB) -> Message:
    """Postal/contact details for platform forms, stored encrypted."""
    m = await _master(db, user.id)
    if m is None:
        m = MasterProfile(user_id=user.id)
        db.add(m)
    m.contact_enc = encrypt(json.dumps(body))
    await db.commit()
    return Message(detail="Saved")


@router.get("/profile/contact")
async def get_contact(user: CurrentUser, db: DB) -> dict[str, str]:
    m = await _master(db, user.id)
    return json.loads(decrypt(m.contact_enc)) if m and m.contact_enc else {}


@router.get("/profile/platforms", response_model=list[PlatformProfileOut])
async def list_platform_profiles(user: CurrentUser, db: DB) -> list[PlatformProfileOut]:
    m = await _master(db, user.id)
    accs = (
        (await db.execute(select(PlatformAccount).where(PlatformAccount.user_id == user.id)))
        .scalars()
        .all()
    )
    out = []
    for a in accs:
        pp = (
            await db.execute(select(PlatformProfile).where(PlatformProfile.account_id == a.id))
        ).scalar_one_or_none()
        if pp:
            out.append(_pp_out(a, pp, m))
    return out


@router.post("/profile/platforms/{account_id}/derive", response_model=PlatformProfileOut)
async def derive(account_id: uuid.UUID, user: CurrentUser, db: DB) -> PlatformProfileOut:
    """Create or reset a platform variant from the master profile, applying that platform's limits."""
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    m = await _master(db, user.id)
    if m is None:
        raise HTTPException(409, "Create your master profile first")
    pp = (
        await db.execute(select(PlatformProfile).where(PlatformProfile.account_id == acc.id))
    ).scalar_one_or_none()
    if pp is None:
        pp = PlatformProfile(account_id=acc.id)
        db.add(pp)
    svc.apply_derived(pp, svc.derive_for_platform(m, acc.platform), m)
    await db.commit()
    return _pp_out(acc, pp, m)


@router.patch("/profile/platforms/{account_id}", response_model=PlatformProfileOut)
async def edit_platform_profile(
    account_id: uuid.UUID, body: PlatformProfileIn, user: CurrentUser, db: DB
) -> PlatformProfileOut:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    pp = (
        await db.execute(select(PlatformProfile).where(PlatformProfile.account_id == acc.id))
    ).scalar_one_or_none()
    if pp is None:
        raise HTTPException(404, "Derive this platform profile first")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pp, k, v)
    await db.commit()
    return _pp_out(acc, pp, await _master(db, user.id))


@router.get("/profile/platforms/{account_id}/diff")
async def platform_diff(account_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    acc = await get_owned(db, PlatformAccount, account_id, user.id)
    m = await _master(db, user.id)
    pp = (
        await db.execute(select(PlatformProfile).where(PlatformProfile.account_id == acc.id))
    ).scalar_one_or_none()
    if m is None or pp is None:
        raise HTTPException(404, "Nothing to compare")
    return {
        "sync_status": svc.sync_status(pp, m),
        "fields": svc.diff(pp, m),
        "completeness": svc.completeness(m, acc.platform),
    }


@router.get("/portfolio", response_model=list[PortfolioOut])
async def list_portfolio(user: CurrentUser, db: DB) -> list[PortfolioItem]:
    return list(
        (
            await db.execute(
                select(PortfolioItem)
                .where(PortfolioItem.user_id == user.id)
                .order_by(PortfolioItem.created_at.desc())
            )
        ).scalars()
    )


@router.post("/portfolio", response_model=PortfolioOut, status_code=201)
async def add_portfolio(body: PortfolioIn, user: CurrentUser, db: DB) -> PortfolioItem:
    item = PortfolioItem(user_id=user.id, **body.model_dump())
    db.add(item)
    await db.commit()
    return item


@router.put("/portfolio/{item_id}", response_model=PortfolioOut)
async def edit_portfolio(
    item_id: uuid.UUID, body: PortfolioIn, user: CurrentUser, db: DB
) -> PortfolioItem:
    item = await get_owned(db, PortfolioItem, item_id, user.id)
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    await db.commit()
    return item


@router.delete("/portfolio/{item_id}", response_model=Message)
async def delete_portfolio(item_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, PortfolioItem, item_id, user.id))
    await db.commit()
    return Message(detail="Deleted")
