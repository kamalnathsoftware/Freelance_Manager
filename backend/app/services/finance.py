"""Fees, FX, invoices (totals, numbering, PDF), tax estimate and earnings reports."""

import csv
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from fpdf import FPDF
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, Expense, Invoice, Payment, User

# (percent of gross, minimum fee). Defaults only - platforms change fees; users can override in settings["fees"].
PLATFORM_FEES: dict[str, tuple[float, float]] = {
    "fiverr": (20.0, 0), "upwork": (10.0, 0), "freelancer": (10.0, 5.0), "peopleperhour": (20.0, 0),
    "toptal": (0.0, 0), "guru": (9.0, 0), "linkedin": (0.0, 0), "contra": (0.0, 0), "direct": (0.0, 0),
}  # fmt: skip


def fee_for(user: User | None, platform: str, gross: float) -> float:
    pct, minimum = PLATFORM_FEES.get(platform, (0.0, 0.0))
    override = ((user.settings or {}).get("fees", {}) if user else {}).get(platform)
    if isinstance(override, dict):
        pct, minimum = float(override.get("pct", pct)), float(override.get("min", minimum))
    return round(max(gross * pct / 100, minimum if gross > 0 else 0), 2)


def fee_calc(user: User | None, platform: str, gross: float) -> dict[str, Any]:
    fee = fee_for(user, platform, gross)
    return {
        "platform": platform,
        "gross": gross,
        "fee": fee,
        "net": round(gross - fee, 2),
        "fee_pct_effective": round(fee / gross * 100, 2) if gross else 0.0,
    }


def base_currency(user: User) -> str:
    return str((user.settings or {}).get("base_currency", "USD")).upper()


def to_base(user: User, amount: float, currency: str, missing: set[str] | None = None) -> float:
    """Convert using the user's manual FX table (settings['fx'] = {'EUR': 1.08}). Unknown rate => 1.0 and flagged."""
    base, cur = base_currency(user), currency.upper()
    if cur == base:
        return amount
    rate = ((user.settings or {}).get("fx", {}) or {}).get(cur)
    if rate is None:
        if missing is not None:
            missing.add(cur)
        return amount
    return amount * float(rate)


# ---------- invoices ----------
def compute_totals(items: list[dict[str, Any]], tax_pct: float) -> tuple[float, float, float]:
    sub = round(sum(float(i.get("quantity", 1)) * float(i.get("unit_price", 0)) for i in items), 2)
    tax = round(sub * tax_pct / 100, 2)
    return sub, tax, round(sub + tax, 2)


async def next_invoice_number(db: AsyncSession, user_id: uuid.UUID, year: int | None = None) -> str:
    year = year or datetime.now(UTC).year
    prefix = f"INV-{year}-"
    n = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.user_id == user_id, Invoice.number.like(f"{prefix}%")
            )
        )
    ).scalar_one()
    while True:
        n += 1
        num = f"{prefix}{n:04d}"
        if not (
            await db.execute(
                select(Invoice.id).where(Invoice.user_id == user_id, Invoice.number == num)
            )
        ).first():
            return num


def _latin(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")  # core PDF fonts are latin-1 only


def invoice_pdf(inv: Invoice, user: User, client: Client | None) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0,
        6,
        _latin(f"Number: {inv.number}    Status: {inv.status.upper()}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(
        0,
        6,
        f"Issued: {inv.issue_date.isoformat()}"
        + (f"    Due: {inv.due_date.isoformat()}" if inv.due_date else ""),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(95, 6, "From")
    pdf.cell(0, 6, "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    frm = [user.full_name or user.email, user.email]
    to = [client.name, client.company, client.email] if client else ["-"]
    for i in range(max(len(frm), len(to))):
        pdf.cell(95, 5, _latin(frm[i] if i < len(frm) else ""))
        pdf.cell(0, 5, _latin(to[i] if i < len(to) else ""), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(235, 235, 245)
    for w, h in ((95, "Description"), (20, "Qty"), (35, "Unit price"), (35, "Amount")):
        pdf.cell(w, 7, h, fill=True, align="L" if w == 95 else "R")
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    for it in inv.items:
        qty, price = float(it.get("quantity", 1)), float(it.get("unit_price", 0))
        pdf.cell(95, 6, _latin(str(it.get("description", ""))[:60]))
        pdf.cell(20, 6, f"{qty:g}", align="R")
        pdf.cell(35, 6, f"{price:,.2f}", align="R")
        pdf.cell(35, 6, f"{qty * price:,.2f}", align="R")
        pdf.ln()
    pdf.ln(3)
    for label, val in (("Subtotal", inv.subtotal), (f"Tax ({inv.tax_pct:g}%)", inv.tax_amount)):
        pdf.cell(150, 6, label, align="R")
        pdf.cell(35, 6, f"{val:,.2f}", align="R")
        pdf.ln()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(150, 8, f"Total ({inv.currency})", align="R")
    pdf.cell(35, 8, f"{inv.total:,.2f}", align="R")
    pdf.ln(12)
    if inv.notes:
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _latin(inv.notes))
    return bytes(pdf.output())


# ---------- tax & reports ----------
async def payments_between(
    db: AsyncSession, user_id: uuid.UUID, start: date, end: date
) -> list[Payment]:
    return list(
        (
            await db.execute(
                select(Payment).where(
                    Payment.user_id == user_id,
                    Payment.received_on >= start,
                    Payment.received_on <= end,
                )
            )
        ).scalars()
    )


async def expenses_between(
    db: AsyncSession, user_id: uuid.UUID, start: date, end: date
) -> list[Expense]:
    return list(
        (
            await db.execute(
                select(Expense).where(
                    Expense.user_id == user_id, Expense.spent_on >= start, Expense.spent_on <= end
                )
            )
        ).scalars()
    )


def tax_estimate(user: User, net_income: float, deductible: float) -> dict[str, Any]:
    rate = float((user.settings or {}).get("tax_rate_pct", 25))
    taxable = max(0.0, net_income - deductible)
    owed = round(taxable * rate / 100, 2)
    return {"rate_pct": rate, "taxable_income": round(taxable, 2), "estimated_tax": owed, "set_aside_per_month_hint": round(owed / 12, 2),
            "disclaimer": "Rough estimate using a single flat rate. Not tax advice - confirm with an accountant."}  # fmt: skip


async def earnings_report(
    db: AsyncSession, user: User, start: date, end: date, group_by: str = "month"
) -> dict[str, Any]:
    missing: set[str] = set()
    pays = await payments_between(db, user.id, start, end)
    exps = await expenses_between(db, user.id, start, end)
    client_names = {
        c.id: c.name
        for c in (await db.execute(select(Client).where(Client.user_id == user.id))).scalars()
    }
    keyf = {
        "month": lambda p: p.received_on.strftime("%Y-%m"),
        "platform": lambda p: p.platform,
        "client": lambda p: client_names.get(p.client_id, "Unassigned"),
    }[group_by]
    rows: dict[str, dict[str, float]] = defaultdict(
        lambda: {"gross": 0.0, "fee": 0.0, "net": 0.0, "count": 0}
    )
    for p in pays:
        r = rows[keyf(p)]
        r["gross"] += to_base(user, p.gross, p.currency, missing)
        r["fee"] += to_base(user, p.fee, p.currency, missing)
        r["net"] += to_base(user, p.net, p.currency, missing)
        r["count"] += 1
    gross = sum(r["gross"] for r in rows.values())
    fees = sum(r["fee"] for r in rows.values())
    net = sum(r["net"] for r in rows.values())
    expense_total = sum(to_base(user, e.amount, e.currency, missing) for e in exps)
    deductible = sum(to_base(user, e.amount, e.currency, missing) for e in exps if e.tax_deductible)
    by_cat: dict[str, float] = defaultdict(float)
    for e in exps:
        by_cat[e.category] += to_base(user, e.amount, e.currency, missing)
    return {
        "currency": base_currency(user), "start": start.isoformat(), "end": end.isoformat(), "group_by": group_by,
        "rows": [{"key": k, **{m: round(v, 2) for m, v in r.items() if m != "count"}, "count": int(r["count"])} for k, r in sorted(rows.items())],
        "totals": {"gross": round(gross, 2), "fees": round(fees, 2), "net": round(net, 2), "expenses": round(expense_total, 2), "profit": round(net - expense_total, 2)},
        "expenses_by_category": {k: round(v, 2) for k, v in sorted(by_cat.items())},
        "tax": tax_estimate(user, net, deductible),
        "missing_fx_rates": sorted(missing),
    }  # fmt: skip


def report_csv(rep: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([rep["group_by"], "gross", "fees", "net", "payments", rep["currency"]])
    for r in rep["rows"]:
        w.writerow([r["key"], r["gross"], r["fee"], r["net"], r["count"], ""])
    t = rep["totals"]
    w.writerow(["TOTAL", t["gross"], t["fees"], t["net"], "", ""])
    w.writerow(["EXPENSES", "", "", t["expenses"], "", ""])
    w.writerow(["PROFIT", "", "", t["profit"], "", ""])
    return buf.getvalue()
