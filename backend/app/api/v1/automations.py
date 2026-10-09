import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import AutomationRule, AutomationRun
from app.schemas import ORM, Message
from app.services import automation as svc
from app.services.common import get_owned

router = APIRouter(prefix="/automations", tags=["automations"])

# Ready-made rules (the examples from the product brief) the UI can instantiate with one click.
PRESETS: list[dict[str, Any]] = [
    {
        "key": "hot_job_alert",
        "name": "Hot job: alert + draft proposal",
        "trigger": "job.created",
        "conditions": [
            {"field": "score", "op": "gte", "value": 70},
            {"field": "budget_max", "op": "gt", "value": 200},
        ],
        "actions": [
            {
                "type": "notify",
                "params": {
                    "title": "Great match: {title}",
                    "body": "{platform} - {score}% match",
                    "channels": ["whatsapp", "push"],
                    "urgent": True,
                },
            },
            {"type": "draft_proposal", "params": {}},
        ],
    },
    {
        "key": "no_reply_followup",
        "name": "No reply in 48h: create follow-up task",
        "trigger": "conversation.stale",
        "conditions": [{"field": "hours_since_reply", "op": "gte", "value": 48}],
        "actions": [
            {"type": "create_task", "params": {"title": "Follow up: {subject}", "due_in_hours": 4}}
        ],
    },
    {
        "key": "review_after_delivery",
        "name": "Order completed: send review request",
        "trigger": "order.status_changed",
        "conditions": [{"field": "status", "op": "eq", "value": "completed"}],
        "actions": [
            {
                "type": "send_form",
                "params": {
                    "form_id": "",
                    "message": "Thanks for the order! Could you leave quick feedback? {link}",
                },
            }
        ],
    },
    {
        "key": "proposal_followup",
        "name": "Submitted proposal: remind me in 3 days",
        "trigger": "proposal.stage_changed",
        "conditions": [{"field": "stage", "op": "eq", "value": "submitted"}],
        "actions": [{"type": "set_follow_up", "params": {"in_days": 3}}],
    },
]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    trigger: str
    conditions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]]
    enabled: bool = True


class RuleOut(ORM):
    id: uuid.UUID
    name: str
    enabled: bool
    trigger: str
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    run_count: int
    last_run_at: datetime | None


class RunOut(ORM):
    id: uuid.UUID
    rule_id: uuid.UUID
    trigger: str
    status: str
    payload: dict[str, Any]
    log: list[str]
    created_at: datetime


class TestIn(BaseModel):
    payload: dict[str, Any] = {}


def _validate(body: RuleIn) -> None:
    try:
        svc.validate_rule(body.trigger, body.conditions, body.actions)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/meta")
async def meta(_: CurrentUser) -> dict[str, Any]:
    return {
        "triggers": [{"key": k, "label": v} for k, v in svc.TRIGGERS.items()],
        "operators": list(svc.OPS),
        "actions": list(svc.ACTIONS),
        "presets": PRESETS,
    }


@router.get("", response_model=list[RuleOut])
async def list_rules(user: CurrentUser, db: DB) -> list[AutomationRule]:
    return list(
        (
            await db.execute(
                select(AutomationRule)
                .where(AutomationRule.user_id == user.id)
                .order_by(AutomationRule.created_at)
            )
        ).scalars()
    )


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(body: RuleIn, user: CurrentUser, db: DB) -> AutomationRule:
    _validate(body)
    r = AutomationRule(user_id=user.id, **body.model_dump())
    db.add(r)
    await db.commit()
    return r


@router.put("/{rid}", response_model=RuleOut)
async def update_rule(rid: uuid.UUID, body: RuleIn, user: CurrentUser, db: DB) -> AutomationRule:
    _validate(body)
    r = await get_owned(db, AutomationRule, rid, user.id)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    await db.commit()
    return r


@router.post("/{rid}/toggle", response_model=RuleOut)
async def toggle(rid: uuid.UUID, user: CurrentUser, db: DB) -> AutomationRule:
    r = await get_owned(db, AutomationRule, rid, user.id)
    r.enabled = not r.enabled
    await db.commit()
    return r


@router.delete("/{rid}", response_model=Message)
async def delete_rule(rid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, AutomationRule, rid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.post("/{rid}/test")
async def test_rule(rid: uuid.UUID, body: TestIn, user: CurrentUser, db: DB) -> dict[str, Any]:
    """Dry run: shows whether the sample event matches and what each action *would* do. Changes nothing."""
    r = await get_owned(db, AutomationRule, rid, user.id)
    res = await svc.dry_run(db, r, body.payload)
    await db.rollback()
    return res


@router.get("/{rid}/runs", response_model=list[RunOut])
async def runs(rid: uuid.UUID, user: CurrentUser, db: DB, limit: int = 50) -> list[AutomationRun]:
    await get_owned(db, AutomationRule, rid, user.id)
    return list(
        (
            await db.execute(
                select(AutomationRun)
                .where(AutomationRun.rule_id == rid)
                .order_by(AutomationRun.created_at.desc())
                .limit(min(limit, 200))
            )
        ).scalars()
    )


@router.get("/runs/recent", response_model=list[RunOut])
async def recent_runs(user: CurrentUser, db: DB, limit: int = 50) -> list[AutomationRun]:
    return list(
        (
            await db.execute(
                select(AutomationRun)
                .where(AutomationRun.user_id == user.id)
                .order_by(AutomationRun.created_at.desc())
                .limit(min(limit, 200))
            )
        ).scalars()
    )
