import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import DB, CurrentAuth, CurrentUser, client_ip
from app.core.security import hash_password, verify_password
from app.models import AuditLog, AuthSession, TeamMember
from app.schemas import (
    AuditOut,
    ChangePasswordIn,
    Message,
    SessionOut,
    TotpCodeIn,
    TotpSetupOut,
    UserOut,
    UserUpdate,
)
from app.services import auth as svc
from app.services.audit import audit

router = APIRouter(prefix="/me", tags=["account"])


@router.get("", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("", response_model=UserOut)
async def update_me(body: UserUpdate, user: CurrentUser, db: DB) -> UserOut:
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(user, k, v)
    await db.commit()
    return UserOut.model_validate(user)


@router.post("/password", response_model=Message)
async def change_password(
    body: ChangePasswordIn, auth: CurrentAuth, db: DB, request: Request
) -> Message:
    user = auth.user
    if not user.password_hash or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await svc.revoke_all_sessions(db, user.id, except_id=auth.session_id)
    await audit(db, user.id, "account.password_changed", client_ip(request))
    await db.commit()
    return Message(detail="Password updated")


@router.post("/2fa/setup", response_model=TotpSetupOut)
async def setup_2fa(user: CurrentUser, db: DB) -> TotpSetupOut:
    secret, uri = svc.totp_setup(user)
    await db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/2fa/enable", response_model=Message)
async def enable_2fa(body: TotpCodeIn, user: CurrentUser, db: DB, request: Request) -> Message:
    svc.totp_enable(user, body.code)
    await audit(db, user.id, "account.2fa_enabled", client_ip(request))
    await db.commit()
    return Message(detail="Two-factor authentication enabled")


@router.post("/2fa/disable", response_model=Message)
async def disable_2fa(body: TotpCodeIn, user: CurrentUser, db: DB, request: Request) -> Message:
    if not user.totp_enabled or not svc.totp_check(user, body.code):
        raise HTTPException(400, "Invalid verification code")
    user.totp_enabled, user.totp_secret_enc = False, None
    await audit(db, user.id, "account.2fa_disabled", client_ip(request))
    await db.commit()
    return Message(detail="Two-factor authentication disabled")


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(auth: CurrentAuth, db: DB) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == auth.user.id, AuthSession.revoked.is_(False))
            .order_by(AuthSession.last_used_at.desc())
        )
    ).scalars()
    return [
        SessionOut(
            id=s.id,
            user_agent=s.user_agent,
            ip=s.ip,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            current=s.id == auth.session_id,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", response_model=Message)
async def revoke_session(session_id: uuid.UUID, auth: CurrentAuth, db: DB) -> Message:
    sess = await db.get(AuthSession, session_id)
    if sess is None or sess.user_id != auth.user.id:
        raise HTTPException(404, "Session not found")
    sess.revoked = True
    await audit(db, auth.user.id, "account.session_revoked", session=str(session_id))
    await db.commit()
    return Message(detail="Session revoked")


@router.get("/audit-log", response_model=list[AuditOut])
async def audit_log(user: CurrentUser, db: DB, limit: int = 50, offset: int = 0) -> list[AuditOut]:
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    ).scalars()
    return [AuditOut.model_validate(r) for r in rows]


@router.get("/export")
async def export_data(user: CurrentUser, db: DB) -> dict:
    """GDPR-style export of everything stored about the user. Extend as modules are added."""
    logs = (await db.execute(select(AuditLog).where(AuditLog.user_id == user.id))).scalars()
    team = (await db.execute(select(TeamMember).where(TeamMember.owner_id == user.id))).scalars()
    return {
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "audit_log": [AuditOut.model_validate(r).model_dump(mode="json") for r in logs],
        "team_members": [
            {"email": t.invite_email, "role": t.role.value, "created_at": t.created_at.isoformat()}
            for t in team
        ],
    }


@router.delete("", response_model=Message)
async def delete_account(body: ChangePasswordIn, user: CurrentUser, db: DB) -> Message:
    """Permanently delete the account. `current_password` is required; `new_password` is ignored."""
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Password is incorrect")
    await audit(db, None, "account.deleted")
    await db.delete(user)
    await db.commit()
    return Message(detail="Account deleted")
