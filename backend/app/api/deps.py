import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import AuditLog, AuthSession, TeamMember, User

bearer = HTTPBearer(auto_error=False)
DB = Annotated[AsyncSession, Depends(get_db)]


class Auth:
    """`user` is the *effective* workspace owner (whose data is read/written); `actor` is who is logged in."""

    def __init__(
        self, user: User, session_id: uuid.UUID, actor: User | None = None, role: str = "owner"
    ) -> None:
        self.user, self.session_id = user, session_id
        self.actor = actor or user
        self.role = role


API = "/api/v1"
# Never available to team members, whatever their role (account, security, credentials, billing-ish).
MEMBER_BLOCKED_PREFIXES = (
    f"{API}/me", f"{API}/api-keys", f"{API}/team", f"{API}/ingest/gmail", f"{API}/calendar/google",
    f"{API}/notifications/channels", f"{API}/notifications/devices", f"{API}/profile/contact", f"{API}/ops", f"{API}/auth",
)  # fmt: skip
MEMBER_ALWAYS_OK = (f"{API}/auth/logout", f"{API}/me/workspaces")
MESSAGING_GET = tuple(
    f"{API}/{p}"
    for p in (
        "conversations",
        "clients",
        "canned-responses",
        "search",
        "notifications",
        "platforms/catalog",
        "widget",
    )
)
MESSAGING_WRITE = tuple(
    f"{API}/{p}"
    for p in (
        "conversations",
        "messages",
        "canned-responses",
        "ai/translate",
        "ai/tone-check",
        "notifications",
    )
)


def member_allowed(role: str, method: str, path: str) -> bool:
    """Permission matrix for team members. `full` = everything not blocked; `messaging_only` = inbox work;
    `view_only` = read-only."""
    if path in MEMBER_ALWAYS_OK:
        return True
    if path.startswith(MEMBER_BLOCKED_PREFIXES) or path.endswith("/token"):
        return False
    read = method in ("GET", "HEAD")
    if role == "full":
        return True
    if role == "view_only":
        return read
    if role == "messaging_only":
        if read:
            return path.startswith(MESSAGING_GET)
        return method in ("POST", "PATCH", "PUT") and path.startswith(MESSAGING_WRITE)
    return False


async def current_auth(
    request: Request,
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_workspace: Annotated[str | None, Header()] = None,
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
    if not x_workspace or x_workspace == str(user.id):
        return Auth(user, sess.id)
    try:
        owner_id = uuid.UUID(x_workspace)
    except ValueError:
        raise HTTPException(400, "Invalid X-Workspace header") from None
    tm = (
        await db.execute(
            select(TeamMember).where(
                TeamMember.owner_id == owner_id, TeamMember.member_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    owner = await db.get(User, owner_id)
    if tm is None or owner is None or not owner.is_active:
        raise HTTPException(403, "You are not a member of that workspace")
    if not member_allowed(tm.role.value, request.method, request.url.path):
        raise HTTPException(
            403, f"Your role ({tm.role.value.replace('_', ' ')}) does not allow this action"
        )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        db.add(
            AuditLog(
                user_id=owner.id,
                action="team.member_action",
                ip=request.client.host if request.client else "",
                meta={
                    "actor": str(user.id),
                    "actor_email": user.email,
                    "role": tm.role.value,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
        )
    return Auth(owner, sess.id, actor=user, role=tm.role.value)


CurrentAuth = Annotated[Auth, Depends(current_auth)]


async def current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(current_user)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""
