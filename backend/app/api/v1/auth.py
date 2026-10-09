from fastapi import APIRouter, Header, Request

from app.api.deps import DB, CurrentAuth, client_ip
from app.schemas import (
    EmailIn,
    GoogleLoginIn,
    Login2FAIn,
    LoginIn,
    LoginOut,
    Message,
    RefreshIn,
    ResetPasswordIn,
    SignupIn,
    TokenIn,
    TokenPair,
)
from app.services import auth as svc
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenPair, status_code=201)
async def signup(
    body: SignupIn, db: DB, request: Request, user_agent: str = Header(default="")
) -> TokenPair:
    ip = client_ip(request)
    user = await svc.signup(db, body.email, body.password, body.full_name, ip)
    tokens = await svc.issue_tokens(db, user, user_agent, ip)
    await db.commit()
    return tokens


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn, db: DB, request: Request, user_agent: str = Header(default="")
) -> LoginOut:
    ip = client_ip(request)
    user = await svc.password_login(db, body.email, body.password, ip)
    if user.totp_enabled:
        return LoginOut(mfa_required=True, mfa_token=svc.mfa_token_for(user))
    tokens = await svc.issue_tokens(db, user, user_agent, ip)
    await audit(db, user.id, "auth.login", ip)
    await db.commit()
    return LoginOut(tokens=tokens)


@router.post("/login/2fa", response_model=TokenPair)
async def login_2fa(
    body: Login2FAIn, db: DB, request: Request, user_agent: str = Header(default="")
) -> TokenPair:
    ip = client_ip(request)
    user = await svc.complete_2fa(db, body.mfa_token, body.code)
    tokens = await svc.issue_tokens(db, user, user_agent, ip)
    await audit(db, user.id, "auth.login_2fa", ip)
    await db.commit()
    return tokens


@router.post("/google", response_model=TokenPair)
async def google(
    body: GoogleLoginIn, db: DB, request: Request, user_agent: str = Header(default="")
) -> TokenPair:
    ip = client_ip(request)
    user = await svc.google_login(db, body.id_token, ip)
    tokens = await svc.issue_tokens(db, user, user_agent, ip)
    await audit(db, user.id, "auth.login_google", ip)
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshIn, db: DB, request: Request, user_agent: str = Header(default="")
) -> TokenPair:
    tokens = await svc.rotate_refresh(db, body.refresh_token, user_agent, client_ip(request))
    await db.commit()
    return tokens


@router.post("/logout", response_model=Message)
async def logout(auth: CurrentAuth, db: DB) -> Message:
    from app.models import AuthSession

    sess = await db.get(AuthSession, auth.session_id)
    if sess:
        sess.revoked = True
    await db.commit()
    return Message(detail="Logged out")


@router.post("/verify-email", response_model=Message)
async def verify_email(body: TokenIn, db: DB) -> Message:
    await svc.verify_email(db, body.token)
    await db.commit()
    return Message(detail="Email verified")


@router.post("/resend-verification", response_model=Message)
async def resend_verification(auth: CurrentAuth) -> Message:
    if not auth.user.email_verified:
        await svc.send_verification(auth.user)
    return Message(detail="Verification email sent")


@router.post("/forgot-password", response_model=Message)
async def forgot_password(body: EmailIn, db: DB) -> Message:
    await svc.request_password_reset(db, body.email)
    await db.commit()
    return Message(detail="If the account exists, a reset email has been sent")


@router.post("/reset-password", response_model=Message)
async def reset_password(body: ResetPasswordIn, db: DB) -> Message:
    await svc.reset_password(db, body.token, body.new_password)
    await db.commit()
    return Message(detail="Password updated")
