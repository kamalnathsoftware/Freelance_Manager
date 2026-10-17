"""Project Finder services. Everything is scoped by `user_id` (the effective workspace owner)."""

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PFSettings

DEFAULT_SKILLS = [
    "python", "fastapi", "react", "next.js", "qa", "test automation", "playwright", "cypress",
    "selenium", "ai", "document ai", "ocr", "n8n", "automation",
]  # fmt: skip


def valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


async def get_pf_settings(db: AsyncSession, user_id: uuid.UUID) -> PFSettings:
    """The user's settings row, created with defaults on first use."""
    row = (
        await db.execute(select(PFSettings).where(PFSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = PFSettings(user_id=user_id, skills=list(DEFAULT_SKILLS))
        db.add(row)
        await db.flush()
    return row
