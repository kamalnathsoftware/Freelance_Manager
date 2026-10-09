import uuid
from datetime import datetime

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import DB, CurrentAuth
from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.models import Role, TeamMember, User
from app.schemas import ORM, Message
from app.services.audit import audit
from app.services.email import send_email

router = APIRouter(tags=["team"])

ASSIGNABLE = {Role.full, Role.messaging_only, Role.view_only}
ROLE_HELP = {
    "full": "Everything except account, security, credentials and team management",
    "messaging_only": "Read and reply in the inbox; view clients",
    "view_only": "Read-only access to workspace data",
}


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.view_only


class RoleIn(BaseModel):
    role: Role


class MemberOut(ORM):
    id: uuid.UUID
    invite_email: str
    role: Role
    created_at: datetime
    accepted: bool = False


class AcceptIn(BaseModel):
    token: str


def _only_self(auth: CurrentAuth) -> User:
    if auth.actor.id != auth.user.id:
        raise HTTPException(403, "Only the workspace owner can manage the team")
    return auth.user


def _m(t: TeamMember) -> MemberOut:
    o = MemberOut.model_validate(t)
    o.accepted = t.member_user_id is not None
    return o


@router.get("/team")
async def list_team(auth: CurrentAuth, db: DB) -> dict[str, object]:
    owner = _only_self(auth)
    rows = (
        await db.execute(
            select(TeamMember)
            .where(TeamMember.owner_id == owner.id)
            .order_by(TeamMember.created_at)
        )
    ).scalars()
    return {"members": [_m(t).model_dump(mode="json") for t in rows], "roles": ROLE_HELP}


@router.post("/team/invite", response_model=MemberOut, status_code=201)
async def invite(body: InviteIn, auth: CurrentAuth, db: DB) -> MemberOut:
    owner = _only_self(auth)
    if body.role not in ASSIGNABLE:
        raise HTTPException(422, "role must be full, messaging_only or view_only")
    email = body.email.lower()
    if email == owner.email:
        raise HTTPException(422, "You are already the owner")
    if (
        await db.execute(
            select(TeamMember.id).where(
                TeamMember.owner_id == owner.id, TeamMember.invite_email == email
            )
        )
    ).first():
        raise HTTPException(409, "That person is already invited")
    tm = TeamMember(owner_id=owner.id, invite_email=email, role=body.role)
    db.add(tm)
    await db.flush()
    token = create_purpose_token(tm.id, "team_invite", 60 * 24 * 7)
    link = f"{get_settings().web_base_url}/accept-invite?token={token}"
    await send_email(
        email,
        f"{owner.full_name or owner.email} invited you to Freelance Manager",
        f"You've been invited as {body.role.value.replace('_', ' ')}. Sign in with this email address and accept: {link}\n\nThe link expires in 7 days.",
    )
    await audit(db, owner.id, "team.invited", email=email, role=body.role.value)
    await db.commit()
    return _m(tm)


@router.post("/team/accept", response_model=Message)
async def accept(body: AcceptIn, auth: CurrentAuth, db: DB) -> Message:
    try:
        tm_id = decode_purpose_token(body.token, "team_invite")
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid or expired invitation") from None
    tm = await db.get(TeamMember, tm_id)
    me = auth.actor
    if tm is None or tm.invite_email != me.email.lower():
        raise HTTPException(403, "This invitation was sent to a different email address")
    if tm.member_user_id and tm.member_user_id != me.id:
        raise HTTPException(409, "This invitation was already used")
    tm.member_user_id = me.id
    await audit(db, tm.owner_id, "team.accepted", member=me.email)
    await db.commit()
    return Message(detail="Invitation accepted")


@router.patch("/team/{tid}", response_model=MemberOut)
async def change_role(tid: uuid.UUID, body: RoleIn, auth: CurrentAuth, db: DB) -> MemberOut:
    owner = _only_self(auth)
    tm = await db.get(TeamMember, tid)
    if tm is None or tm.owner_id != owner.id:
        raise HTTPException(404, "Member not found")
    if body.role not in ASSIGNABLE:
        raise HTTPException(422, "role must be full, messaging_only or view_only")
    tm.role = body.role
    await audit(db, owner.id, "team.role_changed", email=tm.invite_email, role=body.role.value)
    await db.commit()
    return _m(tm)


@router.delete("/team/{tid}", response_model=Message)
async def remove(tid: uuid.UUID, auth: CurrentAuth, db: DB) -> Message:
    owner = _only_self(auth)
    tm = await db.get(TeamMember, tid)
    if tm is None or tm.owner_id != owner.id:
        raise HTTPException(404, "Member not found")
    await audit(db, owner.id, "team.removed", email=tm.invite_email)
    await db.delete(tm)
    await db.commit()
    return Message(detail="Removed")


@router.get("/me/workspaces")
async def workspaces(auth: CurrentAuth, db: DB) -> list[dict[str, object]]:
    me = auth.actor
    out: list[dict[str, object]] = [
        {
            "owner_id": str(me.id),
            "name": me.full_name or me.email,
            "email": me.email,
            "role": "owner",
            "is_self": True,
        }
    ]
    rows = (
        await db.execute(
            select(TeamMember, User)
            .join(User, User.id == TeamMember.owner_id)
            .where(TeamMember.member_user_id == me.id)
        )
    ).all()
    for tm, owner in rows:
        out.append(
            {
                "owner_id": str(owner.id),
                "name": owner.full_name or owner.email,
                "email": owner.email,
                "role": tm.role.value,
                "is_self": False,
            }
        )
    return out
