"""Job ↔ profile match scoring (0-100) with human-readable reasons."""

import re
from collections.abc import Iterable
from typing import Any

from app.models import Job, MasterProfile, SavedSearch


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def matched_skills(job: Job, skills: Iterable[str]) -> list[str]:
    text = _norm(f"{job.title} {job.description} {' '.join(job.skills)}")
    out = []
    for sk in skills:
        k = _norm(sk)
        if k and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text):
            out.append(sk)
    return out


def score_job(
    job: Job,
    master: MasterProfile | None,
    searches: list[SavedSearch],
    won_platforms: set[str],
) -> tuple[int, list[str]]:
    score, reasons = 0, []

    if master and master.skills:
        hits = matched_skills(job, master.skills)
        denom = max(3, min(len(job.skills) or 5, 6))
        pts = round(min(len(hits) / denom, 1) * 50)
        score += pts
        if hits:
            reasons.append(f"Skills match: {', '.join(hits[:5])} (+{pts})")
        else:
            reasons.append("No skills from your profile found in the post")
    else:
        reasons.append("Add skills to your master profile for better matching")

    rate = master.hourly_rate if master else None
    top = job.budget_max or job.budget_min
    if rate and top:
        target = rate if job.budget_type == "hourly" else rate * 5
        if top >= target:
            score += 20
            reasons.append("Budget meets your rate (+20)")
        elif top >= target * 0.7:
            score += 10
            reasons.append("Budget is slightly below your rate (+10)")
        else:
            reasons.append("Budget is well below your rate")
    elif top is None:
        score += 8
        reasons.append("Budget not stated (+8)")

    text = _norm(f"{job.title} {job.description}")
    best = 0
    for s in (x for x in searches if x.active and (not x.platforms or job.platform in x.platforms)):
        kws = [_norm(k) for k in s.keywords if k.strip()]
        if not kws:
            continue
        n = sum(1 for k in kws if k in text)
        if n:
            best = max(best, 20 if n == len(kws) else 12)
    if best:
        score += best
        reasons.append(f"Matches a saved search (+{best})")

    if job.platform in won_platforms:
        score += 5
        reasons.append("You've won work on this platform (+5)")
    c: dict[str, Any] = job.client or {}
    if c.get("verified") or float(c.get("rating") or 0) >= 4.5:
        score += 5
        reasons.append("Strong client signals (+5)")

    return min(score, 100), reasons


def suggest_bid(job: Job, master: MasterProfile | None) -> dict[str, Any]:
    rate = master.hourly_rate if master else None
    if job.budget_type == "hourly":
        if rate:
            hi = job.budget_max
            amt = min(rate, hi) if hi else rate
            return {
                "amount": round(amt, 2),
                "rationale": "Your hourly rate, capped at the client's maximum",
            }
        return {
            "amount": job.budget_max or job.budget_min,
            "rationale": "Set an hourly rate on your profile",
        }
    lo, hi = job.budget_min, job.budget_max
    if lo and hi:
        return {
            "amount": round(lo + (hi - lo) * 0.75, 2),
            "rationale": "75% of the way through the client's range",
        }
    if hi or lo:
        return {
            "amount": round((hi or lo or 0) * 0.9, 2),
            "rationale": "10% under the stated budget",
        }
    return {"amount": None, "rationale": "No budget stated - ask the client for scope first"}
