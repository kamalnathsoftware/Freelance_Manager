"""Dashboard analytics, income goals and pipeline-based forecasting. All money is converted to the
user's base currency using their manual FX table (see services/finance.py)."""

import calendar as cal_mod
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, Order, Payment, Proposal, Stage, TimeEntry, User
from app.models.work import Milestone
from app.services import calendar as calsvc
from app.services import finance, inbox
from app.services.proposals import proposal_analytics

DEFAULT_GOALS = {"monthly_income": 0.0, "yearly_income": 0.0, "weekly_hours": 40.0}
STAGE_ORDER = ["found", "shortlisted", "drafted", "submitted", "viewed", "interview", "won"]


def goals_of(user: User) -> dict[str, float]:
    g = {
        **DEFAULT_GOALS,
        **{
            k: float(v)
            for k, v in ((user.settings or {}).get("goals") or {}).items()
            if k in DEFAULT_GOALS
        },
    }
    legacy = (user.settings or {}).get("monthly_income_goal")
    if not g["monthly_income"] and legacy:
        g["monthly_income"] = float(legacy)
    return g


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _bucket(d: date, granularity: str) -> str:
    if granularity == "day":
        return d.isoformat()
    if granularity == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.strftime("%Y-%m")


def _all_buckets(start: date, end: date, granularity: str) -> list[str]:
    out: list[str] = []
    d = start
    while d <= end:
        b = _bucket(d, granularity)
        if not out or out[-1] != b:
            out.append(b)
        d += timedelta(days=1)
    return out


async def _payments(db: AsyncSession, user_id: uuid.UUID, start: date, end: date) -> list[Payment]:
    return await finance.payments_between(db, user_id, start, end)


async def overview(
    db: AsyncSession, user: User, days: int = 30, granularity: str = "day"
) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    prev_start, prev_end = start - timedelta(days=days), start - timedelta(days=1)
    missing: set[str] = set()

    pays = await _payments(db, user.id, start, today)
    series: dict[str, float] = {b: 0.0 for b in _all_buckets(start, today, granularity)}
    for p in pays:
        series[_bucket(p.received_on, granularity)] += finance.to_base(
            user, p.net, p.currency, missing
        )
    net = sum(series.values())
    prev_net = sum(
        finance.to_base(user, p.net, p.currency, missing)
        for p in await _payments(db, user.id, prev_start, prev_end)
    )

    by_platform = await finance.earnings_report(db, user, start, today, "platform")
    by_client = await finance.earnings_report(db, user, start, today, "client")

    rows = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(Proposal.user_id == user.id)
        )
    ).all()
    props = [(p, j) for p, j in rows]
    funnel = pipeline_funnel([p for p, _ in props])
    pa = proposal_analytics(props, {})
    pipeline_value = sum(
        (p.bid_amount or 0)
        for p, _ in props
        if p.stage in (Stage.submitted, Stage.viewed, Stage.interview)
    )

    entries = list(
        (
            await db.execute(
                select(TimeEntry).where(
                    TimeEntry.user_id == user.id,
                    TimeEntry.started_at >= datetime.combine(start, datetime.min.time(), UTC),
                )
            )
        ).scalars()
    )
    now = datetime.now(UTC)
    tracked = (
        sum(
            ((_aware(e.ended_at) if e.ended_at else now) - _aware(e.started_at)).total_seconds()
            for e in entries
        )
        / 3600
    )
    billable = (
        sum(
            ((_aware(e.ended_at) if e.ended_at else now) - _aware(e.started_at)).total_seconds()
            for e in entries
            if e.billable
        )
        / 3600
    )
    capacity = goals_of(user)["weekly_hours"] * days / 7
    active_orders = list(
        (
            await db.execute(
                select(Order).where(
                    Order.user_id == user.id, Order.status.in_(["active", "revision", "delivered"])
                )
            )
        ).scalars()
    )
    deadlines = [
        i
        for i in await calsvc.items(db, user.id, now, now + timedelta(days=7))
        if i["kind"].endswith("_due")
    ]

    resp = await inbox.response_stats(db, user.id)
    avg_resp = (
        round(
            sum(r["avg_response_minutes"] * r["replies"] for r in resp)
            / max(1, sum(r["replies"] for r in resp)),
            1,
        )
        if resp
        else None
    )
    return {
        "currency": finance.base_currency(user), "days": days, "granularity": granularity,
        "kpis": {
            "net_earnings": round(net, 2), "previous_net_earnings": round(prev_net, 2),
            "change_pct": round((net - prev_net) / prev_net * 100, 1) if prev_net else None,
            "win_rate": pa["win_rate"], "proposals_submitted": pa["submitted"], "open_pipeline_value": round(pipeline_value, 2),
            "active_orders": len(active_orders), "avg_response_minutes": avg_resp,
        },
        "earnings_series": [{"key": k, "net": round(v, 2)} for k, v in series.items()],
        "by_platform": by_platform["rows"], "top_clients": sorted(by_client["rows"], key=lambda r: -r["net"])[:10],
        "funnel": funnel, "win_rate_by": {"platform": pa["by_platform"], "template": pa["by_template"], "price_band": pa["by_price_band"], "hour": pa["by_hour"]},
        "response_times": resp,
        "utilization": {"tracked_hours": round(tracked, 1), "billable_hours": round(billable, 1), "capacity_hours": round(capacity, 1),
                        "utilization_pct": round(tracked / capacity * 100, 1) if capacity else None, "billable_pct": round(billable / tracked * 100, 1) if tracked else None},  # fmt: skip
        "upcoming_deadlines": [{"title": d["title"], "kind": d["kind"], "at": d["start"].isoformat(), "href": d["href"]} for d in deadlines[:8]],
        "missing_fx_rates": sorted(set(by_platform["missing_fx_rates"]) | missing),
    }  # fmt: skip


def pipeline_funnel(proposals: list[Proposal]) -> list[dict[str, Any]]:
    """Cumulative funnel from current stage + submitted_at. Stage history isn't stored, so 'viewed' and
    'interview' undercount proposals that were later lost - treat later steps as lower bounds."""
    idx = {s: i for i, s in enumerate(STAGE_ORDER)}
    reached = {s: 0 for s in STAGE_ORDER}
    for p in proposals:
        if p.stage == Stage.lost:
            top = idx["submitted"] if p.submitted_at else idx["drafted"] if p.body else idx["found"]
        else:
            top = idx[p.stage.value]
        for s in STAGE_ORDER[: top + 1]:
            reached[s] += 1
    out, prev = [], None
    for s in STAGE_ORDER:
        n = reached[s]
        out.append(
            {
                "stage": s,
                "count": n,
                "conversion_from_previous": round(n / prev, 3) if prev else None,
            }
        )
        prev = n if n else prev
    return out


def stage_probabilities(proposals: list[Proposal]) -> dict[str, Any]:
    won = sum(1 for p in proposals if p.stage == Stage.won)
    lost = sum(1 for p in proposals if p.stage == Stage.lost and p.submitted_at)
    closed = won + lost
    if closed >= 5:
        base = won / closed
        return {
            "submitted": round(base, 3),
            "viewed": round(min(0.9, base * 1.6), 3),
            "interview": round(min(0.9, base * 3.5), 3),
            "source": f"your history ({closed} closed proposals)",
        }
    return {
        "submitted": 0.10,
        "viewed": 0.18,
        "interview": 0.40,
        "source": "defaults (fewer than 5 closed proposals)",
    }


async def goal_progress(db: AsyncSession, user: User) -> dict[str, Any]:
    g = goals_of(user)
    today = datetime.now(UTC).date()
    m_start, y_start = today.replace(day=1), date(today.year, 1, 1)
    days_in_month = cal_mod.monthrange(today.year, today.month)[1]
    missing: set[str] = set()

    async def earned(start: date) -> float:
        return round(
            sum(
                finance.to_base(user, p.net, p.currency, missing)
                for p in await _payments(db, user.id, start, today)
            ),
            2,
        )

    m_earned, y_earned = await earned(m_start), await earned(y_start)
    elapsed = today.day
    run_rate = round(m_earned / elapsed * days_in_month, 2) if elapsed else 0.0

    props = [
        p for p in (await db.execute(select(Proposal).where(Proposal.user_id == user.id))).scalars()
    ]
    probs = stage_probabilities(props)
    weighted = round(
        sum(
            (p.bid_amount or 0) * probs[p.stage.value]
            for p in props
            if p.stage.value in ("submitted", "viewed", "interview")
        ),
        2,
    )

    orders = list(
        (
            await db.execute(
                select(Order).where(
                    Order.user_id == user.id, Order.status.in_(["active", "revision", "delivered"])
                )
            )
        ).scalars()
    )
    paid_ms: dict[uuid.UUID, float] = defaultdict(float)
    for m in (
        (
            await db.execute(
                select(Milestone).where(
                    Milestone.order_id.in_([o.id for o in orders]), Milestone.status == "paid"
                )
            )
        ).scalars()
        if orders
        else []
    ):
        paid_ms[m.order_id] += m.amount
    committed = round(
        sum(
            max(0.0, o.amount - paid_ms[o.id])
            - finance.fee_for(user, o.platform, max(0.0, o.amount - paid_ms[o.id]))
            for o in orders
        ),
        2,
    )

    def pct(v: float, goal: float) -> float | None:
        return round(v / goal * 100, 1) if goal else None

    expected_pct = round(elapsed / days_in_month * 100, 1)
    m_pct = pct(m_earned, g["monthly_income"])
    status = (
        None
        if m_pct is None
        else "ahead"
        if m_pct >= expected_pct + 5
        else "behind"
        if m_pct <= expected_pct - 10
        else "on_track"
    )
    return {
        "currency": finance.base_currency(user),
        "goals": g,
        "month": {
            "earned": m_earned,
            "goal": g["monthly_income"],
            "pct": m_pct,
            "expected_pct_by_today": expected_pct,
            "status": status,
        },
        "year": {
            "earned": y_earned,
            "goal": g["yearly_income"],
            "pct": pct(y_earned, g["yearly_income"]),
        },
        "forecast": {
            "run_rate_month_end": run_rate,
            "committed_orders_net": committed,
            "pipeline_weighted": weighted,
            "month_end_with_committed": round(m_earned + committed, 2),
            "month_end_with_pipeline": round(m_earned + committed + weighted, 2),
            "assumptions": {
                "stage_win_probability": probs,
                "note": "Estimates only. Committed = unpaid balance of active orders net of platform fees; pipeline = open bids x stage probability.",
            },
        },  # fmt: skip
        "missing_fx_rates": sorted(missing),
    }


def report_pdf(user: User, ov: dict[str, Any], gp: dict[str, Any]) -> bytes:
    cur = ov["currency"]
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Business report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        0,
        6,
        finance._latin(
            f"{user.full_name or user.email} - last {ov['days']} days - generated {datetime.now(UTC):%Y-%m-%d}"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    def section(title: str) -> None:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)

    def line(a: str, b: str) -> None:
        pdf.cell(110, 6, finance._latin(a))
        pdf.cell(0, 6, finance._latin(b), align="R", new_x="LMARGIN", new_y="NEXT")

    k = ov["kpis"]
    section("Key figures")
    line(
        "Net earnings",
        f"{cur} {k['net_earnings']:,.2f}"
        + (f" ({k['change_pct']:+.1f}% vs previous period)" if k["change_pct"] is not None else ""),
    )
    line(
        "Win rate", f"{k['win_rate'] * 100:.1f}% of {k['proposals_submitted']} submitted proposals"
    )
    line("Open pipeline value", f"{cur} {k['open_pipeline_value']:,.2f}")
    line("Active orders", str(k["active_orders"]))
    line(
        "Average first-response time",
        f"{k['avg_response_minutes']} min" if k["avg_response_minutes"] is not None else "n/a",
    )
    u = ov["utilization"]
    line("Time tracked / billable", f"{u['tracked_hours']}h / {u['billable_hours']}h")
    section("Earnings by platform (net)")
    for r in ov["by_platform"] or [{"key": "-", "net": 0}]:
        line(str(r["key"]), f"{cur} {r['net']:,.2f}")
    section("Top clients (net)")
    for r in ov["top_clients"][:5] or [{"key": "-", "net": 0}]:
        line(str(r["key"]), f"{cur} {r['net']:,.2f}")
    section("Proposal funnel")
    for f in ov["funnel"]:
        line(f["stage"].capitalize(), str(f["count"]))
    section("Goals")
    m = gp["month"]
    line(
        "This month",
        f"{cur} {m['earned']:,.2f}"
        + (f" of {m['goal']:,.0f} ({m['pct']}%)" if m["goal"] else " (no goal set)"),
    )
    line(
        "Projected month end (committed + pipeline)",
        f"{cur} {gp['forecast']['month_end_with_pipeline']:,.2f}",
    )
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        0,
        4,
        "Forecasts are estimates based on your own history and stage probabilities. The funnel is approximate because stage history is not stored. Not tax or financial advice.",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    return bytes(pdf.output())
