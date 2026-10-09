import uuid
from datetime import UTC, datetime, timedelta

import pytest

P = "/api/v1"


# ---------------- forms ----------------
def field(key, type_, label=None, **kw):
    return {"key": key, "type": type_, "label": label or key.title(), **kw}


FORM = {
    "title": "Brief",
    "kind": "brief",
    "settings": {
        "success_message": "Thanks!",
        "auto_actions": ["create_project", "create_proposal_draft"],
    },
    "fields": [
        field("name", "text", required=True),
        field("email", "email", required=True),
        field("kind", "dropdown", options=["Web", "Other"], required=True),
        field(
            "other", "text", required=True, show_if={"field": "kind", "op": "eq", "value": "Other"}
        ),
        field("budget", "number"),
        field("when", "date"),
        field("stars", "rating"),
        field("ok", "checkbox"),
    ],
}


async def published(c, body=None):
    f = (await c.post(f"{P}/forms", json=body or FORM)).json()
    assert (await c.post(f"{P}/forms/{f['id']}/publish")).status_code == 200
    return f


async def submit(c, key, answers=None, **kw):
    return await c.post(f"{P}/public/forms/{key}/submit", json={"answers": answers or {}, **kw})


async def test_schema_validation_rules(auth_client):
    bad = lambda fields: auth_client.post(f"{P}/forms", json={"title": "x", "fields": fields})  # noqa: E731
    assert (await bad([field("Bad Key", "text")])).status_code == 422
    assert (await bad([field("a", "text"), field("a", "text")])).status_code == 422
    assert (await bad([field("a", "hologram")])).status_code == 422
    assert (await bad([field("a", "dropdown")])).status_code == 422  # needs options
    assert (
        await bad(
            [
                field("a", "text", show_if={"field": "later", "op": "eq", "value": 1}),
                field("later", "text"),
            ]
        )
    ).status_code == 422
    assert (
        await bad([field("a", "text"), field("b", "text", show_if={"field": "a", "op": "regex"})])
    ).status_code == 422
    nda = await auth_client.post(
        f"{P}/forms", json={"title": "NDA", "kind": "nda", "fields": [field("a", "text")]}
    )
    assert nda.status_code == 422 and "agreement_text" in nda.text


async def test_publish_requires_fields_and_unpublished_is_hidden(auth_client, client):
    empty = (await auth_client.post(f"{P}/forms", json={"title": "Empty"})).json()
    assert (await auth_client.post(f"{P}/forms/{empty['id']}/publish")).status_code == 409
    f = (await auth_client.post(f"{P}/forms", json=FORM)).json()
    auth = client.headers.pop("Authorization")
    assert (await client.get(f"{P}/public/forms/{f['public_key']}")).status_code == 404  # draft
    client.headers["Authorization"] = auth
    await auth_client.post(f"{P}/forms/{f['id']}/publish")
    client.headers.pop("Authorization")
    pub = (await client.get(f"{P}/public/forms/{f['public_key']}")).json()
    assert pub["title"] == "Brief" and len(pub["fields"]) == 8 and "settings" not in pub
    client.headers["Authorization"] = auth


async def test_public_submission_validation_and_conditional_logic(auth_client, client):
    f = await published(auth_client)
    key = f["public_key"]
    auth = client.headers.pop("Authorization")

    r = await submit(client, key, {})
    assert r.status_code == 422
    errs = r.json()["error"]["details"]["errors"]
    assert set(errs) == {"name", "email", "kind"}  # 'other' is hidden => not required

    r = await submit(client, key, {"name": "Pat", "email": "bad", "kind": "Other"})
    assert r.json()["error"]["details"]["errors"]["email"] == "Enter a valid email"
    assert "other" in r.json()["error"]["details"]["errors"]  # now visible + required

    r = await submit(client, key, {"name": "Pat", "email": "p@x.com", "kind": "Mars"})
    assert r.json()["error"]["details"]["errors"]["kind"].startswith("Choose")
    bad = await submit(
        client,
        key,
        {
            "name": "Pat",
            "email": "p@x.com",
            "kind": "Web",
            "budget": "lots",
            "when": "tomorrow",
            "stars": 9,
        },
    )
    e = bad.json()["error"]["details"]["errors"]
    assert set(e) == {"budget", "when", "stars"}

    ok = await submit(
        client,
        key,
        {
            "name": "Pat",
            "email": "p@x.com",
            "kind": "Web",
            "other": "ignored",
            "budget": "1500",
            "stars": 5,
            "ok": True,
        },
    )
    assert ok.status_code == 201 and ok.json()["message"] == "Thanks!"
    client.headers["Authorization"] = auth

    sub = (await auth_client.get(f"{P}/forms/{f['id']}/submissions")).json()[0]
    assert (
        "other" not in sub["answers"]
        and sub["answers"]["budget"] == 1500
        and sub["answers"]["stars"] == 5
    )  # hidden answer dropped
    assert {"project_id", "proposal_id", "job_id", "conversation_id", "client_id"} <= set(
        sub["result"]
    )  # auto-actions ran
    assert (await auth_client.get(f"{P}/clients", params={"q": "Pat"})).json()[0][
        "email"
    ] == "p@x.com"
    convs = (await auth_client.get(f"{P}/conversations")).json()
    assert any("Form: Brief" in c["subject"] for c in convs)
    types = [n["type"] for n in (await auth_client.get(f"{P}/notifications")).json()["items"]]
    assert "form_submitted" in types
    assert (await auth_client.get(f"{P}/forms/{f['id']}")).json()["submission_count"] == 1
    assert len((await auth_client.get(f"{P}/forms/submissions")).json()) == 1
    assert (await auth_client.get(f"{P}/projects")).json()[0]["name"].startswith("Brief")


async def test_honeypot_and_unknown_form(auth_client, client):
    f = await published(auth_client)
    client.headers.pop("Authorization")
    r = await submit(client, f["public_key"], {"name": "x"}, website="http://spam")
    assert r.status_code == 201  # silently accepted...
    assert (await submit(client, "nope", {})).status_code == 404


async def test_csv_export_neutralises_formula_injection(auth_client, client):
    f = await published(
        auth_client,
        {"title": "T", "fields": [field("name", "text", required=True), field("note", "textarea")]},
    )
    auth = client.headers.pop("Authorization")
    await submit(client, f["public_key"], {"name": "Eve", "note": '=HYPERLINK("http://evil")'})
    client.headers["Authorization"] = auth
    csv = (await auth_client.get(f"{P}/forms/{f['id']}/submissions.csv")).text
    assert "'=HYPERLINK" in csv and ",=HYPERLINK" not in csv
    await auth_client.get(
        f"{P}/forms/{f['id']}/submissions"
    )  # also: no honeypot submissions stored
    assert len((await auth_client.get(f"{P}/forms/{f['id']}/submissions")).json()) == 1


async def test_templates_and_edit_versioning(auth_client):
    tpls = (await auth_client.get(f"{P}/forms/templates")).json()
    assert {t["key"] for t in tpls} == {
        "project_brief",
        "revision_request",
        "client_onboarding",
        "review_request",
        "nda",
    }
    f = (await auth_client.post(f"{P}/forms/from-template/project_brief")).json()
    assert f["kind"] == "brief" and len(f["fields"]) == 9 and f["version"] == 1
    assert (await auth_client.post(f"{P}/forms/from-template/zzz")).status_code == 404
    body = {
        "title": f["title"],
        "description": f["description"],
        "kind": f["kind"],
        "settings": f["settings"],
        "fields": f["fields"],
    }
    assert (await auth_client.put(f"{P}/forms/{f['id']}", json=body)).json()[
        "version"
    ] == 1  # unchanged => same version
    body["fields"] = body["fields"][:-1]
    v2 = (await auth_client.put(f"{P}/forms/{f['id']}", json=body)).json()
    assert v2["version"] == 2 and len(v2["fields"]) == 8
    assert "iframe" in v2["embed_snippet"] and v2["public_url"].endswith(f["public_key"])
    assert (await auth_client.delete(f"{P}/forms/{f['id']}")).status_code == 200


async def test_review_template_conditional_and_rating(auth_client, client):
    f = (await auth_client.post(f"{P}/forms/from-template/review_request")).json()
    await auth_client.post(f"{P}/forms/{f['id']}/publish")
    auth = client.headers.pop("Authorization")
    r = await submit(
        client, f["public_key"], {"name": "Kim", "rating": 2, "improve": "faster replies"}
    )
    assert r.status_code == 201
    r = await submit(
        client, f["public_key"], {"name": "Kim", "rating": 5, "improve": "should be dropped"}
    )
    client.headers["Authorization"] = auth
    answers = [
        s["answers"] for s in (await auth_client.get(f"{P}/forms/{f['id']}/submissions")).json()
    ]
    assert any(a.get("improve") == "faster replies" for a in answers) and any(
        "improve" not in a and a["rating"] == 5 for a in answers
    )


async def test_nda_signature_flow_and_certificate(auth_client, client):
    f = (await auth_client.post(f"{P}/forms/from-template/nda")).json()
    await auth_client.post(f"{P}/forms/{f['id']}/publish")
    key = f["public_key"]
    auth = client.headers.pop("Authorization")
    pub = (await client.get(f"{P}/public/forms/{key}")).json()
    assert pub["requires_signature"] and "confidential" in pub["agreement_text"]
    r = await submit(client, key, {"name": "Lee", "email": "l@x.com", "agree": True})
    assert (
        r.status_code == 422 and "_signature" in r.json()["error"]["details"]["errors"]
    )  # must type name to sign
    r = await submit(client, key, {"name": "Lee", "email": "l@x.com"}, signature_name="Lee Roy")
    assert (
        r.status_code == 422 and "agree" in r.json()["error"]["details"]["errors"]
    )  # must tick agreement
    r = await submit(
        client, key, {"name": "Lee", "email": "l@x.com", "agree": True}, signature_name="Lee Roy"
    )
    assert r.status_code == 201 and r.json()["signed"] is True
    client.headers["Authorization"] = auth
    sub = (await auth_client.get(f"{P}/forms/{f['id']}/submissions")).json()[0]
    assert (
        sub["signature"]["typed_name"] == "Lee Roy" and len(sub["signature"]["document_hash"]) == 64
    )
    pdf = await auth_client.get(f"{P}/forms/submissions/{sub['id']}/certificate.pdf")
    assert pdf.content.startswith(b"%PDF")
    # unsigned submissions have no certificate
    plain = await published(auth_client, {"title": "P", "fields": [field("name", "text")]})
    client.headers.pop("Authorization")
    await submit(client, plain["public_key"], {"name": "A"})
    client.headers["Authorization"] = auth
    psub = (await auth_client.get(f"{P}/forms/{plain['id']}/submissions")).json()[0]
    assert (
        await auth_client.get(f"{P}/forms/submissions/{psub['id']}/certificate.pdf")
    ).status_code == 404


async def test_file_upload_limits_and_ownership(auth_client, client, monkeypatch):
    f = await published(
        auth_client,
        {"title": "Files", "fields": [field("name", "text", required=True), field("doc", "file")]},
    )
    key = f["public_key"]
    auth = client.headers.pop("Authorization")
    r = await client.post(
        f"{P}/public/forms/{key}/upload",
        files={"file": ("brief.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )
    assert r.status_code == 201
    fid = r.json()["file_id"]
    assert (
        await client.post(
            f"{P}/public/forms/{key}/upload",
            files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
        )
    ).status_code == 415
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    assert (
        await client.post(
            f"{P}/public/forms/{key}/upload",
            files={"file": ("big.pdf", b"x" * 10, "application/pdf")},
        )
    ).status_code == 413
    monkeypatch.setattr(get_settings(), "max_upload_mb", 5)
    bad = await submit(client, key, {"name": "A", "doc": str(uuid.uuid4())})
    assert bad.json()["error"]["details"]["errors"]["doc"].startswith("Unknown file")
    assert (await submit(client, key, {"name": "A", "doc": fid})).status_code == 201
    client.headers["Authorization"] = auth
    got = await auth_client.get(f"{P}/files/{fid}")
    assert (
        got.status_code == 200
        and got.content.startswith(b"%PDF")
        and got.headers["x-content-type-options"] == "nosniff"
    )
    # another user cannot read it
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "o@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.get(f"{P}/files/{fid}")).status_code == 404
    # authenticated upload
    up = await client.post(f"{P}/files", files={"file": ("a.png", b"\x89PNG", "image/png")})
    assert up.status_code == 201 and up.json()["size"] == 4


# ---------------- automations ----------------
async def rule(c, **kw):
    body = {
        "name": "r",
        "trigger": "job.created",
        "conditions": [],
        "actions": [{"type": "notify", "params": {"title": "Hi {title}"}}],
        **kw,
    }
    r = await c.post(f"{P}/automations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_rule_validation_and_meta(auth_client):
    meta = (await auth_client.get(f"{P}/automations/meta")).json()
    assert "job.created" in [t["key"] for t in meta["triggers"]] and len(meta["presets"]) == 4
    for kw in (
        {"trigger": "bogus"},
        {"actions": []},
        {"actions": [{"type": "rm_rf"}]},
        {"conditions": [{"field": "x", "op": "regex", "value": "."}]},
        {"actions": [{"type": "notify"}] * 9},
    ):
        r = await auth_client.post(
            f"{P}/automations",
            json={"name": "r", "trigger": "job.created", "actions": [{"type": "notify"}], **kw},
        )
        assert r.status_code == 422, kw
    for p in meta["presets"]:  # every shipped preset must itself be valid
        assert (
            await auth_client.post(
                f"{P}/automations",
                json={k: p[k] for k in ("name", "trigger", "conditions", "actions")},
            )
        ).status_code == 201


async def test_job_created_rule_notifies_and_drafts_proposal(auth_client):
    await auth_client.put(
        f"{P}/profile/master",
        json={"name": "Ann", "skills": ["Python", "FastAPI"], "hourly_rate": 40},
    )
    tpl = (
        await auth_client.post(
            f"{P}/proposal-templates",
            json={"name": "T", "body": "Hi {client_name}, I know {skill_match}."},
        )
    ).json()
    r = await rule(
        auth_client, name="Hot jobs", conditions=[{"field": "score", "op": "gte", "value": 50}, {"field": "skills", "op": "contains", "value": "python"}],
        actions=[{"type": "notify", "params": {"title": "Match: {title}", "body": "{score}% on {platform}", "urgent": True}}, {"type": "draft_proposal", "params": {"template_id": tpl["id"]}}],
    )  # fmt: skip
    await auth_client.post(
        f"{P}/jobs",
        json={
            "platform": "upwork",
            "title": "Cheap logo",
            "external_id": "a",
            "skills": ["Photoshop"],
            "budget_max": 20,
        },
    )
    j = (
        await auth_client.post(
            f"{P}/jobs",
            json={
                "platform": "upwork",
                "title": "FastAPI backend",
                "external_id": "b",
                "skills": ["Python", "FastAPI"],
                "description": "python fastapi",
                "client": {"name": "Bob Lee"},
                "budget_max": 900,
            },
        )
    ).json()
    notes = [
        n
        for n in (
            await auth_client.get(f"{P}/notifications", params={"type": "automation"})
        ).json()["items"]
    ]
    assert (
        len(notes) == 1
        and notes[0]["title"] == "Match: FastAPI backend"
        and notes[0]["priority"] == "high"
    )
    board = (await auth_client.get(f"{P}/pipeline")).json()
    assert len(board["drafted"]) == 1 and board["drafted"][0]["job_title"] == "FastAPI backend"
    p = board["drafted"][0]
    assert (
        p["body"].startswith("Hi Bob,") and p["approved_at"] is None
    )  # drafted, NEVER auto-approved/submitted
    rules = (await auth_client.get(f"{P}/automations")).json()
    assert rules[0]["run_count"] == 1
    runs = (await auth_client.get(f"{P}/automations/{r['id']}/runs")).json()
    assert runs[0]["status"] == "ok" and len(runs[0]["log"]) == 2
    assert j["id"]


async def test_disabled_rule_and_toggle_and_delete(auth_client):
    r = await rule(auth_client)
    assert (await auth_client.post(f"{P}/automations/{r['id']}/toggle")).json()["enabled"] is False
    await auth_client.post(
        f"{P}/jobs", json={"platform": "upwork", "title": "J", "external_id": "z"}
    )
    assert (await auth_client.get(f"{P}/automations/runs/recent")).json() == []
    assert (await auth_client.post(f"{P}/automations/{r['id']}/toggle")).json()["enabled"] is True
    assert (
        await auth_client.put(
            f"{P}/automations/{r['id']}",
            json={"name": "renamed", "trigger": "job.created", "actions": [{"type": "notify"}]},
        )
    ).json()["name"] == "renamed"
    assert (await auth_client.delete(f"{P}/automations/{r['id']}")).status_code == 200


async def test_dry_run_changes_nothing(auth_client):
    r = await rule(
        auth_client,
        conditions=[{"field": "score", "op": "gt", "value": 10}],
        actions=[
            {"type": "create_task", "params": {"title": "T {title}"}},
            {"type": "notify", "params": {"channels": ["whatsapp"]}},
        ],
    )
    miss = (
        await auth_client.post(f"{P}/automations/{r['id']}/test", json={"payload": {"score": 5}})
    ).json()
    assert miss == {"matched": False, "actions": []}
    hit = (
        await auth_client.post(
            f"{P}/automations/{r['id']}/test", json={"payload": {"score": 50, "title": "Zed"}}
        )
    ).json()
    assert (
        hit["matched"]
        and "would create task 'T Zed'" in hit["actions"][0]
        and "whatsapp" in hit["actions"][1]
    )
    assert (await auth_client.get(f"{P}/projects")).json() == [] and (
        await auth_client.get(f"{P}/automations/runs/recent")
    ).json() == []
    assert (await auth_client.get(f"{P}/notifications")).json()["items"] == []


async def test_condition_operators():
    from app.services.automation import check

    assert check({"field": "n", "op": "gte", "value": 5}, {"n": "5"}) and not check(
        {"field": "n", "op": "lt", "value": 5}, {"n": 5}
    )
    assert check({"field": "s", "op": "eq", "value": "FIVERR"}, {"s": "fiverr"}) and check(
        {"field": "s", "op": "ne", "value": "x"}, {"s": "y"}
    )
    assert check({"field": "skills", "op": "contains", "value": "py"}, {"skills": ["Python"]})
    assert check({"field": "p", "op": "in", "value": ["a", "b"]}, {"p": "B"}) and not check(
        {"field": "p", "op": "in", "value": ["a"]}, {"p": "z"}
    )
    assert check({"field": "e", "op": "exists"}, {"e": "x"}) and not check(
        {"field": "e", "op": "exists"}, {}
    )
    assert not check({"field": "missing", "op": "eq", "value": 1}, {}) and not check(
        {"field": "n", "op": "gt", "value": "abc"}, {"n": 1}
    )


async def test_message_rule_labels_and_stars_and_dedupes(auth_client):
    await rule(
        auth_client,
        trigger="message.received",
        conditions=[{"field": "client_vip", "op": "eq", "value": "true"}],
        actions=[
            {"type": "add_label", "params": {"label": "vip-{platform}"}},
            {"type": "star_conversation"},
        ],
    )
    vip = (await auth_client.post(f"{P}/clients", json={"name": "Big", "vip": True})).json()
    c1 = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "V", "client_id": vip["id"], "body": "hello"},
        )
    ).json()
    c2 = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "N", "client_name": "Nobody", "body": "hi"},
        )
    ).json()
    a = (await auth_client.get(f"{P}/conversations/{c1['id']}")).json()
    b = (await auth_client.get(f"{P}/conversations/{c2['id']}")).json()
    assert (
        a["labels"] == ["vip-direct"]
        and a["starred"] is True
        and b["labels"] == []
        and b["starred"] is False
    )


async def test_order_completed_sends_review_form_assisted(auth_client):
    form = (await auth_client.post(f"{P}/forms/from-template/review_request")).json()
    await auth_client.post(f"{P}/forms/{form['id']}/publish")
    await rule(
        auth_client,
        trigger="order.status_changed",
        conditions=[{"field": "status", "op": "eq", "value": "completed"}],
        actions=[{"type": "send_form", "params": {"form_id": form["id"]}}],
    )
    cl = (await auth_client.post(f"{P}/clients", json={"name": "Sam"})).json()
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "fiverr", "subject": "Logo", "client_id": cl["id"], "body": "thx"},
        )
    ).json()
    o = (
        await auth_client.post(
            f"{P}/orders",
            json={"platform": "fiverr", "title": "Logo", "amount": 50, "client_id": cl["id"]},
        )
    ).json()
    await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "completed"})
    msgs = (await auth_client.get(f"{P}/conversations/{conv['id']}/messages")).json()
    out = [m for m in msgs if m["direction"] == "out"]
    assert len(out) == 1 and f"/f/{form['public_key']}" in out[0]["body"]
    assert (
        out[0]["delivery"] == "pending_manual"
    )  # Fiverr has no send API: user pastes it themselves


async def test_followup_and_stale_scans(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.models import Message, Proposal
    from app.services.automation import scan_stale

    await rule(
        auth_client,
        name="stale",
        trigger="conversation.stale",
        conditions=[{"field": "hours_since_reply", "op": "gte", "value": 48}],
        actions=[{"type": "create_task", "params": {"title": "Chase {subject}"}}],
    )
    await rule(
        auth_client,
        name="pstale",
        trigger="proposal.stale",
        conditions=[{"field": "days_since_submitted", "op": "gte", "value": 5}],
        actions=[{"type": "notify", "params": {"title": "Stale: {job_title}"}}],
    )
    await rule(
        auth_client,
        name="fu",
        trigger="proposal.stage_changed",
        conditions=[{"field": "stage", "op": "eq", "value": "submitted"}],
        actions=[{"type": "set_follow_up", "params": {"in_days": 2}}],
    )
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "Quote", "client_name": "Q", "body": "price?"},
        )
    ).json()
    await auth_client.post(f"{P}/conversations/{conv['id']}/messages", json={"body": "Here it is"})
    job = (
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": "Old bid", "external_id": "ob"}
        )
    ).json()
    p = (await auth_client.post(f"{P}/proposals", json={"job_id": job["id"]})).json()
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "hi"})
    await auth_client.post(f"{P}/proposals/{p['id']}/approve")
    await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
    assert (await auth_client.get(f"{P}/proposals/{p['id']}")).json()[
        "follow_up_at"
    ]  # set by rule (and default)
    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import update

        old = datetime.now(UTC) - timedelta(days=6)
        await db.execute(
            update(Message)
            .where(Message.direction == "in")
            .values(created_at=old - timedelta(hours=1))
        )
        await db.execute(update(Message).where(Message.direction == "out").values(created_at=old))
        await db.execute(update(Proposal).values(submitted_at=old))
        await db.commit()
        assert await scan_stale(db) == 2
        assert await scan_stale(db) == 0  # idempotent
        await db.commit()
    tasks = (await auth_client.get(f"{P}/projects")).json()
    assert tasks[0]["name"] == "Inbox" and tasks[0]["tasks_total"] == 1


async def test_rate_limit_and_error_isolation(auth_client, monkeypatch):
    from app.services import automation

    monkeypatch.setattr(automation, "MAX_RUNS_PER_HOUR", 2)
    r = await rule(auth_client)
    for i in range(4):
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": f"J{i}", "external_id": f"x{i}"}
        )
    runs = (await auth_client.get(f"{P}/automations/{r['id']}/runs")).json()
    assert sorted(x["status"] for x in runs).count("ok") == 2 and any(
        x["status"] == "skipped" for x in runs
    )
    # a failing action never breaks the triggering request
    await rule(
        auth_client,
        name="bad",
        actions=[{"type": "create_task", "params": {"project_id": "not-a-uuid"}}],
    )
    assert (
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": "After", "external_id": "after"}
        )
    ).status_code == 201
    bad_runs = [
        x
        for x in (await auth_client.get(f"{P}/automations/runs/recent")).json()
        if x["status"] == "error"
    ]
    assert bad_runs and "ERROR" in bad_runs[0]["log"][0]


async def test_automations_are_tenant_isolated(auth_client, client):
    r = await rule(auth_client)
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "z@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.post(f"{P}/automations/{r['id']}/toggle")).status_code == 404
    await client.post(f"{P}/jobs", json={"platform": "upwork", "title": "Mine", "external_id": "m"})
    assert (
        await client.get(f"{P}/automations/runs/recent")
    ).json() == []  # other user's job never triggers my rule


# ---------------- assistant ----------------
async def test_briefing_is_deterministic_and_ai_narrative_optional(auth_client, monkeypatch):
    await auth_client.post(
        f"{P}/conversations",
        json={"platform": "direct", "subject": "Hi", "client_name": "A", "body": "hello"},
    )
    await auth_client.post(
        f"{P}/jobs", json={"platform": "upwork", "title": "Job", "external_id": "j"}
    )
    await auth_client.post(
        f"{P}/orders",
        json={
            "platform": "fiverr",
            "title": "Due soon",
            "due_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        },
    )
    b = (await auth_client.get(f"{P}/assistant/briefing")).json()
    assert b["facts"]["unread_messages"] == 1 and b["narrative"] is None
    assert (
        b["facts"]["deadlines_next_24h"][0]["title"].startswith("Due: Due soon")
        and b["facts"]["active_orders"] == 1
    )
    assert b["headline"].startswith("Today: 1 unread message(s), 1 deadline(s)")
    assert (await auth_client.get(f"{P}/assistant/briefing", params={"narrative": True})).json()[
        "narrative"
    ] is None  # no key => none
    from app.core.config import get_settings
    from app.services import ai

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "k")
    seen = {}

    async def fake(system, prompt, max_tokens=800):
        seen["prompt"] = prompt
        return "Handle the deadline first."

    monkeypatch.setattr(ai, "complete", fake)
    n = (await auth_client.get(f"{P}/assistant/briefing", params={"narrative": True})).json()[
        "narrative"
    ]
    assert (
        n["text"] == "Handle the deadline first." and n["ai_generated"] and n["requires_approval"]
    )
    assert "Due soon" in seen["prompt"]


async def test_extract_requirements_parsing(auth_client, monkeypatch):
    from app.services import ai

    async def good(system, prompt, max_tokens=800):
        return 'Sure! {"summary":"Landing page","requirements":["3 sections"],"deliverables":["Figma"],"deadline":"Friday","budget":null,"open_questions":["Brand colours?"]}'

    monkeypatch.setattr(ai, "complete", good)
    r = (
        await auth_client.post(
            f"{P}/assistant/extract-requirements", json={"text": "I need a landing page by Friday"}
        )
    ).json()
    assert (
        r["requirements"] == ["3 sections"]
        and r["open_questions"] == ["Brand colours?"]
        and r["ai_generated"]
    )

    async def bad(system, prompt, max_tokens=800):
        return "I could not parse that."

    monkeypatch.setattr(ai, "complete", bad)
    r = (await auth_client.post(f"{P}/assistant/extract-requirements", json={"text": "x"})).json()
    assert r["parse_warning"] is True and r["requirements"] == []
    assert (
        await auth_client.post(f"{P}/assistant/extract-requirements", json={})
    ).status_code == 422

    captured = {}

    async def cap(system, prompt, max_tokens=800):
        captured["p"] = prompt
        return "{}"

    monkeypatch.setattr(ai, "complete", cap)
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={
                "platform": "direct",
                "subject": "S",
                "client_name": "C",
                "body": "need a logo in blue",
            },
        )
    ).json()
    await auth_client.post(
        f"{P}/assistant/extract-requirements", json={"conversation_id": conv["id"]}
    )
    assert "need a logo in blue" in captured["p"]


async def test_pricing_advice_uses_your_history(auth_client):
    await auth_client.put(
        f"{P}/profile/master", json={"name": "A", "hourly_rate": 50, "skills": ["x"]}
    )
    for i, stage in enumerate(["won", "lost"]):
        j = (
            await auth_client.post(
                f"{P}/jobs",
                json={
                    "platform": "upwork",
                    "title": f"H{i}",
                    "external_id": f"h{i}",
                    "budget_min": 400,
                    "budget_max": 600,
                },
            )
        ).json()
        p = (await auth_client.post(f"{P}/proposals", json={"job_id": j["id"]})).json()
        await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "hi", "bid_amount": 450})
        await auth_client.post(f"{P}/proposals/{p['id']}/approve")
        await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
        await auth_client.patch(
            f"{P}/proposals/{p['id']}/move", json={"stage": stage, "lost_reason": "price"}
        )
    new = (
        await auth_client.post(
            f"{P}/jobs",
            json={
                "platform": "upwork",
                "title": "New",
                "external_id": "n",
                "budget_min": 400,
                "budget_max": 600,
            },
        )
    ).json()
    adv = (await auth_client.get(f"{P}/assistant/pricing/{new['id']}")).json()
    assert (
        adv["suggested_amount"] == 550
        and adv["price_band"] == "$500-1k"
        and adv["your_avg_winning_bid"] == 450
    )
    assert adv["confidence"] == "low" and adv["ai_generated"]


async def test_assistant_chat_is_grounded_in_facts(auth_client, monkeypatch):
    from app.services import ai

    seen = {}

    async def fake(system, prompt, max_tokens=800):
        seen["p"] = prompt
        return "You have 0 unread."

    monkeypatch.setattr(ai, "complete", fake)
    r = (
        await auth_client.post(
            f"{P}/assistant/chat",
            json={"message": "what's up?", "history": [{"role": "user", "content": "hi"}]},
        )
    ).json()
    assert (
        r["text"] == "You have 0 unread."
        and r["ai_generated"]
        and '"unread_messages": 0' in seen["p"]
        and "USER: what's up?" in seen["p"]
    )


@pytest.mark.parametrize(
    "path", ["/forms", "/automations", "/assistant/briefing", "/forms/templates"]
)
async def test_phase7_routes_require_auth(client, path):
    assert (await client.get(f"{P}{path}")).status_code == 401
