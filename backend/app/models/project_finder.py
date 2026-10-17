"""Project Finder: find and win freelance work without platform fees.

Tables are prefixed `pf_` because `jobs`, `proposals`, `clients` and `invoices` already belong to the
platform-bid workflow. Status-like columns are plain strings validated in the API layer (no DB enums),
so adding a status never needs a migration.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _uid() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class PFSettings(Base):
    """One row per user: the skills/keywords that drive fit scoring, plus outreach goal and tz prefs."""

    __tablename__ = "pf_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    skills: Mapped[list] = mapped_column(JSON, default=list)
    include_keywords: Mapped[list] = mapped_column(JSON, default=list)
    exclude_keywords: Mapped[list] = mapped_column(JSON, default=list)
    min_store_score: Mapped[int] = mapped_column(Integer, default=15)
    daily_goal: Mapped[int] = mapped_column(Integer, default=5)
    my_name: Mapped[str] = mapped_column(String(120), default="")
    home_tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    work_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    work_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PFSource(Base):
    __tablename__ = "pf_sources"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_pf_source_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    key: Mapped[str] = mapped_column(String(40))  # slug; built-ins map to a fetcher in code
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(10), default="manual")  # feed | manual
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str] = mapped_column(String(300), default="")  # ok: 12 new | error text
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PFJob(Base):
    __tablename__ = "pf_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "source_key", "external_id", name="uq_pf_job_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    source_key: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[str] = mapped_column(String(120), default="")  # as stated, e.g. "$80k-$120k"
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    url: Mapped[str] = mapped_column(String(1000), default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=True)
    skills: Mapped[list] = mapped_column(
        JSON, default=list
    )  # tags (from the feed + matched skills)
    fit_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default="new")  # new | saved | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class PFLead(Base):
    __tablename__ = "pf_leads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    business_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    linkedin_url: Mapped[str] = mapped_column(String(500), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    problem: Mapped[str] = mapped_column(Text, default="")  # the problem I noticed
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(
        String(80), default=""
    )  # free text: Cold email, Reddit, ...
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    next_follow_up: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # foreign-client helper
    country: Mapped[str] = mapped_column(String(80), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")  # IANA, e.g. America/New_York
    currency: Mapped[str] = mapped_column(String(3), default="")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pf_jobs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class PFOutreachLog(Base):
    """One row per outreach message sent. Drives the daily goal and streak."""

    __tablename__ = "pf_outreach_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pf_leads.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="other")  # email | linkedin | other
    sent_on: Mapped[date] = mapped_column(Date, index=True)  # in the user's timezone
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PFTemplate(Base):
    __tablename__ = "pf_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # cold_email | linkedin_dm | proposal
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PFProposal(Base):
    __tablename__ = "pf_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    title: Mapped[str] = mapped_column(String(300))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pf_leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pf_jobs.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(80), default="")  # copied from lead/job, editable
    sent_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="sent", index=True)
    replied_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PFInvoice(Base):
    """Payment record for a won project from a foreign client. Not tax advice."""

    __tablename__ = "pf_invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _uid()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pf_leads.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str] = mapped_column(String(80), default="")
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    invoice_date: Mapped[date] = mapped_column(Date)
    payment_method: Mapped[str] = mapped_column(String(20), default="wise")
    firc_received: Mapped[bool] = mapped_column(Boolean, default=False)  # FIRC / e-FIRA
    lut_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
