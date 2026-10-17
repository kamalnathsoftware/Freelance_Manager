"""Simple, explainable numbers: reply rate, win rate, earnings by source, best source, funnel, outreach."""

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PFInvoice, PFLead, PFOutreachLog, PFProposal, User
from app.services.project_finder.outreach import STATUSES, goal_status, today_for

UNKNOWN = "Unknown"


def rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def _bucket() -> dict[str, Any]:
    return {"sent": 0, "replied": 0, "won": 0, "lost": 0, "earnings": defaultdict(float)}


def _tally(b: dict[str, Any], p: PFProposal) -> None:
    b["sent"] += 1
    b["replied"] += p.replied_on is not None
    b["won"] += p.status == "won"
    b["lost"] += p.status == "lost"
    if p.status == "won":
        b["earnings"][p.currency or "USD"] += p.amount or 0.0


def _row(name: str, b: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": name, "sent": b["sent"], "replied": b["replied"], "won": b["won"], "lost": b["lost"],
        "reply_rate": rate(b["replied"], b["sent"]), "win_rate": rate(b["won"], b["sent"]),
        "earnings": {k: round(v, 2) for k, v in sorted(b["earnings"].items())},
    }  # fmt: skip


def best_source(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Most wins, then most replies, then most proposals sent. None until something has worked."""
    ranked = sorted(rows, key=lambda r: (r["won"], r["replied"], r["sent"]), reverse=True)
    if not ranked or (ranked[0]["won"] == 0 and ranked[0]["replied"] == 0):
        return None
    top = ranked[0]
    if top["won"]:
        why = f"{top['won']} win{'s' if top['won'] > 1 else ''} from {top['sent']} proposal{'s' if top['sent'] > 1 else ''}"
    else:
        why = f"{top['replied']} repl{'ies' if top['replied'] > 1 else 'y'} from {top['sent']} proposal{'s' if top['sent'] > 1 else ''}, no wins yet"
    return {
        "source": top["source"],
        "reason": why,
        "rule": "Most wins, then most replies, then most proposals sent",
    }


async def compute(db: AsyncSession, user: User, days: int | None = None) -> dict[str, Any]:
    today = today_for(user)
    stmt = select(PFProposal).where(PFProposal.user_id == user.id)
    if days:
        stmt = stmt.where(PFProposal.sent_on >= today - timedelta(days=days))
    proposals = list((await db.execute(stmt)).scalars())

    total = _bucket()
    by_source: dict[str, dict[str, Any]] = defaultdict(_bucket)
    for p in proposals:
        _tally(total, p)
        _tally(by_source[p.source.strip() or UNKNOWN], p)
    rows = sorted(
        (_row(k, v) for k, v in by_source.items()),
        key=lambda r: (-r["won"], -r["replied"], -r["sent"], r["source"]),
    )
    summary = _row("all", total)
    summary["pending"] = sum(p.status == "sent" for p in proposals)
    summary.pop("source")

    leads = list((await db.execute(select(PFLead).where(PFLead.user_id == user.id))).scalars())
    by_status = {s: 0 for s in STATUSES}
    leads_by_source: dict[str, dict[str, int]] = defaultdict(lambda: {"leads": 0, "won": 0})
    for ld in leads:
        by_status[ld.status] = by_status.get(ld.status, 0) + 1
        s = leads_by_source[ld.source.strip() or UNKNOWN]
        s["leads"] += 1
        s["won"] += ld.status == "won"
    due = sum(
        1
        for ld in leads
        if ld.next_follow_up and ld.next_follow_up <= today and ld.status not in ("won", "lost")
    )

    def sent_since(n: int) -> Any:
        return select(func.count()).select_from(PFOutreachLog).where(
            PFOutreachLog.user_id == user.id, PFOutreachLog.sent_on > today - timedelta(days=n)
        )  # fmt: skip

    goal = await goal_status(db, user)
    invoices = list(
        (await db.execute(select(PFInvoice).where(PFInvoice.user_id == user.id))).scalars()
    )
    invoiced: dict[str, float] = defaultdict(float)
    for inv in invoices:
        invoiced[inv.currency] += inv.amount
    return {
        "days": days,
        "proposals": summary,
        "by_source": rows,
        "best_source": best_source(rows),
        "earnings_basis": "Amounts of proposals marked Won, per currency (no currency conversion)",
        "leads": {
            "total": len(leads),
            "by_status": by_status,
            "follow_ups_due": due,
            "win_rate": rate(by_status["won"], len(leads)),
            "by_source": sorted(
                ({"source": k, **v} for k, v in leads_by_source.items()),
                key=lambda r: (-r["won"], -r["leads"], r["source"]),
            ),
        },  # fmt: skip
        "foreign": {
            "invoices": len(invoices),
            "firc_pending": sum(not i.firc_received for i in invoices),
            "invoiced": {k: round(v, 2) for k, v in sorted(invoiced.items())},
            "countries": sorted({ld.country.strip() for ld in leads if ld.country.strip()}),
        },
        "outreach": {
            "last_7_days": (await db.execute(sent_since(7))).scalar_one(),
            "last_30_days": (await db.execute(sent_since(30))).scalar_one(),
            "today": goal["today"],
            "goal": goal["goal"],
            "streak": goal["streak"],
            "best_streak": goal["best_streak"],
        },  # fmt: skip
    }
