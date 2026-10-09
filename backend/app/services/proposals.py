import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditEntry, Job, MasterProfile, PlatformAccount, Proposal, Stage
from app.services.matching import matched_skills

VAR_RE = re.compile(r"\{(\w+)\}")


def render(template: str, variables: dict[str, str]) -> str:
    """Replace {var}; unknown variables are left visible so the user notices them."""
    return VAR_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), template)


def variables_for(job: Job, master: MasterProfile | None) -> dict[str, str]:
    client = (job.client or {}).get("name") or "there"
    skills = matched_skills(job, master.skills) if master else []
    return {
        "client_name": client.split()[0] if client != "there" else client,
        "job_title": job.title,
        "skill_match": ", ".join(skills[:4]),
        "my_name": (master.name if master else "") or "",
        "my_rate": f"{master.hourly_rate:g}" if master and master.hourly_rate else "",
        "platform": job.platform,
    }


def unresolved(body: str) -> list[str]:
    return sorted(set(VAR_RE.findall(body)))


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def move(db: AsyncSession, p: Proposal, stage: Stage, lost_reason: str = "") -> None:
    if stage == Stage.lost and not (lost_reason or p.lost_reason):
        raise ValueError("A reason is required when marking a proposal lost")
    if (
        stage in (Stage.submitted, Stage.viewed, Stage.interview, Stage.won)
        and p.submitted_at is None
    ):
        p.submitted_at = datetime.now(UTC)
    if lost_reason:
        p.lost_reason = lost_reason
    if p.stage != stage:
        p.stage, p.stage_changed_at = stage, datetime.now(UTC)
        top = (
            await db.execute(
                select(func.max(Proposal.position)).where(
                    Proposal.user_id == p.user_id, Proposal.stage == stage
                )
            )
        ).scalar()
        p.position = (top if top is not None else -1) + 1


async def credit_balance(db: AsyncSession, account_id: Any) -> int:
    return (
        await db.execute(
            select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
                CreditEntry.account_id == account_id
            )
        )
    ).scalar_one()


async def spend_credits(db: AsyncSession, acc: PlatformAccount | None, n: int, note: str) -> None:
    if acc is not None and n:
        db.add(CreditEntry(account_id=acc.id, delta=-n, note=note))


def price_band(amount: float | None) -> str:
    if amount is None:
        return "unknown"
    for limit, label in ((50, "<$50"), (200, "$50-200"), (500, "$200-500"), (1000, "$500-1k")):
        if amount < limit:
            return label
    return "$1k+"


def proposal_analytics(
    rows: list[tuple[Proposal, Job]], templates: dict[Any, str]
) -> dict[str, Any]:
    """Win rate by platform, template, price band, hour of day (only proposals that were submitted)."""

    def bucket(keyfn: Any) -> list[dict[str, Any]]:
        agg: dict[str, list[int]] = {}
        for p, j in rows:
            if p.submitted_at is None:
                continue
            k = str(keyfn(p, j))
            a = agg.setdefault(k, [0, 0])
            a[0] += 1
            a[1] += 1 if p.stage == Stage.won else 0
        return [
            {"key": k, "submitted": s, "won": w, "win_rate": round(w / s, 3)}
            for k, (s, w) in sorted(agg.items())
        ]

    submitted = [p for p, _ in rows if p.submitted_at]
    won = [p for p in submitted if p.stage == Stage.won]
    return {
        "submitted": len(submitted),
        "won": len(won),
        "win_rate": round(len(won) / len(submitted), 3) if submitted else 0.0,
        "by_platform": bucket(lambda p, j: j.platform),
        "by_template": bucket(lambda p, j: templates.get(p.template_id, "none")),
        "by_price_band": bucket(lambda p, j: price_band(p.bid_amount)),
        "by_hour": bucket(
            lambda p, j: f"{aware(p.submitted_at).hour:02d}" if p.submitted_at else "?"
        ),
    }
