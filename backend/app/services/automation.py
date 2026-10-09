"""If/then rule engine. Services call `fire()` at key moments; matching rules run their actions inline.

Safety: rules can only act inside the owner's own data; no outbound HTTP/webhook action (SSRF); a rule that
fires > MAX_RUNS_PER_HOUR is skipped; every run is logged; actions never fire further triggers (no loops);
client-facing sends are 'assisted' (saved for the user to paste) unless the thread is a direct chat.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AutomationRule, AutomationRun

log = logging.getLogger(__name__)

TRIGGERS: dict[str, str] = {
    "job.created": "A new job arrives",
    "message.received": "A client message arrives",
    "conversation.stale": "A conversation has had no reply for N hours",
    "proposal.stage_changed": "A proposal moves to a new stage",
    "proposal.stale": "A submitted proposal has had no outcome for N days",
    "order.status_changed": "An order changes status",
    "payment.received": "A payment is recorded",
    "form.submitted": "A form is submitted",
}
OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "exists")
ACTIONS = (
    "notify",
    "draft_proposal",
    "create_task",
    "send_form",
    "add_label",
    "star_conversation",
    "set_follow_up",
)
MAX_RUNS_PER_HOUR = 50
MAX_ACTIONS = 8


def _num(x: Any) -> float:
    return float(x)


def check(cond: dict[str, Any], payload: dict[str, Any]) -> bool:
    field, op, want = cond.get("field", ""), cond.get("op", "eq"), cond.get("value")
    if op == "exists":
        return payload.get(field) not in (None, "")
    if field not in payload:
        return False
    have = payload[field]
    try:
        if op == "eq":
            return str(have).lower() == str(want).lower()
        if op == "ne":
            return str(have).lower() != str(want).lower()
        if op == "gt":
            return _num(have) > _num(want)
        if op == "gte":
            return _num(have) >= _num(want)
        if op == "lt":
            return _num(have) < _num(want)
        if op == "lte":
            return _num(have) <= _num(want)
        if op == "contains":
            return (
                str(want).lower()
                in (" ".join(map(str, have)) if isinstance(have, list) else str(have)).lower()
            )
        if op == "in":
            return str(have).lower() in [
                str(x).lower() for x in (want if isinstance(want, list) else [want])
            ]
    except (TypeError, ValueError):
        return False
    return False


def matches(rule: AutomationRule, payload: dict[str, Any]) -> bool:
    return all(check(c, payload) for c in rule.conditions)


class _Safe(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def tpl(text: Any, payload: dict[str, Any]) -> str:
    try:
        return str(text).format_map(
            _Safe({k: v for k, v in payload.items() if isinstance(v, str | int | float | bool)})
        )
    except (ValueError, IndexError, KeyError, AttributeError):
        return str(text)


def validate_rule(
    trigger: str, conditions: list[dict[str, Any]], actions: list[dict[str, Any]]
) -> None:
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown trigger '{trigger}'")
    for c in conditions:
        if c.get("op", "eq") not in OPS or not c.get("field"):
            raise ValueError("Each condition needs a field and a valid operator")
    if not actions:
        raise ValueError("A rule needs at least one action")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"At most {MAX_ACTIONS} actions per rule")
    for a in actions:
        if a.get("type") not in ACTIONS:
            raise ValueError(f"Unknown action '{a.get('type')}'")


async def fire(
    db: AsyncSession,
    user_id: uuid.UUID,
    trigger: str,
    payload: dict[str, Any],
    dedupe_key: str | None = None,
) -> int:
    """Run every enabled matching rule. Never raises."""
    try:
        rules = list(
            (
                await db.execute(
                    select(AutomationRule).where(
                        AutomationRule.user_id == user_id,
                        AutomationRule.trigger == trigger,
                        AutomationRule.enabled.is_(True),
                    )
                )
            ).scalars()
        )
        ran = 0
        for rule in rules:
            if not matches(rule, payload):
                continue
            if await _run(db, rule, payload, dedupe_key, dry_run=False):
                ran += 1
        return ran
    except Exception:
        log.exception("automation fire failed trigger=%s", trigger)
        return 0


async def _run(
    db: AsyncSession,
    rule: AutomationRule,
    payload: dict[str, Any],
    dedupe_key: str | None,
    *,
    dry_run: bool,
) -> AutomationRun | None:
    if dedupe_key and not dry_run:
        if (
            await db.execute(
                select(AutomationRun.id).where(
                    AutomationRun.rule_id == rule.id, AutomationRun.dedupe_key == dedupe_key
                )
            )
        ).first():
            return None
    if not dry_run:
        since = datetime.now(UTC) - timedelta(hours=1)
        recent = (
            await db.execute(
                select(func.count(AutomationRun.id)).where(
                    AutomationRun.rule_id == rule.id,
                    AutomationRun.created_at >= since,
                    AutomationRun.status != "skipped",
                )
            )
        ).scalar_one()
        if recent >= MAX_RUNS_PER_HOUR:
            db.add(
                AutomationRun(
                    rule_id=rule.id,
                    user_id=rule.user_id,
                    trigger=rule.trigger,
                    status="skipped",
                    payload=payload,
                    log=["rate limit reached"],
                )
            )
            await db.flush()
            return None
    run = AutomationRun(
        rule_id=rule.id,
        user_id=rule.user_id,
        trigger=rule.trigger,
        status="dry_run" if dry_run else "ok",
        dedupe_key=None if dry_run else dedupe_key,
        payload=_jsonable(payload),
        log=[],
    )
    for a in rule.actions:
        try:
            entry = await _do(db, rule, a, payload, dry_run)
            run.log = [*run.log, f"{a['type']}: {entry}"]
        except Exception as e:
            log.exception("automation action failed rule=%s", rule.id)
            run.status = "error" if not dry_run else run.status
            run.log = [*run.log, f"{a['type']}: ERROR {type(e).__name__}: {e}"]
    if not dry_run:
        rule.run_count += 1
        rule.last_run_at = datetime.now(UTC)
    db.add(run)
    await db.flush()
    return run


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (v if isinstance(v, str | int | float | bool | list | dict | type(None)) else str(v))
        for k, v in d.items()
    }


async def dry_run(
    db: AsyncSession, rule: AutomationRule, payload: dict[str, Any]
) -> dict[str, Any]:
    ok = matches(rule, payload)
    run = await _run(db, rule, payload, None, dry_run=True) if ok else None
    return {"matched": ok, "actions": run.log if run else []}


async def _do(
    db: AsyncSession,
    rule: AutomationRule,
    action: dict[str, Any],
    payload: dict[str, Any],
    dry: bool,
) -> str:
    from app.models import (
        Conversation,
        Form,
        Job,
        Project,
        Proposal,
        ProposalTemplate,
        Stage,
        Task,
        User,
    )
    from app.services import ai, inbox, notifications
    from app.services import proposals as prop_svc

    t, p = action["type"], action.get("params", {}) or {}
    uid = rule.user_id
    if t == "notify":
        chans = set(p.get("channels") or []) or None
        title, body = tpl(p.get("title", rule.name), payload), tpl(p.get("body", ""), payload)
        if dry:
            return f"would notify '{title}' via {sorted(chans) if chans else 'preferences'}"
        user = await db.get(User, uid)
        assert user is not None
        await notifications.notify(
            db,
            user,
            "automation",
            title,
            body,
            url=p.get("url", ""),
            priority="high" if p.get("urgent") else "normal",
            only_channels=chans,
        )
        return f"notified '{title}'"
    if t == "draft_proposal":
        job_id = payload.get("job_id")
        if not job_id:
            return "skipped: no job in this event"
        if dry:
            return "would create a proposal draft"
        job = await db.get(Job, uuid.UUID(str(job_id)))
        if job is None or job.user_id != uid:
            return "skipped: job not found"
        prop = (
            await db.execute(
                select(Proposal).where(Proposal.job_id == job.id, Proposal.user_id == uid)
            )
        ).scalar_one_or_none()
        if prop is None:
            prop = Proposal(user_id=uid, job_id=job.id, stage=Stage.shortlisted)
            db.add(prop)
            await db.flush()
        from app.models import MasterProfile

        master = (
            await db.execute(select(MasterProfile).where(MasterProfile.user_id == uid))
        ).scalar_one_or_none()
        vars_ = prop_svc.variables_for(job, master)
        if p.get("template_id"):
            tmpl = await db.get(ProposalTemplate, uuid.UUID(str(p["template_id"])))
            if tmpl and tmpl.user_id == uid:
                prop.body, prop.template_id = prop_svc.render(tmpl.body, vars_), tmpl.id
        elif p.get("use_ai"):
            prop.body = await ai.complete(
                "You write concise, specific freelance proposals. Return only the text.",
                f"JOB: {job.title}\n{job.description[:2500]}\nME: {master.headline if master else ''}; skills {', '.join((master.skills if master else [])[:10])}",
                700,
            )
            prop.ai_generated = True
        if prop.body:
            prop.approved_at = None
            await prop_svc.move(db, prop, Stage.drafted)
        return f"drafted proposal {prop.id} (needs your approval before sending)"
    if t == "create_task":
        title = tpl(p.get("title", "Follow up"), payload)
        if dry:
            return f"would create task '{title}'"
        pid = p.get("project_id")
        project = await db.get(Project, uuid.UUID(str(pid))) if pid else None
        if project is None or project.user_id != uid:
            project = (
                await db.execute(
                    select(Project).where(Project.user_id == uid, Project.name == "Inbox")
                )
            ).scalar_one_or_none()
            if project is None:
                project = Project(
                    user_id=uid, name="Inbox", description="Tasks created by automations"
                )
                db.add(project)
                await db.flush()
        due = datetime.now(UTC) + timedelta(hours=float(p.get("due_in_hours", 24)))
        db.add(Task(user_id=uid, project_id=project.id, title=title, due_at=due))
        return f"created task '{title}'"
    if t == "send_form":
        cid, form_id = payload.get("conversation_id"), p.get("form_id")
        if dry:
            return "would add a message with the form link to the client thread"
        form = await db.get(Form, uuid.UUID(str(form_id))) if form_id else None
        if form is None or form.user_id != uid or not form.published:
            return "skipped: form missing or not published"
        conv = await db.get(Conversation, uuid.UUID(str(cid))) if cid else None
        if conv is None and payload.get("client_id"):
            conv = (
                (
                    await db.execute(
                        select(Conversation)
                        .where(
                            Conversation.user_id == uid,
                            Conversation.client_id == uuid.UUID(str(payload["client_id"])),
                        )
                        .order_by(Conversation.last_message_at.desc())
                    )
                )
                .scalars()
                .first()
            )
        if conv is None or conv.user_id != uid:
            return "skipped: no conversation to send to"
        from app.core.config import get_settings

        link = f"{get_settings().web_base_url}/f/{form.public_key}"
        msg, _ = await inbox.add_outbound(
            db,
            conv,
            tpl(
                p.get("message", "Could you fill in this short form? {link}"),
                {**payload, "link": link},
            ),
            delivery="sent" if conv.platform == "direct" else "pending_manual",
            idempotency_key=f"auto:{rule.id}:{conv.id}:{form.id}",
        )
        return f"queued form link in thread {conv.id} ({msg.delivery}" + (
            ": paste it on the platform)" if msg.delivery == "pending_manual" else ")"
        )
    if t in ("add_label", "star_conversation"):
        cid = payload.get("conversation_id")
        if dry:
            return f"would {t}"
        conv = await db.get(Conversation, uuid.UUID(str(cid))) if cid else None
        if conv is None or conv.user_id != uid:
            return "skipped: no conversation"
        if t == "add_label":
            conv.labels = sorted({*conv.labels, tpl(p.get("label", "automated"), payload)})
        else:
            conv.starred = True
        return "ok"
    if t == "set_follow_up":
        pid = payload.get("proposal_id")
        if dry:
            return "would set follow-up"
        prop = await db.get(Proposal, uuid.UUID(str(pid))) if pid else None
        if prop is None or prop.user_id != uid:
            return "skipped: no proposal"
        prop.follow_up_at = datetime.now(UTC) + timedelta(days=float(p.get("in_days", 3)))
        return f"follow-up set for {prop.follow_up_at:%Y-%m-%d}"
    raise ValueError(f"unknown action {t}")


# --------- scheduled triggers ---------
async def scan_stale(db: AsyncSession, now: datetime | None = None) -> int:
    """Fire conversation.stale / proposal.stale for rules that exist (runs every few minutes via Celery)."""
    from app.models import Conversation, ConvStatus, Job, Message, Proposal, Stage

    now = now or datetime.now(UTC)
    fired = 0
    rules = list(
        (
            await db.execute(
                select(AutomationRule).where(
                    AutomationRule.enabled.is_(True),
                    AutomationRule.trigger.in_(["conversation.stale", "proposal.stale"]),
                )
            )
        ).scalars()
    )
    by_user: dict[uuid.UUID, list[AutomationRule]] = {}
    for r in rules:
        by_user.setdefault(r.user_id, []).append(r)
    for uid, urules in by_user.items():
        if any(r.trigger == "conversation.stale" for r in urules):
            for c in (
                await db.execute(
                    select(Conversation).where(
                        Conversation.user_id == uid, Conversation.status == ConvStatus.open
                    )
                )
            ).scalars():
                last = (
                    (
                        await db.execute(
                            select(Message)
                            .where(Message.conversation_id == c.id)
                            .order_by(Message.created_at.desc())
                        )
                    )
                    .scalars()
                    .first()
                )
                if last is None or last.direction != "out":
                    continue
                hours = (now - _aware(last.created_at)).total_seconds() / 3600
                payload = {
                    "conversation_id": str(c.id),
                    "platform": c.platform,
                    "subject": c.subject,
                    "hours_since_reply": round(hours, 1),
                    "client_id": str(c.client_id or ""),
                }
                fired += await fire(
                    db, uid, "conversation.stale", payload, dedupe_key=f"stale:{c.id}:{last.id}"
                )
        if any(r.trigger == "proposal.stale" for r in urules):
            rows = await db.execute(
                select(Proposal, Job)
                .join(Job, Job.id == Proposal.job_id)
                .where(Proposal.user_id == uid, Proposal.stage.in_([Stage.submitted, Stage.viewed]))
            )
            for p, j in rows.all():
                if p.submitted_at is None:
                    continue
                days = (now - _aware(p.submitted_at)).total_seconds() / 86400
                fired += await fire(
                    db,
                    uid,
                    "proposal.stale",
                    {
                        "proposal_id": str(p.id),
                        "job_title": j.title,
                        "platform": j.platform,
                        "days_since_submitted": round(days, 1),
                    },
                    dedupe_key=f"pstale:{p.id}",
                )
    return fired


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
