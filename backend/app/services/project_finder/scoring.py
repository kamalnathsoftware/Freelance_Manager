"""Fit score (0-100) of a job against the user's skills and keyword filters, with reasons.

Transparent on purpose: every point is explained so the user can tune their skills list."""

import re
from datetime import UTC, datetime

from app.models import PFSettings

# Max points per component; they sum to exactly 100.
W_SKILLS, W_KEYWORDS, W_REMOTE, W_FRESH, W_BUDGET = 70, 10, 8, 8, 4
SKILL_TITLE, SKILL_BODY = 20, 8
KEYWORD_TITLE, KEYWORD_BODY = 4, 2


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def has_term(text: str, term: str) -> bool:
    """Whole-word match that also works for terms like "next.js", "c++" or "ci/cd"."""
    t = norm(term)
    return bool(t) and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text) is not None


def _freshness(posted_at: datetime | None, now: datetime) -> tuple[int, str]:
    if posted_at is None:
        return 0, ""
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    days = (now - posted_at).total_seconds() / 86400
    for limit, pts, label in (
        (1, 8, "today"),
        (3, 6, "in the last 3 days"),
        (7, 3, "this week"),
        (14, 1, "in the last 2 weeks"),
    ):
        if days <= limit:
            return pts, label
    return 0, ""


def score_job(
    cfg: PFSettings,
    *,
    title: str,
    description: str,
    tags: list[str],
    remote: bool,
    budget: str,
    posted_at: datetime | None,
    now: datetime | None = None,
) -> tuple[int, list[str], list[str]]:
    """Returns (score, reasons, matched_skills). A hit in an exclude keyword (title or body) zeroes the
    score. `matched_skills` + keyword hits tell the caller whether the job is relevant at all."""
    now = now or datetime.now(UTC)
    t_title = norm(title)
    t_body = norm(f"{description} {' '.join(tags)}")
    reasons: list[str] = []

    for kw in cfg.exclude_keywords:
        if has_term(t_title, kw) or has_term(t_body, kw):
            return 0, [f"Excluded keyword: {kw}"], []

    skill_pts, matched = 0, []
    for sk in cfg.skills:
        if has_term(t_title, sk):
            skill_pts += SKILL_TITLE
            matched.append(sk)
        elif has_term(t_body, sk):
            skill_pts += SKILL_BODY
            matched.append(sk)
    skill_pts = min(skill_pts, W_SKILLS)
    if matched:
        reasons.append(f"Skills: {', '.join(matched[:6])} (+{skill_pts})")

    kw_pts, kw_hits = 0, []
    for kw in cfg.include_keywords:
        if has_term(t_title, kw):
            kw_pts += KEYWORD_TITLE
            kw_hits.append(kw)
        elif has_term(t_body, kw):
            kw_pts += KEYWORD_BODY
            kw_hits.append(kw)
    kw_pts = min(kw_pts, W_KEYWORDS)
    if kw_hits:
        reasons.append(f"Keywords: {', '.join(kw_hits[:6])} (+{kw_pts})")

    total = skill_pts + kw_pts
    if remote:
        total += W_REMOTE
        reasons.append(f"Remote (+{W_REMOTE})")
    fresh, label = _freshness(posted_at, now)
    if fresh:
        total += fresh
        reasons.append(f"Posted {label} (+{fresh})")
    if budget:
        total += W_BUDGET
        reasons.append(f"Budget stated (+{W_BUDGET})")
    if not matched and not kw_hits:
        reasons.append("No skills or keywords from your list found")
        # Only skills/keywords make a job relevant; remote + fresh + budget alone must not rank one highly.
        total = min(total, 10)
    return min(total, 100), reasons, matched + [k for k in kw_hits if k not in matched]
