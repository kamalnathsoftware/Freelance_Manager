"""Outreach templates: {{placeholder}} rendering, starter set, and the optional LLM-personalised draft.

Nothing here sends anything. A draft is text for the user to review, edit and send by hand."""

import re
from typing import Any

from app.models import PFLead, PFSettings
from app.services import ai

KINDS = ("cold_email", "linkedin_dm", "proposal")
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
VARIABLES = {
    "company": "Lead's business name",
    "contact": "Lead's contact name",
    "first_name": "First word of the contact name",
    "problem": "The problem you noticed",
    "website": "Lead's website",
    "country": "Lead's country",
    "my_name": "Your name (Project Finder settings)",
}

STARTERS: list[dict[str, str]] = [
    {
        "name": "Cold email - problem spotted",
        "kind": "cold_email",
        "subject": "Quick note about {{company}}'s website",
        "body": (
            "Hi {{first_name}},\n\n"
            "I was looking at {{company}} and noticed something: {{problem}}\n\n"
            "I'm a developer and QA automation engineer (Python/FastAPI, React/Next.js, Playwright). "
            "I can fix this and add automated tests so it doesn't come back. "
            "Happy to send a short written outline of what I'd do - no obligation.\n\n"
            "Would that be useful?\n\n"
            "Best,\n{{my_name}}"
        ),
    },
    {
        "name": "LinkedIn DM - short intro",
        "kind": "linkedin_dm",
        "subject": "",
        "body": (
            "Hi {{first_name}} - I came across {{company}} and noticed {{problem}} "
            "I help teams with test automation and backend/frontend fixes. "
            "Open to a quick chat about it? - {{my_name}}"
        ),
    },
    {
        "name": "Proposal - fix and test",
        "kind": "proposal",
        "subject": "Proposal for {{company}}",
        "body": (
            "Hi {{first_name}},\n\nThanks for taking the time to talk.\n\n"
            "What I understood: {{problem}}\n\n"
            "Proposed approach:\n1. Reproduce and diagnose the issue\n2. Implement the fix\n"
            "3. Add automated tests (Playwright/Cypress) to prevent regressions\n"
            "4. Hand over with a short written summary\n\n"
            "Timeline and price: [fill in]\n\nBest,\n{{my_name}}"
        ),
    },
]


def build_vars(lead: PFLead | None, cfg: PFSettings) -> dict[str, str]:
    contact = (lead.contact_name if lead else "").strip()
    v = {
        "company": lead.business_name if lead else "",
        "contact": contact,
        "first_name": contact.split()[0] if contact else "",
        "problem": lead.problem.strip() if lead else "",
        "website": lead.website if lead else "",
        "country": lead.country if lead else "",
        "my_name": cfg.my_name,
    }
    return {k: x.strip() for k, x in v.items()}


def render(text: str, values: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """Single-pass substitution (so a value containing "{{x}}" is never expanded again).
    Returns (text, missing, unknown). Missing/unknown placeholders are left visible in the text so the
    user notices them before sending."""
    missing: list[str] = []
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in VARIABLES:
            if name not in unknown:
                unknown.append(name)
            return m.group(0)
        if not values.get(name):
            if name not in missing:
                missing.append(name)
            return m.group(0)
        return values[name]

    return PLACEHOLDER.sub(sub, text), missing, unknown


SYSTEM = (
    "You write short, honest, personalised outreach messages for an independent freelance developer "
    "and QA automation engineer. Use ONLY the facts provided; never invent clients, results, numbers, "
    "credentials or flattery. No hype, no emojis, no placeholders left unfilled. "
    "Return only the message text."
)


def build_prompt(
    kind: str, template_body: str, lead: PFLead, cfg: PFSettings, instructions: str
) -> str:
    facts: dict[str, Any] = {
        "business": lead.business_name,
        "contact": lead.contact_name,
        "website": lead.website,
        "country": lead.country,
        "problem_noticed": lead.problem,
        "notes": lead.notes,
        "my_name": cfg.my_name,
        "my_skills": ", ".join(cfg.skills[:12]),
    }
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v)
    extra = f"\nExtra instructions from the user: {instructions}\n" if instructions else ""
    shape = {
        "cold_email": "a cold email, under 120 words. First line must be 'Subject: <subject>'.",
        "linkedin_dm": "a LinkedIn direct message, under 70 words.",
        "proposal": "a concise project proposal, under 250 words.",
    }[kind]
    return (
        f"Write {shape}\nPersonalise the template below using the facts. Keep its structure and "
        f"tone, drop anything the facts don't support.{extra}\n"
        f"FACTS:\n{lines}\n\nTEMPLATE:\n{template_body}"
    )


def split_subject(kind: str, text: str) -> tuple[str, str]:
    if kind == "cold_email":
        first, _, rest = text.partition("\n")
        if first.lower().startswith("subject:"):
            return first.split(":", 1)[1].strip(), rest.strip()
    return "", text.strip()


async def generate(
    kind: str, template_body: str, lead: PFLead, cfg: PFSettings, instructions: str
) -> tuple[str, str]:
    text = await ai.complete(
        SYSTEM, build_prompt(kind, template_body, lead, cfg, instructions), 700
    )
    return split_subject(kind, text)
