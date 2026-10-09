import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, bearer
from app.core.security import decode_access_token
from app.models import User
from app.services.ingest import resolve_api_key


async def ingest_user(
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> User:
    """Ingest endpoints accept either a normal bearer token or a scoped `X-API-Key` (browser extension)."""
    user = await _by_key(db, x_api_key) if x_api_key else None
    if user is None and creds is not None:
        try:
            user = await db.get(User, uuid.UUID(decode_access_token(creds.credentials)["sub"]))
        except (jwt.PyJWTError, ValueError):
            user = None
    if user is None or not user.is_active:
        raise HTTPException(401, "Not authenticated")
    return user


async def _by_key(db: AsyncSession, raw: str) -> User | None:
    key = await resolve_api_key(db, raw)
    if key is None or "ingest" not in key.scopes:
        return None
    return await db.get(User, key.user_id)


IngestUser = Annotated[User, Depends(ingest_user)]
