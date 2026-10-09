import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import Gig, GigPackage, GigPlatformListing, GigStatus, PlatformAccount
from app.schemas import ORM, Message
from app.services import gigs as svc
from app.services.common import get_owned

router = APIRouter(prefix="/gigs", tags=["gigs"])


class PackageIn(BaseModel):
    tier: str = Field(pattern="^(basic|standard|premium)$")
    name: str = ""
    description: str = ""
    price: float = Field(default=0, ge=0)
    delivery_days: int = Field(default=3, ge=1, le=365)
    revisions: int = Field(default=1, ge=0)
    features: list[str] = []


class PackageOut(PackageIn, ORM):
    id: uuid.UUID


class GigIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = ""
    tags: list[str] = []
    description: str = ""
    faq: list[dict[str, str]] = []
    requirements: list[dict[str, Any]] = []
    gallery: list[str] = []
    notes: str = ""
    keywords: list[str] = []
    status: GigStatus = GigStatus.draft
    packages: list[PackageIn] = []


class GigOut(ORM):
    id: uuid.UUID
    title: str
    category: str
    tags: list[str]
    description: str
    faq: list[dict[str, str]]
    requirements: list[dict[str, Any]]
    gallery: list[str]
    notes: str
    keywords: list[str]
    status: GigStatus
    created_at: datetime
    packages: list[PackageOut] = []


class ListingOut(ORM):
    id: uuid.UUID
    gig_id: uuid.UUID
    account_id: uuid.UUID
    overrides: dict[str, Any]
    status: GigStatus
    external_url: str
    metrics: dict[str, Any]


class CloneIn(BaseModel):
    account_ids: list[uuid.UUID] = Field(min_length=1)


class ListingUpdate(BaseModel):
    overrides: dict[str, Any] | None = None
    status: GigStatus | None = None
    external_url: str | None = None
    metrics: dict[str, Any] | None = None  # imported via API/email or entered manually


async def _packages(db: DB, gig_id: uuid.UUID) -> list[GigPackage]:
    return list((await db.execute(select(GigPackage).where(GigPackage.gig_id == gig_id))).scalars())


async def _out(db: DB, gig: Gig) -> GigOut:
    o = GigOut.model_validate(gig)
    o.packages = [PackageOut.model_validate(p) for p in await _packages(db, gig.id)]
    return o


async def _listing(db: DB, gig_id: uuid.UUID, listing_id: uuid.UUID) -> GigPlatformListing:
    li = await db.get(GigPlatformListing, listing_id)
    if li is None or li.gig_id != gig_id:
        raise HTTPException(404, "Listing not found")
    return li


@router.get("", response_model=list[GigOut])
async def list_gigs(user: CurrentUser, db: DB, status: GigStatus | None = None) -> list[GigOut]:
    q = select(Gig).where(Gig.user_id == user.id).order_by(Gig.created_at.desc())
    if status:
        q = q.where(Gig.status == status)
    return [await _out(db, g) for g in (await db.execute(q)).scalars()]


@router.post("", response_model=GigOut, status_code=201)
async def create_gig(body: GigIn, user: CurrentUser, db: DB) -> GigOut:
    data = body.model_dump(exclude={"packages"})
    gig = Gig(user_id=user.id, **data)
    db.add(gig)
    await db.flush()
    for p in body.packages:
        db.add(GigPackage(gig_id=gig.id, **p.model_dump()))
    await db.commit()
    return await _out(db, gig)


@router.get("/{gig_id}", response_model=GigOut)
async def get_gig(gig_id: uuid.UUID, user: CurrentUser, db: DB) -> GigOut:
    return await _out(db, await get_owned(db, Gig, gig_id, user.id))


@router.put("/{gig_id}", response_model=GigOut)
async def update_gig(gig_id: uuid.UUID, body: GigIn, user: CurrentUser, db: DB) -> GigOut:
    gig = await get_owned(db, Gig, gig_id, user.id)
    for k, v in body.model_dump(exclude={"packages"}).items():
        setattr(gig, k, v)
    for old in await _packages(db, gig.id):
        await db.delete(old)
    for new in body.packages:
        db.add(GigPackage(gig_id=gig.id, **new.model_dump()))
    await db.commit()
    return await _out(db, gig)


@router.delete("/{gig_id}", response_model=Message)
async def delete_gig(gig_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Gig, gig_id, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/{gig_id}/clone", response_model=list[ListingOut], status_code=201)
async def clone_to_platforms(
    gig_id: uuid.UUID, body: CloneIn, user: CurrentUser, db: DB
) -> list[GigPlatformListing]:
    """Create a per-platform listing for each account, pre-adapted to that platform's limits."""
    gig = await get_owned(db, Gig, gig_id, user.id)
    out = []
    for aid in dict.fromkeys(body.account_ids):
        acc = await get_owned(db, PlatformAccount, aid, user.id)
        from app.adapters.rules import RULES

        if RULES[acc.platform].gig_title_max == 0:
            raise HTTPException(422, f"{acc.platform} does not support gigs")
        existing = (
            await db.execute(
                select(GigPlatformListing).where(
                    GigPlatformListing.gig_id == gig.id, GigPlatformListing.account_id == acc.id
                )
            )
        ).scalar_one_or_none()
        if existing:
            out.append(existing)
            continue
        li = GigPlatformListing(
            gig_id=gig.id, account_id=acc.id, overrides=svc.adapt_for_platform(gig, acc.platform)
        )
        db.add(li)
        out.append(li)
    await db.commit()
    return out


@router.get("/{gig_id}/listings", response_model=list[ListingOut])
async def listings(gig_id: uuid.UUID, user: CurrentUser, db: DB) -> list[GigPlatformListing]:
    await get_owned(db, Gig, gig_id, user.id)
    return list(
        (
            await db.execute(select(GigPlatformListing).where(GigPlatformListing.gig_id == gig_id))
        ).scalars()
    )


@router.patch("/{gig_id}/listings/{listing_id}", response_model=ListingOut)
async def update_listing(
    gig_id: uuid.UUID, listing_id: uuid.UUID, body: ListingUpdate, user: CurrentUser, db: DB
) -> GigPlatformListing:
    await get_owned(db, Gig, gig_id, user.id)
    li = await _listing(db, gig_id, listing_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(li, k, v)
    await db.commit()
    return li


@router.get("/{gig_id}/listings/{listing_id}/checklist")
async def publish_checklist(
    gig_id: uuid.UUID, listing_id: uuid.UUID, user: CurrentUser, db: DB
) -> dict[str, Any]:
    gig = await get_owned(db, Gig, gig_id, user.id)
    li = await _listing(db, gig_id, listing_id)
    acc = await db.get(PlatformAccount, li.account_id)
    items = svc.checklist(gig, await _packages(db, gig.id), li, acc)  # type: ignore[arg-type]
    return {"ready": all(i["done"] for i in items), "items": items}


@router.get("/{gig_id}/listings/{listing_id}/export")
async def export_listing(
    gig_id: uuid.UUID, listing_id: uuid.UUID, user: CurrentUser, db: DB
) -> dict[str, Any]:
    gig = await get_owned(db, Gig, gig_id, user.id)
    li = await _listing(db, gig_id, listing_id)
    acc = await db.get(PlatformAccount, li.account_id)
    return svc.export_listing(gig, await _packages(db, gig.id), li, acc)  # type: ignore[arg-type]


@router.get("/{gig_id}/performance")
async def gig_performance(gig_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    await get_owned(db, Gig, gig_id, user.id)
    lis = list(
        (
            await db.execute(select(GigPlatformListing).where(GigPlatformListing.gig_id == gig_id))
        ).scalars()
    )
    return {
        "total": svc.performance(lis),
        "by_listing": {str(li.id): svc.performance([li]) for li in lis},
    }
