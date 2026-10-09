import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import AuthSession, User

bearer = HTTPBearer(auto_error=False)
DB = Annotated[AsyncSession, Depends(get_db)]


class Auth:
    def __init__(self, user: User, session_id: uuid.UUID) -> None:
        self.user, self.session_id = user, session_id


async def current_auth(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Auth:
    unauth = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauth
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauth from None
    sess = await db.get(AuthSession, uuid.UUID(payload["sid"]))
    if sess is None or sess.revoked:
        raise unauth
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise unauth
    return Auth(user, sess.id)


CurrentAuth = Annotated[Auth, Depends(current_auth)]


async def current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(current_user)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""
