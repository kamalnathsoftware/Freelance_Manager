"""Form validation (with conditional logic), built-in templates, submission side effects, signature certificate."""

import hashlib
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fpdf import FPDF
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Form,
    FormField,
    FormSubmission,
    Job,
    Project,
    Proposal,
    Stage,
    UploadedFile,
)
from app.services import automation, inbox, notifications

FIELD_TYPES = (
    "text",
    "textarea",
    "email",
    "number",
    "dropdown",
    "radio",
    "checkbox",
    "date",
    "file",
    "rating",
    "agreement",
)


class _Invalid(Exception):
    pass


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OPS = ("eq", "ne", "contains", "gt", "lt", "filled")


def _num(x: Any) -> float:
    return float(x)


def condition_met(cond: dict[str, Any] | None, answers: dict[str, Any]) -> bool:
    if not cond:
        return True
    val = answers.get(cond.get("field", ""))
    op, want = cond.get("op", "eq"), cond.get("value")
    try:
        if op == "filled":
            return val not in (None, "", [], False)
        if op == "eq":
            return str(val) == str(want) if not isinstance(val, bool) else val == bool(want)
        if op == "ne":
            return str(val) != str(want)
        if op == "contains":
            return str(want).lower() in str(val or "").lower()
        if op == "gt":
            return _num(val) > _num(want)
        if op == "lt":
            return _num(val) < _num(want)
    except (TypeError, ValueError):
        return False
    return False


def visible_fields(fields: list[FormField], answers: dict[str, Any]) -> list[FormField]:
    """Resolve show_if chains in order (a hidden field's answer never satisfies a later condition)."""
    shown: list[FormField] = []
    effective: dict[str, Any] = {}
    for f in sorted(fields, key=lambda x: x.position):
        if condition_met(f.show_if, effective):
            shown.append(f)
            if f.key in answers:
                effective[f.key] = answers[f.key]
    return shown


async def validate(
    db: AsyncSession, form: Form, fields: list[FormField], answers: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in visible_fields(fields, answers):
        raw = answers.get(f.key)
        empty = raw in (None, "", [], False)
        if empty:
            if f.required:
                errors[f.key] = "This field is required"
            continue
        v: Any
        try:
            if f.type in ("text", "textarea"):
                v = str(raw).strip()
                if len(v) > (500 if f.type == "text" else 5000):
                    raise _Invalid("Too long")
            elif f.type == "email":
                v = str(raw).strip()
                if not EMAIL_RE.match(v) or len(v) > 320:
                    raise _Invalid("Enter a valid email")
            elif f.type == "number":
                v = _num(raw)
            elif f.type in ("dropdown", "radio"):
                v = str(raw)
                if v not in [str(o) for o in f.options]:
                    raise _Invalid("Choose one of the listed options")
            elif f.type in ("checkbox", "agreement"):
                v = bool(raw)
            elif f.type == "date":
                v = date.fromisoformat(str(raw)).isoformat()
            elif f.type == "rating":
                v = int(_num(raw))
                if not 1 <= v <= 5:
                    raise _Invalid("Rating must be 1-5")
            elif f.type == "file":
                fid = uuid.UUID(str(raw))
                up = await db.get(UploadedFile, fid)
                if up is None or up.form_id != form.id:
                    raise _Invalid("Unknown file - upload it first")
                v = str(fid)
            else:
                raise _Invalid("Unsupported field type")
            clean[f.key] = v
        except _Invalid as e:
            errors[f.key] = str(e)
        except (ValueError, TypeError):
            errors[f.key] = "Invalid value"
    return clean, errors


def validate_schema(fields: list[dict[str, Any]]) -> None:
    keys: set[str] = set()
    for f in fields:
        k = f["key"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", k):
            raise ValueError(f"Field key '{k}' must be lowercase letters, digits or underscores")
        if k in keys:
            raise ValueError(f"Duplicate field key '{k}'")
        if f["type"] not in FIELD_TYPES:
            raise ValueError(f"Unknown field type '{f['type']}'")
        if f["type"] in ("dropdown", "radio") and not f.get("options"):
            raise ValueError(f"Field '{k}' needs options")
        cond = f.get("show_if")
        if cond:
            if cond.get("field") not in keys:
                raise ValueError(f"Field '{k}': show_if must reference an earlier field")
            if cond.get("op", "eq") not in OPS:
                raise ValueError(f"Field '{k}': unknown operator")
        keys.add(k)


def agreement_hash(form: Form) -> str:
    return hashlib.sha256(
        f"{form.id}:{form.version}:{(form.settings or {}).get('agreement_text', '')}".encode()
    ).hexdigest()


def summarize(form: Form, fields: list[FormField], answers: dict[str, Any]) -> str:
    lines = [
        f"{f.label}: {answers[f.key]}"
        for f in sorted(fields, key=lambda x: x.position)
        if f.key in answers and f.type != "file"
    ]
    return f"New submission for '{form.title}'\n" + "\n".join(lines)


async def process_submission(
    db: AsyncSession, form: Form, fields: list[FormField], sub: FormSubmission
) -> None:
    """Land the submission in CRM + inbox, notify, run the form's auto-actions, fire automations."""
    owner = form.user_id
    handle = sub.submitter_email or f"form:{sub.id}"
    client = await inbox.resolve_client(
        db,
        owner,
        "direct",
        handle,
        name=sub.submitter_name or sub.submitter_email or "Form respondent",
        email=sub.submitter_email,
    )
    sub.client_id = client.id
    conv, _ = await inbox.get_or_create_conversation(
        db, owner, "direct", f"form:{sub.id}", subject=f"Form: {form.title}", client=client
    )
    await inbox.add_inbound(
        db,
        conv,
        summarize(form, fields, sub.answers),
        sender=client.name,
        source="form",
        external_key=f"sub:{sub.id}",
    )
    result: dict[str, Any] = {"conversation_id": str(conv.id), "client_id": str(client.id)}
    actions = (form.settings or {}).get("auto_actions", [])
    if "create_project" in actions:
        proj = Project(
            user_id=owner,
            client_id=client.id,
            name=f"{form.title} - {client.name}",
            description=summarize(form, fields, sub.answers)[:2000],
        )
        db.add(proj)
        await db.flush()
        result["project_id"] = str(proj.id)
    if "create_proposal_draft" in actions:
        job = Job(
            user_id=owner,
            platform="direct",
            external_id=f"form:{sub.id}",
            title=f"{form.title} - {client.name}",
            description=summarize(form, fields, sub.answers)[:6000],
            source="form",
            client={"name": client.name},
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        prop = Proposal(user_id=owner, job_id=job.id, stage=Stage.shortlisted)
        db.add(prop)
        await db.flush()
        result.update(job_id=str(job.id), proposal_id=str(prop.id))
    sub.result = result
    await notifications.emit(
        db, owner, "form_submitted", f"{client.name} submitted '{form.title}'", body=sub.submitter_email, url=f"/forms?submission={sub.id}",
        dedupe_key=f"form-sub:{sub.id}", data={"form_id": str(form.id), "submission_id": str(sub.id)},
    )  # fmt: skip
    await automation.fire(
        db,
        owner,
        "form.submitted",
        {
            "form_id": str(form.id),
            "form_kind": form.kind,
            "form_title": form.title,
            "client_id": str(client.id),
            "client_name": client.name,
            "submission_id": str(sub.id),
            **{f"answer_{k}": v for k, v in sub.answers.items()},
        },
        dedupe_key=f"sub:{sub.id}",
    )


def _latin(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


def signature_certificate(form: Form, sub: FormSubmission) -> bytes:
    sig = sub.signature or {}
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Signature certificate", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for k, v in (("Document", form.title), ("Version", str(sub.form_version)), ("Signer", sig.get("typed_name", "")), ("Email", sub.submitter_email),
                 ("Signed at (UTC)", sig.get("signed_at", "")), ("IP address", sub.ip), ("Document SHA-256", sig.get("document_hash", ""))):  # fmt: skip
        pdf.multi_cell(0, 6, _latin(f"{k}: {v}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5,
        _latin("Agreement text:\n" + (form.settings or {}).get("agreement_text", "")),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    pdf.multi_cell(
        0,
        5,
        "This record shows the signer typed their name and ticked agreement. It is a simple electronic signature; whether it is legally sufficient depends on your jurisdiction.",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    return bytes(pdf.output())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------- built-in templates ---------
def _f(key: str, type_: str, label: str, required: bool = False, **kw: Any) -> dict[str, Any]:
    return {
        "key": key,
        "type": type_,
        "label": label,
        "required": required,
        "options": kw.pop("options", []),
        "help_text": kw.pop("help_text", ""),
        "show_if": kw.pop("show_if", None),
    }


TEMPLATES: dict[str, dict[str, Any]] = {
    "project_brief": {
        "title": "Project brief",
        "kind": "brief",
        "description": "Tell me about your project so I can send an accurate quote.",
        "settings": {
            "success_message": "Thanks! I'll reply within one business day.",
            "auto_actions": ["create_proposal_draft"],
        },
        "fields": [
            _f("name", "text", "Your name", True),
            _f("email", "email", "Email", True),
            _f("company", "text", "Company"),
            _f(
                "project_type",
                "dropdown",
                "What do you need?",
                True,
                options=["Website", "Mobile app", "API / backend", "Design", "Other"],
            ),
            _f(
                "other_type",
                "text",
                "Please describe",
                True,
                show_if={"field": "project_type", "op": "eq", "value": "Other"},
            ),
            _f("description", "textarea", "Describe the project", True),
            _f(
                "budget",
                "dropdown",
                "Budget",
                False,
                options=["< $500", "$500-2k", "$2k-10k", "$10k+"],
            ),
            _f("deadline", "date", "Desired delivery date"),
            _f("references", "file", "Reference files"),
        ],
    },
    "revision_request": {
        "title": "Revision request",
        "kind": "revision",
        "description": "Tell me what to adjust.",
        "settings": {"success_message": "Got it - I'll get back to you shortly."},
        "fields": [
            _f("name", "text", "Your name", True),
            _f("email", "email", "Email", True),
            _f("order_ref", "text", "Order / project reference"),
            _f("changes", "textarea", "What should change?", True),
            _f("urgent", "checkbox", "This is urgent"),
        ],
    },
    "client_onboarding": {
        "title": "Client onboarding",
        "kind": "onboarding",
        "description": "A few details to get started.",
        "settings": {"success_message": "Welcome aboard!", "auto_actions": ["create_project"]},
        "fields": [
            _f("name", "text", "Full name", True),
            _f("email", "email", "Email", True),
            _f("company", "text", "Company"),
            _f("timezone", "text", "Timezone"),
            _f(
                "contact_pref",
                "radio",
                "Preferred contact",
                True,
                options=["Email", "Chat", "Video call"],
            ),
            _f("goals", "textarea", "Goals for this project", True),
            _f("assets", "file", "Brand assets / access details"),
        ],
    },
    "review_request": {
        "title": "How did I do?",
        "kind": "review",
        "description": "Your feedback helps a lot.",
        "settings": {"success_message": "Thank you for the feedback!"},
        "fields": [
            _f("name", "text", "Your name", True),
            _f("email", "email", "Email"),
            _f("rating", "rating", "Overall rating", True),
            _f("comment", "textarea", "What went well?"),
            _f(
                "improve",
                "textarea",
                "What could be better?",
                show_if={"field": "rating", "op": "lt", "value": 4},
            ),
            _f("public_ok", "checkbox", "You may quote me as a testimonial"),
        ],
    },
    "nda": {
        "title": "Mutual NDA",
        "kind": "nda",
        "description": "Please review and sign before we share project details.",
        "settings": {
            "success_message": "Signed - thank you.",
            "require_signature": True,
            "agreement_text": "Each party agrees to keep the other's confidential information private and to use it only for the purpose of the proposed project, for two years from the date of signing. This is a template; have it reviewed before relying on it.",
        },
        "fields": [
            _f("name", "text", "Full legal name", True),
            _f("email", "email", "Email", True),
            _f("company", "text", "Company"),
            _f("agree", "agreement", "I have read and agree to the terms above", True),
        ],
    },
}
