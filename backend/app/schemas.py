import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Login2FAIn(BaseModel):
    mfa_token: str
    code: str


class GoogleLoginIn(BaseModel):
    id_token: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginOut(BaseModel):
    mfa_required: bool = False
    mfa_token: str | None = None
    tokens: TokenPair | None = None


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(ORM):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    timezone: str
    locale: str
    email_verified: bool
    totp_enabled: bool
    settings: dict[str, Any]
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=16)
    settings: dict[str, Any] | None = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class SessionOut(ORM):
    id: uuid.UUID
    user_agent: str
    ip: str
    created_at: datetime
    last_used_at: datetime
    current: bool = False


class AuditOut(ORM):
    id: uuid.UUID
    action: str
    ip: str
    meta: dict[str, Any]
    created_at: datetime


class Message(BaseModel):
    detail: str
