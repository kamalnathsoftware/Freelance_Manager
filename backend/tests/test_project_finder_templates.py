"""Project Finder: templates, placeholder rendering and the LLM draft."""

import pytest

from app.services import ai
from app.services.project_finder.templates import render, split_subject

P = "/api/v1/project-finder"


async def mk_lead(c, **kw):
    body = {
        "business_name": "Acme Dental",
        "contact_name": "Dana Smith",
        "problem": "Booking form fails on iPhone",
        **kw,
    }
    return (await c.post(f"{P}/leads", json=body)).json()


async def mk_tpl(c, **kw):
    body = {
        "name": "T1",
        "kind": "cold_email",
        "subject": "About {{company}}",
        "body": "Hi {{first_name}}, {{problem}}. - {{my_name}}",
        **kw,
    }
    return (await c.post(f"{P}/templates", json=body)).json()


def test_render_fills_reports_and_never_re_expands():
    vals = {
        "company": "Acme",
        "problem": "uses {{my_name}} literally",
        "my_name": "Kamal",
        "first_name": "",
    }
    out, missing, unknown = render(
        "{{ company }}: {{problem}} / {{first_name}} / {{bogus}} / {{my_name}}", vals
    )
    assert out == "Acme: uses {{my_name}} literally / {{first_name}} / {{bogus}} / Kamal"
    assert missing == ["first_name"] and unknown == ["bogus"]


def test_split_subject():
    assert split_subject("cold_email", "Subject: Hello\nBody here") == ("Hello", "Body here")
    assert split_subject("cold_email", "No subject line") == ("", "No subject line")
    assert split_subject("linkedin_dm", "Subject: x\ny") == ("", "Subject: x\ny")


async def test_template_crud_and_validation(auth_client):
    t = await mk_tpl(auth_client)
    assert t["kind"] == "cold_email"
    r = await auth_client.patch(f"{P}/templates/{t['id']}", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed"
    assert (
        await auth_client.patch(f"{P}/templates/{t['id']}", json={"body": "  "})
    ).status_code == 422
    assert [x["id"] for x in (await auth_client.get(f"{P}/templates?kind=cold_email")).json()] == [
        t["id"]
    ]
    assert (await auth_client.get(f"{P}/templates?kind=proposal")).json() == []
    for bad in ({"kind": "fax"}, {"name": " "}, {"body": ""}):
        assert (
            await auth_client.post(
                f"{P}/templates", json={"name": "x", "kind": "proposal", "body": "b", **bad}
            )
        ).status_code == 422
    assert (await auth_client.delete(f"{P}/templates/{t['id']}")).status_code == 200
    assert (
        await auth_client.patch(f"{P}/templates/{t['id']}", json={"name": "z"})
    ).status_code == 404


async def test_starters_are_idempotent(auth_client):
    first = (await auth_client.post(f"{P}/templates/starters")).json()
    assert {t["kind"] for t in first} == {"cold_email", "linkedin_dm", "proposal"}
    assert (await auth_client.post(f"{P}/templates/starters")).json() == []
    assert len((await auth_client.get(f"{P}/templates")).json()) == 3


async def test_render_endpoint(auth_client):
    await auth_client.put(f"{P}/settings", json={"my_name": "Kamal"})
    lead = await mk_lead(auth_client)
    t = await mk_tpl(auth_client)
    r = (
        await auth_client.post(f"{P}/templates/{t['id']}/render", json={"lead_id": lead["id"]})
    ).json()
    assert r["subject"] == "About Acme Dental"
    assert r["body"] == "Hi Dana, Booking form fails on iPhone. - Kamal"
    assert r["missing"] == [] and r["ai_generated"] is False

    # no lead: every lead-derived placeholder is reported, your own name still fills
    r = (await auth_client.post(f"{P}/templates/{t['id']}/render", json={})).json()
    assert set(r["missing"]) == {"company", "first_name", "problem"} and r["body"].endswith(
        "- Kamal"
    )


async def test_generate_uses_llm_and_never_sends(auth_client, monkeypatch):
    seen = {}

    async def fake(system, prompt, max_tokens=800):
        seen["system"], seen["prompt"] = system, prompt
        return "Subject: Fixing your booking form\nHi Dana - saw the iPhone issue."

    monkeypatch.setattr(ai, "complete", fake)
    lead = await mk_lead(auth_client, notes="Owner replied on Reddit")
    t = await mk_tpl(auth_client)
    r = (
        await auth_client.post(
            f"{P}/templates/{t['id']}/generate",
            json={"lead_id": lead["id"], "instructions": "keep it friendly"},
        )
    ).json()
    assert r["ai_generated"] is True
    assert (
        r["subject"] == "Fixing your booking form"
        and r["body"] == "Hi Dana - saw the iPhone issue."
    )
    assert (
        "Booking form fails on iPhone" in seen["prompt"]
        and "Owner replied on Reddit" in seen["prompt"]
    )
    assert "keep it friendly" in seen["prompt"] and "never invent" in seen["system"].lower()


async def test_generate_without_api_key_is_a_clear_503(auth_client):
    lead = await mk_lead(auth_client)
    t = await mk_tpl(auth_client)
    r = await auth_client.post(f"{P}/templates/{t['id']}/generate", json={"lead_id": lead["id"]})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["error"]["message"]
    # the plain render still works without a key
    assert (
        await auth_client.post(f"{P}/templates/{t['id']}/render", json={"lead_id": lead["id"]})
    ).status_code == 200


async def test_templates_and_leads_are_per_user(auth_client, client):
    t = await mk_tpl(auth_client)
    lead = await mk_lead(auth_client)
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"{P}/templates", headers=other)).json() == []
    assert (
        await client.post(f"{P}/templates/{t['id']}/render", json={}, headers=other)
    ).status_code == 404
    mine = await mk_tpl(auth_client, name="mine")
    # another user's lead can't be pulled into a render, even with a valid template of one's own
    r = await client.post(
        f"{P}/templates", json={"name": "o", "kind": "proposal", "body": "x"}, headers=other
    )
    ot = r.json()
    assert (
        await client.post(
            f"{P}/templates/{ot['id']}/render", json={"lead_id": lead["id"]}, headers=other
        )
    ).status_code == 404
    assert mine["id"] != ot["id"]


@pytest.mark.parametrize("path", ["/templates", "/templates/variables"])
async def test_requires_auth(client, path):
    assert (await client.get(f"{P}{path}")).status_code == 401
