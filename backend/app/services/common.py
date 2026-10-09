import uuid
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def get_owned(db: AsyncSession, model: type[T], obj_id: uuid.UUID, user_id: uuid.UUID) -> T:
    """Fetch a row owned by user_id or raise 404 (never reveal other users' rows)."""
    obj = await db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", user_id) != user_id:
        raise HTTPException(404, f"{model.__name__} not found")  # type: ignore[attr-defined]
    return obj
