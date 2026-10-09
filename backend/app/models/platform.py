import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> uuid.UUID:
    return uuid.uuid4()


class IntegrationMode(enum.StrEnum):
    api = "api"
    email = "email"
    manual = "manual"


class AccountStatus(enum.StrEnum):
    pending = "pending"
    connected = "connected"
    error = "error"
    disconnected = "disconnected"


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    username: Mapped[str] = mapped_column(String(120), default="")
    profile_url: Mapped[str] = mapped_column(String(500), default="")
    mode: Mapped[IntegrationMode] = mapped_column(
        Enum(IntegrationMode), default=IntegrationMode.manual
    )
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus), default=AccountStatus.pending
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # unread, active_orders, pending_bids, earnings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IntegrationToken(Base):
    """OAuth/API credentials, always stored encrypted (see app.core.crypto)."""

    __tablename__ = "integration_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), unique=True
    )
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(String(500), default="")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # ok | error | skipped
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MasterProfile(Base):
    __tablename__ = "master_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    location: Mapped[str] = mapped_column(String(200), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    availability: Mapped[str] = mapped_column(String(100), default="")
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[list] = mapped_column(JSON, default=list)
    contact_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # encrypted JSON (address, phone…)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class PlatformProfile(Base):
    """Per-account variant of the master profile. `synced_master` is the master snapshot at last derive."""

    __tablename__ = "platform_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), unique=True
    )
    headline: Mapped[str] = mapped_column(String(300), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    synced_master: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(
        String(20), default="link"
    )  # image | video | link | case_study
    url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GigStatus(enum.StrEnum):
    draft = "draft"
    ready = "ready"
    live = "live"
    paused = "paused"


class Gig(Base):
    __tablename__ = "gigs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    faq: Mapped[list] = mapped_column(JSON, default=list)  # [{q, a}]
    requirements: Mapped[list] = mapped_column(JSON, default=list)  # questionnaire
    gallery: Mapped[list] = mapped_column(JSON, default=list)  # urls
    notes: Mapped[str] = mapped_column(Text, default="")  # A/B + competitor notes
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[GigStatus] = mapped_column(Enum(GigStatus), default=GigStatus.draft)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GigPackage(Base):
    __tablename__ = "gig_packages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    gig_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gigs.id", ondelete="CASCADE"), index=True)
    tier: Mapped[str] = mapped_column(String(20))  # basic | standard | premium
    name: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    delivery_days: Mapped[int] = mapped_column(Integer, default=3)
    revisions: Mapped[int] = mapped_column(Integer, default=1)
    features: Mapped[list] = mapped_column(JSON, default=list)


class GigPlatformListing(Base):
    __tablename__ = "gig_platform_listings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    gig_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gigs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), index=True
    )
    overrides: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # title/description/tags adjustments
    status: Mapped[GigStatus] = mapped_column(Enum(GigStatus), default=GigStatus.draft)
    external_url: Mapped[str] = mapped_column(String(500), default="")
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # impressions, clicks, orders
