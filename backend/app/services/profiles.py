"""Master/platform profile logic: derive, drift detection, completeness scoring."""

from typing import Any

from app.adapters.rules import RULES
from app.models import MasterProfile, PlatformProfile

SYNC_FIELDS = ("headline", "bio", "skills", "hourly_rate")


def master_snapshot(m: MasterProfile) -> dict[str, Any]:
    return {f: getattr(m, f) for f in SYNC_FIELDS}


def fit(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[: limit - 1]
    if text[limit - 1] != " ":  # mid-word: back up to the previous word boundary
        head = head.rsplit(" ", 1)[0] if " " in head else head
    return head.rstrip(",.;:- ") + "…"


def derive_for_platform(m: MasterProfile, platform: str) -> dict[str, Any]:
    rules = RULES[platform]
    return {
        "headline": fit(m.headline, rules.headline_max) if rules.headline_max else "",
        "bio": fit(m.bio, rules.bio_max),
        "skills": list(m.skills)[: rules.skills_max],
        "hourly_rate": m.hourly_rate,
    }


def apply_derived(pp: PlatformProfile, derived: dict[str, Any], m: MasterProfile) -> None:
    for k, v in derived.items():
        setattr(pp, k, v)
    pp.synced_master = master_snapshot(m)


def sync_status(pp: PlatformProfile | None, m: MasterProfile | None) -> str:
    """in_sync | drifted | missing. Drifted = master changed since this variant was last derived."""
    if pp is None:
        return "missing"
    if m is None or pp.synced_master == master_snapshot(m):
        return "in_sync"
    return "drifted"


def diff(pp: PlatformProfile, m: MasterProfile) -> list[dict[str, Any]]:
    out = []
    for f in SYNC_FIELDS:
        a, b = getattr(m, f), getattr(pp, f)
        out.append({"field": f, "master": a, "platform": b, "same": a == b})
    return out


def completeness(m: MasterProfile | None, platform: str | None = None) -> dict[str, Any]:
    checks: list[tuple[str, bool, int]] = []
    if m is None:
        return {"score": 0, "checklist": [{"item": "Create your master profile", "done": False}]}
    checks += [
        ("Add your name", bool(m.name), 5),
        ("Write a headline", bool(m.headline), 15),
        ("Write a bio of at least 300 characters", len(m.bio) >= 300, 20),
        ("Add at least 5 skills", len(m.skills) >= 5, 15),
        ("Set an hourly rate", m.hourly_rate is not None, 10),
        ("Add languages", bool(m.languages), 5),
        ("Add location and timezone", bool(m.location and m.timezone), 5),
        ("Add work experience", bool(m.experience), 10),
        ("Add education or certifications", bool(m.education or m.certifications), 5),
        ("State your availability", bool(m.availability), 10),
    ]
    if platform and platform in RULES:
        r = RULES[platform]
        if r.headline_max:
            checks.append(
                (
                    f"Headline within {r.headline_max} characters",
                    0 < len(m.headline) <= r.headline_max,
                    0,
                )
            )
        checks.append((f"Bio within {r.bio_max} characters", 0 < len(m.bio) <= r.bio_max, 0))
    total = sum(w for _, _, w in checks) or 1
    got = sum(w for _, ok, w in checks if ok)
    return {
        "score": round(100 * got / total),
        "checklist": [{"item": i, "done": ok} for i, ok, _ in checks],
    }
