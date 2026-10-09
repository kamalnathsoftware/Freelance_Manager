"""Parse platform notification emails into structured events.

Compliance: this reads only emails the user has chosen to forward/connect. Nothing is fetched from the
platforms themselves. Patterns are intentionally conservative; unknown mails are ignored.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

DOMAINS = {
    "fiverr.com": "fiverr",
    "upwork.com": "upwork",
    "freelancer.com": "freelancer",
    "peopleperhour.com": "peopleperhour",
    "toptal.com": "toptal",
    "guru.com": "guru",
    "linkedin.com": "linkedin",
    "contra.com": "contra",
}

# order matters: first match wins
KIND_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "payment",
        re.compile(
            r"(payment (received|released)|you('ve| have) been paid|funds? (released|available))",
            re.I,
        ),
    ),
    ("review", re.compile(r"(left you a (\d-star )?review|new review|rated you|feedback)", re.I)),
    ("revision", re.compile(r"(revision (request|requested)|requested a revision)", re.I)),
    (
        "order_delivered",
        re.compile(
            r"(delivery (accepted|completed)|order (completed|delivered)|marked (it )?as complete)",
            re.I,
        ),
    ),
    (
        "order",
        re.compile(
            r"(new order|order (received|placed|started)|you('ve| have) (got|received) an? order|placed an order|hired you|awarded)",
            re.I,
        ),
    ),
    (
        "offer",
        re.compile(
            r"(sent you an? (custom )?offer|new offer|offer (received|accepted|declined)|contract offer)",
            re.I,
        ),
    ),
    (
        "job_invite",
        re.compile(
            r"(invited you|invitation to (apply|bid|interview)|job invitation|new job(s)? (match|for you|posted)|recommended job)",
            re.I,
        ),
    ),
    ("bid_viewed", re.compile(r"(viewed your (proposal|bid)|proposal (was )?viewed)", re.I)),
    ("bid_accepted", re.compile(r"(accepted your (proposal|bid)|proposal accepted)", re.I)),
    (
        "bid_declined",
        re.compile(
            r"(declined your (proposal|bid)|proposal (declined|not selected)|not (moving|moved) forward)",
            re.I,
        ),
    ),
    (
        "message",
        re.compile(
            r"(new message|sent you a message|you have a message|replied to|unread message|messaged you)",
            re.I,
        ),
    ),
]

URL_RE = re.compile(r"https?://[^\s<>\"')]+")


@dataclass
class ParsedEmail:
    platform: str
    kind: str
    title: str
    summary: str
    url: str = ""
    dedupe_key: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def platform_for(sender: str) -> str | None:
    m = re.search(r"@([\w.-]+)", sender)
    host = (m.group(1) if m else sender).lower()
    for dom, key in DOMAINS.items():
        if host == dom or host.endswith("." + dom):
            return key
    return None


def classify(subject: str, body: str) -> str | None:
    for kind, pat in KIND_RULES:
        if pat.search(subject):
            return kind
    head = body[:600]
    for kind, pat in KIND_RULES:
        if pat.search(head):
            return kind
    return None


def _first_platform_url(platform: str, body: str) -> str:
    dom = next(d for d, k in DOMAINS.items() if k == platform)
    for u in URL_RE.findall(body):
        if dom in u and not re.search(r"unsubscribe|preferences|settings/notifications", u, re.I):
            return u.rstrip(".,;")
    return ""


NAME = r"([A-Z][\w.'-]+(?: [A-Z][\w.'-]+)?)"
NOT_NAMES = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March", "April",
    "May", "June", "July", "August", "September", "October", "November", "December", "Fiverr", "Upwork", "Freelancer", "You", "The",
}  # fmt: skip


def counterparty(subject: str, body: str) -> str:
    """Best-effort name of the other person. Subject patterns first; body only as a labelled fallback."""
    candidates = [
        re.search(rf"\b(?:from|by)\s+{NAME}", subject),
        re.search(
            rf"^{NAME}\s+(?:sent|invited|messaged|replied|left|accepted|declined|viewed|requested)",
            subject.strip(),
        ),
        re.search(rf"\b(?:from|sender|client|buyer)\s*:\s*{NAME}", body[:400], re.I),
    ]
    for m in candidates:
        if m and m.group(1).split()[0] not in NOT_NAMES:
            return m.group(1)
    return ""


def parse_email(sender: str, subject: str, body: str, message_id: str = "") -> ParsedEmail | None:
    platform = platform_for(sender)
    if platform is None:
        return None
    kind = classify(subject, body)
    if kind is None:
        return None
    meta: dict[str, Any] = {}
    if who := counterparty(subject, body):
        meta["counterparty"] = who
    if m := re.search(r"(?:order\s*#|order id:?\s*)(\w{4,})", subject + " " + body, re.I):
        meta["order_id"] = m.group(1)
    if m := re.search(r"([$€£])\s?(\d[\d,]*(?:\.\d{1,2})?)", subject + " " + body[:800]):
        meta["amount"] = float(m.group(2).replace(",", ""))
        meta["currency"] = {"$": "USD", "€": "EUR", "£": "GBP"}[m.group(1)]
    summary = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", body)).strip()[:280]
    digest = hashlib.sha1(f"{subject}|{body[:200]}".encode()).hexdigest()[
        :16
    ]  # stable across processes
    key = message_id or f"{platform}:{kind}:{digest}"
    return ParsedEmail(
        platform,
        kind,
        subject.strip()[:300],
        summary,
        _first_platform_url(platform, body),
        key[:200],
        meta,
    )
