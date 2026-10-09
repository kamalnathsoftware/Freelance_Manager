"""Full personal-data export and account erasure (including files on disk)."""

import datetime as dt
import enum
import json
import uuid
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.models import (
    AuditLog,
    AutomationRule,
    CalendarEvent,
    CannedResponse,
    Client,
    ClientIdentity,
    Conversation,
    Expense,
    Form,
    FormField,
    FormSubmission,
    Gig,
    GigPackage,
    GigPlatformListing,
    Invoice,
    Job,
    MasterProfile,
    Message,
    Milestone,
    NotificationEvent,
    Order,
    OrderFile,
    Payment,
    PlatformAccount,
    PlatformEvent,
    PlatformProfile,
    PortfolioItem,
    Project,
    Proposal,
    ProposalTemplate,
    SavedSearch,
    Task,
    TeamMember,
    TimeEntry,
    UploadedFile,
    User,
)
from app.services import storage

# Never exported: credential material and internal secrets.
SECRET_COLUMNS = {
    "password_hash",
    "totp_secret_enc",
    "access_token_enc",
    "refresh_token_enc",
    "key_hash",
    "refresh_hash",
    "prev_refresh_hash",
    "visitor_token_hash",
    "path",
}


def _val(v: Any) -> Any:
    if isinstance(v, uuid.UUID | dt.datetime | dt.date):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)
    if isinstance(v, enum.Enum):
        return v.value
    return v


def row(obj: Any) -> dict[str, Any]:
    return {
        c.key: _val(getattr(obj, c.key))
        for c in inspect(obj).mapper.column_attrs
        if c.key not in SECRET_COLUMNS
    }


async def _rows(db: AsyncSession, model: Any, col: Any, ids: Any) -> list[dict[str, Any]]:
    return [
        row(o)
        for o in (
            await db.execute(
                select(model).where(col.in_(ids) if isinstance(ids, list | set) else col == ids)
            )
        ).scalars()
    ]


async def export_all(db: AsyncSession, user: User) -> dict[str, Any]:
    uid = user.id
    out: dict[str, Any] = {"exported_at": dt.datetime.now(dt.UTC).isoformat(), "user": row(user)}
    for name, model in (
        ("master_profile", MasterProfile), ("platform_accounts", PlatformAccount), ("portfolio", PortfolioItem), ("gigs", Gig), ("jobs", Job),
        ("saved_searches", SavedSearch), ("proposals", Proposal), ("proposal_templates", ProposalTemplate), ("clients", Client),
        ("client_identities", ClientIdentity), ("conversations", Conversation), ("orders", Order), ("projects", Project), ("tasks", Task),
        ("time_entries", TimeEntry), ("invoices", Invoice), ("expenses", Expense), ("payments", Payment), ("calendar_events", CalendarEvent),
        ("forms", Form), ("form_submissions", FormSubmission), ("automation_rules", AutomationRule), ("notifications", NotificationEvent),
        ("platform_events", PlatformEvent), ("canned_responses", CannedResponse), ("audit_log", AuditLog), ("uploaded_files", UploadedFile),
    ):  # fmt: skip
        out[name] = await _rows(db, model, model.user_id, uid)
    out["team_members"] = await _rows(db, TeamMember, TeamMember.owner_id, uid)
    acc_ids = [a["id"] for a in out["platform_accounts"]]
    out["platform_profiles"] = [
        row(p)
        for p in (await db.execute(select(PlatformProfile))).scalars()
        if str(p.account_id) in acc_ids
    ]
    gig_ids = [uuid.UUID(g["id"]) for g in out["gigs"]]
    if gig_ids:
        out["gig_packages"] = await _rows(db, GigPackage, GigPackage.gig_id, gig_ids)
        out["gig_listings"] = await _rows(
            db, GigPlatformListing, GigPlatformListing.gig_id, gig_ids
        )
    conv_ids = [uuid.UUID(c["id"]) for c in out["conversations"]]
    out["messages"] = (
        await _rows(db, Message, Message.conversation_id, conv_ids) if conv_ids else []
    )
    order_ids = [uuid.UUID(o["id"]) for o in out["orders"]]
    if order_ids:
        out["milestones"] = await _rows(db, Milestone, Milestone.order_id, order_ids)
        out["order_files"] = await _rows(db, OrderFile, OrderFile.order_id, order_ids)
    form_ids = [uuid.UUID(f["id"]) for f in out["forms"]]
    out["form_fields"] = await _rows(db, FormField, FormField.form_id, form_ids) if form_ids else []
    mp = (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == uid))
    ).scalar_one_or_none()
    out["contact_details"] = json.loads(decrypt(mp.contact_enc)) if mp and mp.contact_enc else {}
    return json.loads(json.dumps(out, default=str))  # guarantees JSON-serialisable output


async def erase_files(db: AsyncSession, user_id: uuid.UUID) -> int:
    n = 0
    for f in (
        await db.execute(select(UploadedFile).where(UploadedFile.user_id == user_id))
    ).scalars():
        storage.delete_file(f.path)
        n += 1
    return n
