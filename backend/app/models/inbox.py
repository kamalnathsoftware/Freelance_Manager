import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
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


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    country: Mapped[str] = mapped_column(String(80), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    vip: Mapped[bool] = mapped_column(Boolean, default=False)
    # Updated by orders/invoices in later phases; editable manually until then.
    total_earned: Mapped[float] = mapped_column(Float, default=0)
    completed_orders: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ClientIdentity(Base):
    """A client's handle on one platform. Several identities merge into one Client."""

    __tablename__ = "client_identities"
    __table_args__ = (UniqueConstraint("user_id", "platform", "handle", name="uq_identity"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40))
    handle: Mapped[str] = mapped_column(String(200))


class ConvStatus(enum.StrEnum):
    open = "open"
    snoozed = "snoozed"
    archived = "archived"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "platform", "thread_key", name="uq_thread"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(40), index=True)
    thread_key: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(300), default="")
    platform_url: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[ConvStatus] = mapped_column(
        Enum(ConvStatus), default=ConvStatus.open, index=True
    )
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    last_preview: Mapped[str] = mapped_column(String(300), default="")
    awaiting_reply_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    visitor_token_hash: Mapped[str] = mapped_column(String(64), default="")  # chat-widget threads
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "idempotency_key", name="uq_msg_idem"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    sender_name: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # email|extension|api|widget|manual
    # out messages: sent | pending_manual (user must paste on the platform) | failed
    delivery: Mapped[str] = mapped_column(String(20), default="sent")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)


class CannedResponse(Base):
    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    shortcut: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)


class ChatWidget(Base):
    """Embeddable chat for the freelancer's own site (direct clients)."""

    __tablename__ = "chat_widgets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    public_key: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    greeting: Mapped[str] = mapped_column(String(300), default="Hi! How can I help?")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
