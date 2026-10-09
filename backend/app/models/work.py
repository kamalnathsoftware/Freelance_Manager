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


def _fk(table: str, *, null: bool = False, ondelete: str = "CASCADE", index: bool = True):  # type: ignore[no-untyped-def]
    return mapped_column(
        Uuid, ForeignKey(f"{table}.id", ondelete=ondelete), nullable=null, index=index
    )


ORDER_STATUSES = ("pending", "active", "delivered", "revision", "completed", "cancelled")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "platform", "external_ref", name="uq_order_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    client_id: Mapped[uuid.UUID | None] = _fk("clients", null=True, ondelete="SET NULL")
    account_id: Mapped[uuid.UUID | None] = _fk(
        "platform_accounts", null=True, ondelete="SET NULL", index=False
    )
    proposal_id: Mapped[uuid.UUID | None] = _fk(
        "proposals", null=True, ondelete="SET NULL", index=False
    )
    platform: Mapped[str] = mapped_column(String(40), index=True)
    external_ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # platform id; NULL if manual
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revisions_allowed: Mapped[int] = mapped_column(Integer, default=1)
    revisions_used: Mapped[int] = mapped_column(Integer, default=0)
    checklist: Mapped[list] = mapped_column(JSON, default=list)  # [{item, done}]
    source: Mapped[str] = mapped_column(String(10), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    order_id: Mapped[uuid.UUID] = _fk("orders")
    title: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | submitted | paid
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderFile(Base):
    __tablename__ = "order_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    order_id: Mapped[uuid.UUID] = _fk("orders")
    filename: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(12), default="deliverable")  # deliverable | reference
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    order_id: Mapped[uuid.UUID | None] = _fk("orders", null=True, ondelete="SET NULL", index=False)
    client_id: Mapped[uuid.UUID | None] = _fk(
        "clients", null=True, ondelete="SET NULL", index=False
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused | done
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    project_id: Mapped[uuid.UUID] = _fk("projects")
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(8), default="todo")  # todo | doing | done
    priority: Mapped[str] = mapped_column(String(6), default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    project_id: Mapped[uuid.UUID | None] = _fk("projects", null=True, ondelete="SET NULL")
    task_id: Mapped[uuid.UUID | None] = _fk("tasks", null=True, ondelete="SET NULL", index=False)
    invoice_id: Mapped[uuid.UUID | None] = _fk(
        "invoices", null=True, ondelete="SET NULL", index=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # None = running
    note: Mapped[str] = mapped_column(String(300), default="")
    billable: Mapped[bool] = mapped_column(Boolean, default=True)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("user_id", "number", name="uq_invoice_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    client_id: Mapped[uuid.UUID | None] = _fk("clients", null=True, ondelete="SET NULL")
    order_id: Mapped[uuid.UUID | None] = _fk("orders", null=True, ondelete="SET NULL", index=False)
    project_id: Mapped[uuid.UUID | None] = _fk(
        "projects", null=True, ondelete="SET NULL", index=False
    )
    number: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(
        String(8), default="draft", index=True
    )  # draft|sent|paid|void
    issue_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(UTC).date())
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{description, quantity, unit_price}]
    tax_pct: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    subtotal: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    project_id: Mapped[uuid.UUID | None] = _fk(
        "projects", null=True, ondelete="SET NULL", index=False
    )
    spent_on: Mapped[date] = mapped_column(
        Date, default=lambda: datetime.now(UTC).date(), index=True
    )
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    category: Mapped[str] = mapped_column(String(60), default="other")
    description: Mapped[str] = mapped_column(String(300), default="")
    tax_deductible: Mapped[bool] = mapped_column(Boolean, default=True)


class Payment(Base):
    """Money received. Source of truth for earnings reports (gross/fee/net)."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("user_id", "source", "source_id", name="uq_payment_source"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    client_id: Mapped[uuid.UUID | None] = _fk(
        "clients", null=True, ondelete="SET NULL", index=False
    )
    platform: Mapped[str] = mapped_column(String(40), default="direct", index=True)
    source: Mapped[str] = mapped_column(
        String(12), default="manual"
    )  # manual|order|milestone|invoice|email
    source_id: Mapped[str] = mapped_column(String(64), default="")
    gross: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0)
    net: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    received_on: Mapped[date] = mapped_column(
        Date, default=lambda: datetime.now(UTC).date(), index=True
    )
    note: Mapped[str] = mapped_column(String(300), default="")


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(
        String(12), default="other"
    )  # interview | followup | meeting | other
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    google_event_id: Mapped[str] = mapped_column(String(100), default="", index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class CalendarConnection(Base):
    """Google Calendar link (two-way sync with a dedicated 'Freelance Manager' calendar). Tokens encrypted."""

    __tablename__ = "calendar_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = _fk("users")
    calendar_id: Mapped[str] = mapped_column(String(200), default="")
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalendarFeedToken(Base):
    """Secret URL token so calendar apps can subscribe to an ICS feed without an Authorization header."""

    __tablename__ = "calendar_feed_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
