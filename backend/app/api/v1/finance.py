import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.v1.projects import _entries, minutes_of
from app.models import Client, Expense, Invoice, Order, Payment, Project, TimeEntry
from app.schemas import ORM, Message
from app.services import finance as svc
from app.services import notifications
from app.services.analytics import goals_of as analytics_goals
from app.services.common import get_owned
from app.services.orders import record_payment

router = APIRouter(prefix="/finance", tags=["finance"])


class ItemIn(BaseModel):
    description: str = Field(max_length=300)
    quantity: float = Field(default=1, gt=0)
    unit_price: float = Field(default=0, ge=0)


class InvoiceIn(BaseModel):
    client_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    issue_date: date | None = None
    due_date: date | None = None
    items: list[ItemIn] = Field(min_length=1)
    tax_pct: float = Field(default=0, ge=0, le=100)
    notes: str = ""


class InvoiceOut(ORM):
    id: uuid.UUID
    client_id: uuid.UUID | None
    order_id: uuid.UUID | None
    project_id: uuid.UUID | None
    number: str
    currency: str
    status: str
    issue_date: date
    due_date: date | None
    items: list[dict[str, Any]]
    tax_pct: float
    notes: str
    subtotal: float
    tax_amount: float
    total: float
    paid_at: datetime | None
    overdue: bool = False
    client_name: str = ""


class FromTimeIn(BaseModel):
    project_id: uuid.UUID
    start: date | None = None
    end: date | None = None
    hourly_rate: float | None = Field(default=None, ge=0)
    tax_pct: float = Field(default=0, ge=0, le=100)
    due_in_days: int = Field(default=14, ge=0, le=365)


class ExpenseIn(BaseModel):
    spent_on: date | None = None
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    category: str = Field(default="other", max_length=60)
    description: str = Field(default="", max_length=300)
    tax_deductible: bool = True
    project_id: uuid.UUID | None = None


class ExpenseOut(ExpenseIn, ORM):
    id: uuid.UUID
    spent_on: date


class PaymentIn(BaseModel):
    platform: str = "direct"
    gross: float = Field(gt=0)
    fee: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    received_on: date | None = None
    client_id: uuid.UUID | None = None
    note: str = ""


class PaymentOut(ORM):
    id: uuid.UUID
    platform: str
    source: str
    gross: float
    fee: float
    net: float
    currency: str
    received_on: date
    client_id: uuid.UUID | None
    note: str


async def _inv_out(db: DB, inv: Invoice) -> InvoiceOut:
    o = InvoiceOut.model_validate(inv)
    o.overdue = (
        inv.status == "sent"
        and inv.due_date is not None
        and inv.due_date < datetime.now(UTC).date()
    )
    if inv.client_id and (c := await db.get(Client, inv.client_id)):
        o.client_name = c.name
    return o


def _apply_totals(inv: Invoice) -> None:
    inv.subtotal, inv.tax_amount, inv.total = svc.compute_totals(inv.items, inv.tax_pct)


# ---------- invoices ----------
@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    user: CurrentUser, db: DB, status: str | None = None, client_id: uuid.UUID | None = None
) -> list[InvoiceOut]:
    stmt = select(Invoice).where(Invoice.user_id == user.id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if client_id:
        stmt = stmt.where(Invoice.client_id == client_id)
    return [
        await _inv_out(db, i)
        for i in (await db.execute(stmt.order_by(Invoice.created_at.desc()))).scalars()
    ]


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(body: InvoiceIn, user: CurrentUser, db: DB) -> InvoiceOut:
    for model, ref in (
        (Client, body.client_id),
        (Order, body.order_id),
        (Project, body.project_id),
    ):
        if ref:
            await get_owned(db, model, ref, user.id)
    inv = Invoice(
        user_id=user.id, number=await svc.next_invoice_number(db, user.id), client_id=body.client_id, order_id=body.order_id, project_id=body.project_id,
        currency=body.currency.upper(), issue_date=body.issue_date or datetime.now(UTC).date(), due_date=body.due_date,
        items=[i.model_dump() for i in body.items], tax_pct=body.tax_pct, notes=body.notes,
    )  # fmt: skip
    _apply_totals(inv)
    db.add(inv)
    await db.commit()
    return await _inv_out(db, inv)


@router.post("/invoices/from-time", response_model=InvoiceOut, status_code=201)
async def invoice_from_time(body: FromTimeIn, user: CurrentUser, db: DB) -> InvoiceOut:
    """Bill uninvoiced billable time on a project; entries are locked to the invoice."""
    proj = await get_owned(db, Project, body.project_id, user.id)
    rate = body.hourly_rate if body.hourly_rate is not None else proj.hourly_rate
    if not rate:
        raise HTTPException(422, "Set an hourly rate on the project or pass hourly_rate")
    entries = [
        e
        for e in await _entries(db, user.id, proj.id, body.start, body.end)
        if e.billable and e.invoice_id is None and e.ended_at is not None
    ]
    if not entries:
        raise HTTPException(409, "No unbilled time in that range")
    hours = round(sum(minutes_of(e) for e in entries) / 60, 2)
    today = datetime.now(UTC).date()
    inv = Invoice(
        user_id=user.id, number=await svc.next_invoice_number(db, user.id), client_id=proj.client_id, project_id=proj.id, currency=proj.currency,
        issue_date=today, due_date=today + timedelta(days=body.due_in_days), tax_pct=body.tax_pct,
        items=[{"description": f"{proj.name} - {hours:g}h @ {rate:g}/h", "quantity": hours, "unit_price": rate}],
    )  # fmt: skip
    _apply_totals(inv)
    db.add(inv)
    await db.flush()
    for e in entries:
        e.invoice_id = inv.id
    await db.commit()
    return await _inv_out(db, inv)


@router.get("/invoices/{iid}", response_model=InvoiceOut)
async def get_invoice(iid: uuid.UUID, user: CurrentUser, db: DB) -> InvoiceOut:
    return await _inv_out(db, await get_owned(db, Invoice, iid, user.id))


@router.put("/invoices/{iid}", response_model=InvoiceOut)
async def update_invoice(iid: uuid.UUID, body: InvoiceIn, user: CurrentUser, db: DB) -> InvoiceOut:
    inv = await get_owned(db, Invoice, iid, user.id)
    if inv.status != "draft":
        raise HTTPException(409, "Only draft invoices can be edited")
    inv.client_id, inv.currency, inv.due_date, inv.notes, inv.tax_pct = (
        body.client_id,
        body.currency.upper(),
        body.due_date,
        body.notes,
        body.tax_pct,
    )
    inv.items = [i.model_dump() for i in body.items]
    if body.issue_date:
        inv.issue_date = body.issue_date
    _apply_totals(inv)
    await db.commit()
    return await _inv_out(db, inv)


@router.post("/invoices/{iid}/{action}", response_model=InvoiceOut)
async def invoice_action(iid: uuid.UUID, action: str, user: CurrentUser, db: DB) -> InvoiceOut:
    inv = await get_owned(db, Invoice, iid, user.id)
    if action == "send":
        if inv.status != "draft":
            raise HTTPException(409, "Only draft invoices can be marked as sent")
        inv.status = "sent"
    elif action == "pay":
        if inv.status not in ("sent", "draft"):
            raise HTTPException(409, f"Cannot mark a {inv.status} invoice as paid")
        inv.status, inv.paid_at = "paid", datetime.now(UTC)
        platform = "direct"
        if inv.order_id and (o := await db.get(Order, inv.order_id)):
            platform = o.platform
        p, created = await record_payment(
            db,
            user,
            source="invoice",
            source_id=str(inv.id),
            platform=platform,
            gross=inv.total,
            currency=inv.currency,
            client_id=inv.client_id,
            fee=0.0,
            note=inv.number,
        )
        if created:
            if inv.client_id and (c := await db.get(Client, inv.client_id)):
                c.total_earned += p.net
            await notifications.emit(
                db,
                user.id,
                "payment_received",
                f"Invoice {inv.number} paid",
                body=f"{inv.currency} {inv.total:,.2f}",
                url="/finance",
                dedupe_key=f"inv-paid:{inv.id}",
            )
    elif action == "void":
        if inv.status == "paid":
            raise HTTPException(409, "Paid invoices cannot be voided")
        inv.status = "void"
        for e in (
            await db.execute(select(TimeEntry).where(TimeEntry.invoice_id == inv.id))
        ).scalars():
            e.invoice_id = None  # release time for re-billing
    else:
        raise HTTPException(422, "action must be send, pay or void")
    await db.commit()
    return await _inv_out(db, inv)


@router.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    inv = await get_owned(db, Invoice, iid, user.id)
    client = await db.get(Client, inv.client_id) if inv.client_id else None
    return Response(
        svc.invoice_pdf(inv, user, client),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{inv.number}.pdf"'},
    )


# ---------- expenses & payments ----------
@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(user: CurrentUser, db: DB, category: str | None = None) -> list[Expense]:
    stmt = select(Expense).where(Expense.user_id == user.id)
    if category:
        stmt = stmt.where(Expense.category == category)
    return list((await db.execute(stmt.order_by(Expense.spent_on.desc()))).scalars())


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
async def add_expense(body: ExpenseIn, user: CurrentUser, db: DB) -> Expense:
    if body.project_id:
        await get_owned(db, Project, body.project_id, user.id)
    d = body.model_dump()
    d["spent_on"] = body.spent_on or datetime.now(UTC).date()
    e = Expense(user_id=user.id, **d)
    db.add(e)
    await db.commit()
    return e


@router.delete("/expenses/{eid}", response_model=Message)
async def del_expense(eid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Expense, eid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(user: CurrentUser, db: DB, platform: str | None = None) -> list[Payment]:
    stmt = select(Payment).where(Payment.user_id == user.id)
    if platform:
        stmt = stmt.where(Payment.platform == platform)
    return list((await db.execute(stmt.order_by(Payment.received_on.desc()))).scalars())


@router.post("/payments", response_model=PaymentOut, status_code=201)
async def add_payment(body: PaymentIn, user: CurrentUser, db: DB) -> Payment:
    if body.client_id:
        await get_owned(db, Client, body.client_id, user.id)
    p, _ = await record_payment(
        db, user, source="manual", source_id=uuid.uuid4().hex, platform=body.platform, gross=body.gross, currency=body.currency.upper(),
        client_id=body.client_id, fee=body.fee, note=body.note, received_on=body.received_on,
    )  # fmt: skip
    await notifications.emit(
        db,
        user.id,
        "payment_received",
        f"Payment received: {body.currency.upper()} {body.gross:,.2f}",
        body=body.note,
        url="/finance",
        dedupe_key=f"pay:{p.id}",
    )
    await db.commit()
    return p


@router.delete("/payments/{pid}", response_model=Message)
async def del_payment(pid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Payment, pid, user.id))
    await db.commit()
    return Message(detail="Deleted")


# ---------- calculators & reports ----------
@router.get("/fee-calculator")
async def fee_calculator(user: CurrentUser, platform: str, amount: float) -> dict[str, Any]:
    if platform not in svc.PLATFORM_FEES:
        raise HTTPException(422, "Unknown platform")
    if amount < 0:
        raise HTTPException(422, "amount must be >= 0")
    return svc.fee_calc(user, platform, amount) | {
        "note": "Default fee schedule - platforms change fees, override in settings.fees"
    }


@router.get("/report")
async def report(
    user: CurrentUser,
    db: DB,
    start: date | None = None,
    end: date | None = None,
    group_by: str = "month",
) -> dict[str, Any]:
    if group_by not in ("month", "platform", "client"):
        raise HTTPException(422, "group_by must be month, platform or client")
    today = datetime.now(UTC).date()
    return await svc.earnings_report(
        db, user, start or date(today.year, 1, 1), end or today, group_by
    )


@router.get("/report.csv")
async def report_csv(
    user: CurrentUser,
    db: DB,
    start: date | None = None,
    end: date | None = None,
    group_by: str = "month",
) -> Response:
    rep = await report(user, db, start, end, group_by)
    return Response(
        svc.report_csv(rep),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="earnings.csv"'},
    )


@router.get("/summary")
async def summary(user: CurrentUser, db: DB) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    month = await svc.earnings_report(db, user, today.replace(day=1), today, "platform")
    open_invoices = list(
        (
            await db.execute(
                select(Invoice).where(Invoice.user_id == user.id, Invoice.status == "sent")
            )
        ).scalars()
    )
    missing: set[str] = set()
    outstanding = sum(svc.to_base(user, i.total, i.currency, missing) for i in open_invoices)
    overdue = [i for i in open_invoices if i.due_date and i.due_date < today]
    goal = analytics_goals(user)["monthly_income"]
    return {
        "currency": svc.base_currency(user), "month": month["totals"], "by_platform": month["rows"],
        "outstanding_invoices": round(outstanding, 2), "overdue_invoices": len(overdue),
        "tax_set_aside": month["tax"]["estimated_tax"], "monthly_income_goal": goal,
        "goal_progress": round(month["totals"]["net"] / goal, 3) if goal else None,
        "missing_fx_rates": sorted(set(month["missing_fx_rates"]) | missing),
    }  # fmt: skip
