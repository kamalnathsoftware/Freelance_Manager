import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notif_dedupe"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")  # in-app path or external link
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # normal | high (VIP / SLA)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class NotificationPreference(Base):
    """One cell of the event-type x channel matrix."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "event_type", "channel", name="uq_pref"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(10), default="instant")  # instant | hourly | daily


class ChannelAddress(Base):
    """Where to reach the user on a channel; WhatsApp/SMS require explicit opt-in."""

    __tablename__ = "channel_addresses"
    __table_args__ = (UniqueConstraint("user_id", "channel", name="uq_channel"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20))  # email | whatsapp | sms | telegram
    address: Mapped[str] = mapped_column(String(200), default="")
    opted_in: Mapped[bool] = mapped_column(Boolean, default=False)
    link_code: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_device_token"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))  # expo | webpush
    token: Mapped[str] = mapped_column(Text)  # expo token, or JSON push subscription
    label: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), index=True)
    # pending | sent | failed | skipped | digest
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    provider_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fallback_of: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="instant")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
