import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.security import (
    create_access_token,
    create_purpose_token,
    decode_purpose_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.models import AuthSession, User
from app.schemas import TokenPair
from app.services.audit import audit
from app.services.email import send_email


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()


async def issue_tokens(db: AsyncSession, user: User, user_agent: str, ip: str) -> TokenPair:
    s = get_settings()
    refresh = new_refresh_token()
    sess = AuthSession(
        user_id=user.id,
        refresh_hash=hash_token(refresh),
        user_agent=user_agent[:300],
        ip=ip,
        expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
    )
    db.add(sess)
    await db.flush()
    return TokenPair(access_token=create_access_token(user.id, sess.id), refresh_token=refresh)


async def send_verification(user: User) -> None:
    token = create_purpose_token(user.id, "verify_email", 60 * 24)
    url = f"{get_settings().web_base_url}/verify-email?token={token}"
    await send_email(user.email, "Verify your email", f"Confirm your email: {url}")


async def signup(db: AsyncSession, email: str, password: str, full_name: str, ip: str) -> User:
    if await get_user_by_email(db, email):
        raise HTTPException(409, "Email already registered")
    user = User(email=email.lower(), password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    await db.flush()
    await audit(db, user.id, "auth.signup", ip)
    await send_verification(user)
    return user


async def verify_email(db: AsyncSession, token: str) -> None:
    try:
        uid = decode_purpose_token(token, "verify_email")
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid or expired token") from None
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(400, "Invalid or expired token")
    user.email_verified = True
    await audit(db, user.id, "auth.email_verified")


def _check_totp(user: User, code: str) -> bool:
    if not user.totp_secret_enc:
        return False
    return bool(pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(code.strip(), valid_window=1))


async def password_login(db: AsyncSession, email: str, password: str, ip: str) -> User:
    user = await get_user_by_email(db, email)
    if (
        user is None
        or not user.password_hash
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        await audit(db, user.id if user else None, "auth.login_failed", ip)
        await db.commit()
        raise HTTPException(401, "Invalid email or password")
    return user


def mfa_token_for(user: User) -> str:
    return create_purpose_token(user.id, "mfa", 5)


async def complete_2fa(db: AsyncSession, mfa_token: str, code: str) -> User:
    try:
        uid = decode_purpose_token(mfa_token, "mfa")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired MFA token") from None
    user = await db.get(User, uid)
    if user is None or not _check_totp(user, code):
        raise HTTPException(401, "Invalid verification code")
    return user


async def rotate_refresh(
    db: AsyncSession, refresh_token: str, user_agent: str, ip: str
) -> TokenPair:
    h = hash_token(refresh_token)
    sess = (
        await db.execute(
            select(AuthSession).where(
                (AuthSession.refresh_hash == h) | (AuthSession.prev_refresh_hash == h)
            )
        )
    ).scalar_one_or_none()
    if sess is None or sess.revoked or _aware(sess.expires_at) < datetime.now(UTC):
        raise HTTPException(401, "Invalid refresh token")
    if sess.prev_refresh_hash == h and sess.refresh_hash != h:
        # Reuse of an already-rotated token => assume theft, kill the session.
        sess.revoked = True
        await audit(db, sess.user_id, "auth.refresh_reuse_detected", ip)
        await db.commit()
        raise HTTPException(401, "Refresh token reuse detected")
    new = new_refresh_token()
    sess.prev_refresh_hash, sess.refresh_hash = sess.refresh_hash, hash_token(new)
    sess.last_used_at = datetime.now(UTC)
    sess.ip, sess.user_agent = ip, user_agent[:300] or sess.user_agent
    return TokenPair(access_token=create_access_token(sess.user_id, sess.id), refresh_token=new)


async def request_password_reset(db: AsyncSession, email: str) -> None:
    user = await get_user_by_email(db, email)
    if user is None:
        return  # do not reveal whether the email exists
    token = create_purpose_token(user.id, "reset_password", 30)
    url = f"{get_settings().web_base_url}/reset-password?token={token}"
    await send_email(user.email, "Reset your password", f"Reset your password: {url}")
    await audit(db, user.id, "auth.password_reset_requested")


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    try:
        uid = decode_purpose_token(token, "reset_password")
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid or expired token") from None
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(400, "Invalid or expired token")
    user.password_hash = hash_password(new_password)
    await revoke_all_sessions(db, user.id)
    await audit(db, user.id, "auth.password_reset")


async def revoke_all_sessions(
    db: AsyncSession, user_id: uuid.UUID, except_id: uuid.UUID | None = None
) -> None:
    rows = (await db.execute(select(AuthSession).where(AuthSession.user_id == user_id))).scalars()
    for s in rows:
        if s.id != except_id:
            s.revoked = True


def totp_setup(user: User) -> tuple[str, str]:
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt(secret)
    user.totp_enabled = False
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Freelance Manager")
    return secret, uri


def totp_enable(user: User, code: str) -> None:
    if not _check_totp(user, code):
        raise HTTPException(400, "Invalid verification code")
    user.totp_enabled = True


def totp_check(user: User, code: str) -> bool:
    return _check_totp(user, code)


async def google_login(db: AsyncSession, id_token: str, ip: str) -> User:
    """Verify a Google ID token via Google's tokeninfo endpoint and sign the user in/up."""
    import httpx

    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(501, "Google login is not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}
        )
    if r.status_code != 200:
        raise HTTPException(401, "Invalid Google token")
    info = r.json()
    if info.get("aud") != s.google_client_id or info.get("email_verified") not in ("true", True):
        raise HTTPException(401, "Invalid Google token")
    user = await get_user_by_email(db, info["email"])
    if user is None:
        user = User(
            email=info["email"].lower(),
            full_name=info.get("name", ""),
            google_sub=info["sub"],
            email_verified=True,
        )
        db.add(user)
        await db.flush()
        await audit(db, user.id, "auth.signup_google", ip)
    elif not user.google_sub:
        user.google_sub = info["sub"]
    return user
