"""AI assistant: deterministic daily briefing + optional Claude narrative, requirement extraction, pricing, chat.
All AI output is labelled and never auto-sent."""

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Conversation,
    ConvStatus,
    Invoice,
    Job,
    MasterProfile,
    Order,
    Proposal,
    Stage,
    Task,
    User,
)
from app.services import ai, inbox
from app.services import calendar as cal
from app.services.matching import suggest_bid
from app.services.proposals import price_band, proposal_analytics


async def briefing_facts(db: AsyncSession, user: User) -> dict[str, Any]:
    now = datetime.now(UTC)
    day_end = now + timedelta(hours=24)
    unread = (
        await db.execute(
            select(func.coalesce(func.sum(Conversation.unread_count), 0)).where(
                Conversation.user_id == user.id, Conversation.status == ConvStatus.open
            )
        )
    ).scalar_one()
    waiting = await inbox.sla_alerts(db, user)
    due = [
        i
        for i in await cal.items(db, user.id, now - timedelta(hours=12), day_end)
        if i["kind"] not in ("follow_up",)
    ]
    new_jobs = list(
        (
            await db.execute(
                select(Job)
                .where(
                    Job.user_id == user.id,
                    Job.created_at >= now - timedelta(hours=24),
                    Job.dismissed.is_(False),
                )
                .order_by(Job.score.desc())
                .limit(5)
            )
        ).scalars()
    )
    job_count = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.user_id == user.id, Job.created_at >= now - timedelta(hours=24), Job.score >= 60
            )
        )
    ).scalar_one()
    follow = list(
        (
            await db.execute(
                select(Proposal, Job)
                .join(Job, Job.id == Proposal.job_id)
                .where(
                    Proposal.user_id == user.id,
                    Proposal.stage.in_([Stage.submitted, Stage.viewed]),
                    Proposal.follow_up_at.is_not(None),
                    Proposal.follow_up_at <= now,
                )
            )
        ).all()
    )
    overdue = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.user_id == user.id, Invoice.status == "sent", Invoice.due_date < now.date()
            )
        )
    ).scalar_one()
    active_orders = (
        await db.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status.in_(["active", "revision"])
            )
        )
    ).scalar_one()
    open_tasks = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.user_id == user.id,
                Task.status != "done",
                Task.due_at.is_not(None),
                Task.due_at <= day_end,
            )
        )
    ).scalar_one()
    return {
        "date": now.date().isoformat(),
        "unread_messages": int(unread),
        "clients_waiting": [{"subject": a["subject"], "minutes": a["waiting_minutes"], "vip": a["vip"]} for a in waiting[:5]],
        "deadlines_next_24h": [{"title": i["title"], "kind": i["kind"], "at": i["start"].isoformat()} for i in due[:8]],
        "new_matching_jobs": job_count,
        "top_new_jobs": [{"title": j.title, "platform": j.platform, "score": j.score} for j in new_jobs],
        "proposal_follow_ups_due": [{"job": j.title, "platform": j.platform} for _, j in follow],
        "overdue_invoices": int(overdue),
        "active_orders": int(active_orders),
        "tasks_due_today": int(open_tasks),
    }  # fmt: skip


def headline(f: dict[str, Any]) -> str:
    parts = [f"{f['unread_messages']} unread message(s)"]
    if f["deadlines_next_24h"]:
        parts.append(f"{len(f['deadlines_next_24h'])} deadline(s)")
    parts.append(f"{f['new_matching_jobs']} new matching job(s)")
    if f["overdue_invoices"]:
        parts.append(f"{f['overdue_invoices']} overdue invoice(s)")
    return "Today: " + ", ".join(parts)


async def narrative(f: dict[str, Any]) -> str | None:
    if not get_settings().anthropic_api_key:
        return None
    return await ai.complete(
        "You are a calm chief-of-staff for a solo freelancer. Using ONLY the JSON facts, write a 4-6 line morning briefing: "
        "what is most urgent first, then what can wait. No invented items. No greetings.",
        json.dumps(f), 400,
    )  # fmt: skip


def _parse_json(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))  # type: ignore[no-any-return]


async def extract_requirements(text: str) -> dict[str, Any]:
    out = await ai.complete(
        "Extract structured requirements from a client brief. Reply with ONLY a JSON object with keys: "
        '"summary" (string), "requirements" (array of strings), "deliverables" (array), "deadline" (string or null), '
        '"budget" (string or null), "open_questions" (array of questions to ask the client). Do not invent facts.',
        text[:12000], 900,
    )  # fmt: skip
    try:
        data = _parse_json(out)
    except (ValueError, json.JSONDecodeError):
        return {
            "summary": out[:500],
            "requirements": [],
            "deliverables": [],
            "deadline": None,
            "budget": None,
            "open_questions": [],
            "parse_warning": True,
        }
    return {
        k: data.get(k, [] if k in ("requirements", "deliverables", "open_questions") else None)
        for k in ("summary", "requirements", "deliverables", "deadline", "budget", "open_questions")
    }


async def pricing_advice(db: AsyncSession, user: User, job: Job) -> dict[str, Any]:
    master = (
        await db.execute(select(MasterProfile).where(MasterProfile.user_id == user.id))
    ).scalar_one_or_none()
    base = suggest_bid(job, master)
    rows = (
        await db.execute(
            select(Proposal, Job)
            .join(Job, Job.id == Proposal.job_id)
            .where(Proposal.user_id == user.id)
        )
    ).all()
    stats = proposal_analytics([(p, j) for p, j in rows], {})
    won = [p.bid_amount for p, _ in rows if p.stage == Stage.won and p.bid_amount]
    amount = base["amount"]
    band = price_band(amount)
    band_row = next((b for b in stats["by_price_band"] if b["key"] == band), None)
    return {
        "suggested_amount": amount, "rationale": base["rationale"], "price_band": band,
        "your_win_rate_in_band": band_row["win_rate"] if band_row else None, "your_samples_in_band": band_row["submitted"] if band_row else 0,
        "your_avg_winning_bid": round(sum(won) / len(won), 2) if won else None,
        "confidence": "low" if (band_row["submitted"] if band_row else 0) < 5 else "ok",
    }  # fmt: skip


async def chat(db: AsyncSession, user: User, message: str, history: list[dict[str, str]]) -> str:
    facts = await briefing_facts(db, user)
    convo = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in history[-8:])
    return await ai.complete(
        "You are the assistant inside a freelancer's management app. Answer using the FACTS when relevant; if something is "
        "not in the facts, say you don't know. You cannot take actions; suggest what the user can do in the app. Be concise.",
        f"FACTS: {json.dumps(facts)}\n\n{convo}\nUSER: {message}", 600,
    )  # fmt: skip


def uid(s: str) -> uuid.UUID:
    return uuid.UUID(s)
