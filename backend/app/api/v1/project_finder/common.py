"""Shared request validation for Project Finder schemas."""

from typing import Annotated
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, StringConstraints

from app.services.project_finder import valid_tz


def _http_url(v: str) -> str:
    """Empty is allowed; otherwise http(s) only (these are rendered as links, so no javascript: etc.)."""
    v = v.strip()
    if not v:
        return v
    if (
        ":" not in v
    ):  # "acme.com" -> https://acme.com (anything with an explicit scheme is checked as-is)
        v = f"https://{v}"
    p = urlparse(v)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("must be an http(s) URL")
    return v


def _email(v: str) -> str:
    v = v.strip()
    if not v:
        return v
    try:
        return validate_email(v, check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise ValueError(str(e)) from None


def _tz(v: str) -> str:
    v = v.strip()
    if v and not valid_tz(v):
        raise ValueError("unknown time zone (use an IANA name such as America/New_York)")
    return v


def _currency(v: str) -> str:
    v = v.strip().upper()
    if v and not (len(v) == 3 and v.isalpha()):
        raise ValueError("must be a 3-letter currency code")
    return v


HttpUrlStr = Annotated[str, StringConstraints(max_length=1000), AfterValidator(_http_url)]
EmailOrBlank = Annotated[str, StringConstraints(max_length=320), AfterValidator(_email)]
TzStr = Annotated[str, StringConstraints(max_length=64), AfterValidator(_tz)]
CurrencyStr = Annotated[str, StringConstraints(max_length=3), AfterValidator(_currency)]


def clean_list(items: list[str], limit: int = 50) -> list[str]:
    """Trim, drop blanks, case-insensitive de-dupe (keeps first spelling), cap the length."""
    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        t = i.strip()[:60]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]
