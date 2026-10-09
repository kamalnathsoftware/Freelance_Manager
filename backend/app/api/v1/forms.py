import csv
import io
import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, client_ip
from app.core.config import get_settings
from app.models import Form, FormField, FormSubmission, UploadedFile
from app.schemas import ORM, Message
from app.services import forms as svc
from app.services import storage
from app.services.common import get_owned

router = APIRouter(tags=["forms"])

MAX_FIELDS = 60


class FieldIn(BaseModel):
    key: str = Field(max_length=60)
    type: str
    label: str = Field(min_length=1, max_length=300)
    help_text: str = Field(default="", max_length=500)
    required: bool = False
    options: list[str] = []
    show_if: dict[str, Any] | None = None


class FormIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    kind: str = Field(
        default="custom",
        pattern="^(brief|feedback|testimonial|nda|onboarding|review|revision|custom)$",
    )
    settings: dict[str, Any] = {}
    fields: list[FieldIn] = Field(default=[], max_length=MAX_FIELDS)


class FormOut(ORM):
    id: uuid.UUID
    public_key: str
    title: str
    description: str
    kind: str
    published: bool
    settings: dict[str, Any]
    version: int
    created_at: datetime
    fields: list[FieldIn] = []
    public_url: str = ""
    embed_snippet: str = ""
    submission_count: int = 0


class SubmissionOut(ORM):
    id: uuid.UUID
    form_id: uuid.UUID
    client_id: uuid.UUID | None
    submitter_name: str
    submitter_email: str
    answers: dict[str, Any]
    signature: dict[str, Any] | None
    result: dict[str, Any]
    created_at: datetime


async def _fields(db: DB, form_id: uuid.UUID) -> list[FormField]:
    return list(
        (
            await db.execute(
                select(FormField).where(FormField.form_id == form_id).order_by(FormField.position)
            )
        ).scalars()
    )


async def _out(db: DB, f: Form) -> FormOut:
    s = get_settings()
    o = FormOut.model_validate(f)
    o.fields = [
        FieldIn(
            key=x.key,
            type=x.type,
            label=x.label,
            help_text=x.help_text,
            required=x.required,
            options=x.options,
            show_if=x.show_if,
        )
        for x in await _fields(db, f.id)
    ]
    o.public_url = f"{s.web_base_url}/f/{f.public_key}"
    o.embed_snippet = f'<iframe src="{o.public_url}?embed=1" width="100%" height="640" style="border:0" title="{f.title}"></iframe>'
    o.submission_count = len(
        (await db.execute(select(FormSubmission.id).where(FormSubmission.form_id == f.id))).all()
    )
    return o


async def _replace_fields(db: DB, form: Form, fields: list[FieldIn]) -> None:
    raw = [x.model_dump() for x in fields]
    try:
        svc.validate_schema(raw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if form.kind == "nda" or (form.settings or {}).get("require_signature"):
        if not (form.settings or {}).get("agreement_text", "").strip():
            raise HTTPException(422, "Signature forms need settings.agreement_text")
    for old in await _fields(db, form.id):
        await db.delete(old)
    await db.flush()
    for i, x in enumerate(raw):
        db.add(FormField(form_id=form.id, position=i, **x))


# ---------- owner ----------
@router.get("/forms/templates")
async def templates(_: CurrentUser) -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "title": v["title"],
            "kind": v["kind"],
            "description": v["description"],
            "field_count": len(v["fields"]),
        }
        for k, v in svc.TEMPLATES.items()
    ]


@router.post("/forms/from-template/{key}", response_model=FormOut, status_code=201)
async def from_template(key: str, user: CurrentUser, db: DB) -> FormOut:
    t = svc.TEMPLATES.get(key)
    if t is None:
        raise HTTPException(404, "Unknown template")
    form = Form(
        user_id=user.id,
        public_key="f_" + secrets.token_urlsafe(12),
        title=t["title"],
        description=t["description"],
        kind=t["kind"],
        settings=dict(t["settings"]),
    )
    db.add(form)
    await db.flush()
    await _replace_fields(db, form, [FieldIn(**f) for f in t["fields"]])
    await db.commit()
    return await _out(db, form)


@router.get("/forms", response_model=list[FormOut])
async def list_forms(user: CurrentUser, db: DB) -> list[FormOut]:
    return [
        await _out(db, f)
        for f in (
            await db.execute(
                select(Form).where(Form.user_id == user.id).order_by(Form.created_at.desc())
            )
        ).scalars()
    ]


@router.post("/forms", response_model=FormOut, status_code=201)
async def create_form(body: FormIn, user: CurrentUser, db: DB) -> FormOut:
    form = Form(
        user_id=user.id,
        public_key="f_" + secrets.token_urlsafe(12),
        **body.model_dump(exclude={"fields"}),
    )
    db.add(form)
    await db.flush()
    await _replace_fields(db, form, body.fields)
    await db.commit()
    return await _out(db, form)


@router.get("/forms/submissions", response_model=list[SubmissionOut])
async def all_submissions(user: CurrentUser, db: DB, limit: int = 100) -> list[FormSubmission]:
    return list(
        (
            await db.execute(
                select(FormSubmission)
                .where(FormSubmission.user_id == user.id)
                .order_by(FormSubmission.created_at.desc())
                .limit(min(limit, 500))
            )
        ).scalars()
    )


@router.get("/forms/{fid}", response_model=FormOut)
async def get_form(fid: uuid.UUID, user: CurrentUser, db: DB) -> FormOut:
    return await _out(db, await get_owned(db, Form, fid, user.id))


@router.put("/forms/{fid}", response_model=FormOut)
async def update_form(fid: uuid.UUID, body: FormIn, user: CurrentUser, db: DB) -> FormOut:
    """The builder saves the whole schema. Editing a published form bumps its version (signed copies keep theirs)."""
    form = await get_owned(db, Form, fid, user.id)
    changed = form.settings != body.settings or [x.model_dump() for x in body.fields] != [
        x.model_dump() for x in (await _out(db, form)).fields
    ]
    for k, v in body.model_dump(exclude={"fields"}).items():
        setattr(form, k, v)
    await _replace_fields(db, form, body.fields)
    if changed:
        form.version += 1
    await db.commit()
    return await _out(db, form)


@router.post("/forms/{fid}/publish", response_model=FormOut)
async def publish(fid: uuid.UUID, user: CurrentUser, db: DB, published: bool = True) -> FormOut:
    form = await get_owned(db, Form, fid, user.id)
    if published and not await _fields(db, form.id):
        raise HTTPException(409, "Add at least one field before publishing")
    form.published = published
    await db.commit()
    return await _out(db, form)


@router.delete("/forms/{fid}", response_model=Message)
async def delete_form(fid: uuid.UUID, user: CurrentUser, db: DB) -> Message:
    await db.delete(await get_owned(db, Form, fid, user.id))
    await db.commit()
    return Message(detail="Deleted")


@router.get("/forms/{fid}/submissions", response_model=list[SubmissionOut])
async def submissions(fid: uuid.UUID, user: CurrentUser, db: DB) -> list[FormSubmission]:
    await get_owned(db, Form, fid, user.id)
    return list(
        (
            await db.execute(
                select(FormSubmission)
                .where(FormSubmission.form_id == fid)
                .order_by(FormSubmission.created_at.desc())
            )
        ).scalars()
    )


@router.get("/forms/{fid}/submissions.csv")
async def submissions_csv(fid: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    form = await get_owned(db, Form, fid, user.id)
    fields = await _fields(db, form.id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["submitted_at", "name", "email", *[f.label for f in fields]])
    for s in reversed(
        list(
            (
                await db.execute(
                    select(FormSubmission)
                    .where(FormSubmission.form_id == fid)
                    .order_by(FormSubmission.created_at.desc())
                )
            ).scalars()
        )
    ):
        # neutralise spreadsheet formula injection from untrusted respondents
        cells = [str(s.answers.get(f.key, "")) for f in fields]
        w.writerow(
            [
                s.created_at.isoformat(),
                s.submitter_name,
                s.submitter_email,
                *[("'" + c if c[:1] in "=+-@" else c) for c in cells],
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="submissions.csv"'},
    )


@router.get("/forms/submissions/{sid}/certificate.pdf")
async def certificate(sid: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    sub = await get_owned(db, FormSubmission, sid, user.id)
    if not sub.signature:
        raise HTTPException(404, "This submission has no signature")
    form = await db.get(Form, sub.form_id)
    assert form is not None
    return Response(
        svc.signature_certificate(form, sub),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="signature-{sub.id}.pdf"'},
    )


# ---------- files (owner) ----------
@router.post("/files", status_code=201)
async def upload_file(file: UploadFile, user: CurrentUser, db: DB) -> dict[str, Any]:
    path, size, ctype = await storage.save_upload(file)
    up = UploadedFile(
        user_id=user.id,
        filename=(file.filename or "file")[:300],
        content_type=ctype,
        size=size,
        path=path,
    )
    db.add(up)
    await db.commit()
    return {
        "id": str(up.id),
        "filename": up.filename,
        "size": size,
        "url": f"/api/v1/files/{up.id}",
    }


@router.get("/files/{file_id}")
async def download_file(file_id: uuid.UUID, user: CurrentUser, db: DB) -> FileResponse:
    up = await get_owned(db, UploadedFile, file_id, user.id)
    return FileResponse(
        up.path,
        media_type=up.content_type,
        filename=up.filename,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{up.filename.replace(chr(34), "")}"',
        },
    )


# ---------- public ----------
class PublicSubmit(BaseModel):
    answers: dict[str, Any] = {}
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    signature_name: str = Field(default="", max_length=200)
    website: str = ""  # honeypot: real users never fill this in


async def _public_form(db: DB, key: str) -> Form:
    form = (
        await db.execute(select(Form).where(Form.public_key == key, Form.published.is_(True)))
    ).scalar_one_or_none()
    if form is None:
        raise HTTPException(404, "This form is not available")
    return form


@router.get("/public/forms/{key}")
async def public_form(key: str, db: DB) -> dict[str, Any]:
    form = await _public_form(db, key)
    s = form.settings or {}
    return {
        "title": form.title, "description": form.description, "kind": form.kind, "version": form.version,
        "agreement_text": s.get("agreement_text", ""), "requires_signature": bool(s.get("require_signature") or form.kind == "nda"),
        "fields": [{"key": f.key, "type": f.type, "label": f.label, "help_text": f.help_text, "required": f.required, "options": f.options, "show_if": f.show_if} for f in await _fields(db, form.id)],
    }  # fmt: skip


@router.post("/public/forms/{key}/upload", status_code=201)
async def public_upload(key: str, file: UploadFile, db: DB) -> dict[str, str]:
    form = await _public_form(db, key)
    path, size, ctype = await storage.save_upload(file)
    up = UploadedFile(
        user_id=form.user_id,
        form_id=form.id,
        filename=(file.filename or "file")[:300],
        content_type=ctype,
        size=size,
        path=path,
    )
    db.add(up)
    await db.commit()
    return {"file_id": str(up.id)}


@router.post("/public/forms/{key}/submit", status_code=201)
async def public_submit(
    key: str, body: PublicSubmit, request: Request, db: DB, user_agent: str = Header(default="")
) -> dict[str, Any]:
    form = await _public_form(db, key)
    if body.website:  # bot: pretend success, store nothing
        return {"ok": True, "message": (form.settings or {}).get("success_message", "Thanks!")}
    fields = await _fields(db, form.id)
    clean, errors = await svc.validate(db, form, fields, body.answers)
    s = form.settings or {}
    sig = None
    if s.get("require_signature") or form.kind == "nda":
        if not body.signature_name.strip():
            errors["_signature"] = "Type your full name to sign"
        else:
            sig = {
                "typed_name": body.signature_name.strip(),
                "signed_at": svc.now_iso(),
                "document_hash": svc.agreement_hash(form),
                "user_agent": user_agent[:200],
            }
    email = body.email.strip() or str(clean.get("email", ""))
    if email and not svc.EMAIL_RE.match(email):
        errors["_email"] = "Enter a valid email"
    if errors:
        raise HTTPException(422, {"errors": errors})  # type: ignore[arg-type]
    name = body.name.strip() or str(clean.get("name", "")) or (sig or {}).get("typed_name", "")
    sub = FormSubmission(
        form_id=form.id,
        user_id=form.user_id,
        submitter_name=name[:200],
        submitter_email=email[:320],
        answers=clean,
        signature=sig,
        form_version=form.version,
        ip=client_ip(request),
    )
    db.add(sub)
    await db.flush()
    await svc.process_submission(db, form, fields, sub)
    await db.commit()
    return {"ok": True, "message": s.get("success_message", "Thanks!"), "signed": bool(sig)}


def new_key() -> str:
    return "f_" + secrets.token_urlsafe(12)
