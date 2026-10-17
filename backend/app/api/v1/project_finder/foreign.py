"""Foreign-client helper: time-zone overlap and payment records. Not tax advice."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.v1.project_finder.common import CurrencyStr, TzStr
from app.models import PFInvoice, PFLead
from app.schemas import ORM, Message
from app.services.common import get_owned
from app.services.project_finder import get_pf_settings, tz
from app.services.project_finder.outreach import today_for

router = APIRouter(tags=["project-finder"])

DISCLAIMER = (
    "This is a record-keeping aid, not tax, legal or accounting advice. Rules for GST/LUT, FIRC/e-FIRA and "
    "foreign-exchange reporting change and depend on your situation - confirm them with a chartered accountant."
)
PAYMENT_METHODS = ("wise", "payoneer", "paypal", "swift", "other")
Method = Literal["wise", "payoneer", "paypal", "swift", "other"]


@router.get("/foreign/info")
async def info(user: CurrentUser) -> dict[str, Any]:
    return {"disclaimer": DISCLAIMER, "payment_methods": list(PAYMENT_METHODS)}


@router.get("/foreign/tz-overlap")
async def tz_overlap(
    user: CurrentUser,
    db: DB,
    timezone: Annotated[TzStr, Query(min_length=1)],
    on: date | None = None,
) -> dict[str, object]:
    """Shared working hours with a client in `timezone`, relative to your time zone and hours (Settings)."""
    cfg = await get_pf_settings(db, user.id)
    await db.commit()
    return tz.overlap(
        cfg.home_tz, timezone, start_hour=cfg.work_start_hour, end_hour=cfg.work_end_hour, on=on
    )


@router.get("/foreign/tz-suggest")
async def tz_suggest(country: str, user: CurrentUser) -> dict[str, str]:
    """A likely IANA zone for a country name (a guess: large countries span several zones)."""
    return {"timezone": tz.suggest_timezone(country)}


class InvoiceIn(BaseModel):
    lead_id: uuid.UUID
    reference: str = Field(default="", max_length=80)
    amount: float = Field(gt=0, le=1e9)
    currency: CurrencyStr = ""
    invoice_date: date | None = None
    payment_method: Method = "wise"
    firc_received: bool = False
    lut_note: str = Field(default="", max_length=2000)


class InvoicePatch(BaseModel):
    reference: str | None = Field(default=None, max_length=80)
    amount: float | None = Field(default=None, gt=0, le=1e9)
    currency: CurrencyStr | None = None
    invoice_date: date | None = None
    payment_method: Method | None = None
    firc_received: bool | None = None
    lut_note: str | None = Field(default=None, max_length=2000)


class InvoiceOut(ORM):
    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str = ""
    reference: str
    amount: float
    currency: str
    invoice_date: date
    payment_method: str
    firc_received: bool
    lut_note: str
    created_at: datetime


async def _names(db: DB, rows: list[PFInvoice]) -> list[InvoiceOut]:
    leads = {r.lead_id for r in rows}
    names: dict[uuid.UUID, str] = {}
    for lid in leads:
        lead = await db.get(PFLead, lid)
        if lead is not None:
            names[lid] = lead.business_name
    out = []
    for r in rows:
        o = InvoiceOut.model_validate(r)
        o.lead_name = names.get(r.lead_id, "")
        out.append(o)
    return out


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    user: CurrentUser,
    db: DB,
    lead_id: uuid.UUID | None = None,
    firc: Literal["pending", "received"] | None = None,
) -> list[InvoiceOut]:
    stmt = select(PFInvoice).where(PFInvoice.user_id == user.id)
    if lead_id:
        stmt = stmt.where(PFInvoice.lead_id == lead_id)
    if firc:
        stmt = stmt.where(PFInvoice.firc_received.is_(firc == "received"))
    rows = list(
        (
            await db.execute(
                stmt.order_by(PFInvoice.invoice_date.desc(), PFInvoice.created_at.desc())
            )
        ).scalars()
    )
    return await _names(db, rows)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(body: InvoiceIn, user: CurrentUser, db: DB) -> InvoiceOut:
    lead = await get_owned(db, PFLead, body.lead_id, user.id)
    data = body.model_dump()
    data["currency"] = data["currency"] or lead.currency or "USD"
    data["invoice_date"] = data["invoice_date"] or today_for(user)
    inv = PFInvoice(user_id=user.id, **data)
    db.add(inv)
    await db.commit()
    return (await _names(db, [inv]))[0]


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
async def update_invoice(
    invoice_id: uuid.UUID, body: InvoicePatch, user: CurrentUser, db: DB
) -> InvoiceOut:
    inv = await get_owned(db, PFInvoice, invoice_id, user.id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "currency" in changes and not changes["currency"]:
        raise HTTPException(422, "currency cannot be empty")
    for k, v in changes.items():
        setattr(inv, k, v)
    await db.commit()
    return (await _names(db, [inv]))[0]


@router.delete("/invoices/{invoice_id}", response_model=Message)
async def delete_invoice(invoice_id: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, PFInvoice, invoice_id, user.id))
    await db.commit()
    return Message(detail="Deleted")
