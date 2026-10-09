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


class Form(Base):
    __tablename__ = "forms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    public_key: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(
        String(20), default="custom"
    )  # brief|feedback|testimonial|nda|onboarding|review|revision|custom
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # {"success_message": str, "auto_actions": ["create_project"|"create_proposal_draft"], "agreement_text": str}
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FormField(Base):
    __tablename__ = "form_fields"
    __table_args__ = (UniqueConstraint("form_id", "key", name="uq_form_field_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(12))
    label: Mapped[str] = mapped_column(String(300))
    help_text: Mapped[str] = mapped_column(String(500), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list] = mapped_column(JSON, default=list)
    # {"field": key, "op": "eq|ne|contains|gt|lt|filled", "value": any}; field shown only when it holds
    show_if: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    submitter_name: Mapped[str] = mapped_column(String(200), default="")
    submitter_email: Mapped[str] = mapped_column(String(320), default="")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    signature: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    form_version: Mapped[int] = mapped_column(Integer, default=1)
    ip: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # ids created by auto-actions
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class UploadedFile(Base):
    """Local-disk file store (swap `app.services.storage` for S3/R2 in production)."""

    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    form_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[str] = mapped_column(String(40), index=True)
    conditions: Mapped[list] = mapped_column(JSON, default=list)  # [{field, op, value}] (AND)
    actions: Mapped[list] = mapped_column(JSON, default=list)  # [{type, params}]
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (UniqueConstraint("rule_id", "dedupe_key", name="uq_run_dedupe"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10))  # ok | error | skipped | dry_run
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
