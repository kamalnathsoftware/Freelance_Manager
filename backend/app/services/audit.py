import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def audit(
    db: AsyncSession, user_id: uuid.UUID | None, action: str, ip: str = "", **meta: Any
) -> None:
    db.add(AuditLog(user_id=user_id, action=action, ip=ip, meta=meta))
