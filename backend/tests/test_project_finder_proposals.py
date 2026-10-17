"""Project Finder: proposal tracker."""

from datetime import UTC, datetime, timedelta

import pytest

P = "/api/v1/project-finder"


def today():
    return datetime.now(UTC).date()


async def mk_lead(c, **kw):
    return (
        await c.post(
            f"{P}/leads", json={"business_name": "Acme Dental", "source": "Cold email", **kw}
        )
    ).json()


async def mk_prop(c, **kw):
    r = await c.post(f"{P}/proposals", json={"title": "Fix booking form", "amount": 500, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_defaults_and_derivations(auth_client):
    lead = await mk_lead(auth_client)
    p = await mk_prop(auth_client, title="", lead_id=lead["id"])
    assert (
        p["title"] == "Acme Dental"
        and p["source"] == "Cold email"
        and p["lead_name"] == "Acme Dental"
    )
    assert (
        p["status"] == "sent"
        and p["sent_on"] == str(today())
        and p["days_waiting"] == 0
        and p["replied"] is False
    )
    assert p["currency"] == "USD"
    r = await auth_client.post(f"{P}/proposals", json={"amount": 1})
    assert r.status_code == 422 and "title" in r.json()["error"]["message"].lower()


async def test_creating_a_proposal_advances_the_lead(auth_client):
    lead = await mk_lead(auth_client)
    await mk_prop(auth_client, lead_id=lead["id"])
    assert (await auth_client.get(f"{P}/leads/{lead['id']}")).json()["status"] == "proposal_sent"
    # a lead that is already further along (or closed) is not pulled back
    won = await mk_lead(auth_client, business_name="Won Co")
    await auth_client.patch(f"{P}/leads/{won['id']}", json={"status": "won"})
    await mk_prop(auth_client, lead_id=won["id"])
    assert (await auth_client.get(f"{P}/leads/{won['id']}")).json()["status"] == "won"


async def test_status_flow_replies_and_won_closes_lead(auth_client):
    lead = await mk_lead(auth_client)
    p = await mk_prop(auth_client, lead_id=lead["id"], sent_on=str(today() - timedelta(days=4)))
    assert p["days_waiting"] == 4
    r = (await auth_client.patch(f"{P}/proposals/{p['id']}", json={"status": "replied"})).json()
    assert r["replied"] is True and r["replied_on"] == str(today()) and r["days_waiting"] is None
    r = (
        await auth_client.patch(
            f"{P}/proposals/{p['id']}", json={"status": "won", "outcome": "Signed, 2 weeks"}
        )
    ).json()
    assert r["status"] == "won" and r["outcome"] == "Signed, 2 weeks"
    got = (await auth_client.get(f"{P}/leads/{lead['id']}")).json()
    assert got["status"] == "won" and got["next_follow_up"] is None


async def test_lost_proposal_leaves_lead_alone_and_no_reply_is_recorded(auth_client):
    lead = await mk_lead(auth_client)
    p = await mk_prop(auth_client, lead_id=lead["id"])
    r = (await auth_client.patch(f"{P}/proposals/{p['id']}", json={"status": "no_response"})).json()
    assert r["replied"] is False and r["replied_on"] is None
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"status": "lost"})
    assert (await auth_client.get(f"{P}/leads/{lead['id']}")).json()["status"] == "proposal_sent"


async def test_patch_nulls_and_validation(auth_client):
    p = await mk_prop(auth_client, sent_on=str(today() - timedelta(days=3)))
    r = (
        await auth_client.patch(f"{P}/proposals/{p['id']}", json={"amount": None, "title": None})
    ).json()
    assert r["amount"] is None and r["title"] == "Fix booking form"  # null clears amount only
    bad = [
        {"amount": -5},
        {"currency": "EURO"},
        {"status": "ghosted"},
        {"replied_on": str(today() - timedelta(days=10))},  # before sent_on
        {"sent_on": str(today() + timedelta(days=30))},
    ]
    for body in bad:
        assert (
            await auth_client.patch(f"{P}/proposals/{p['id']}", json=body)
        ).status_code == 422, body
    assert (
        await auth_client.post(
            f"{P}/proposals", json={"title": "x", "sent_on": str(today() + timedelta(days=9))}
        )
    ).status_code == 422


async def test_filters_and_delete(auth_client):
    a = await mk_prop(auth_client, title="Alpha", source="Reddit")
    await mk_prop(auth_client, title="Beta", source="LinkedIn", status="won")
    assert [x["id"] for x in (await auth_client.get(f"{P}/proposals?source=Reddit")).json()] == [
        a["id"]
    ]
    assert [x["title"] for x in (await auth_client.get(f"{P}/proposals?status=won")).json()] == [
        "Beta"
    ]
    assert [x["title"] for x in (await auth_client.get(f"{P}/proposals?q=alp")).json()] == ["Alpha"]
    assert (await auth_client.delete(f"{P}/proposals/{a['id']}")).status_code == 200
    assert len((await auth_client.get(f"{P}/proposals")).json()) == 1
    won = (await auth_client.get(f"{P}/proposals?status=won")).json()[0]
    assert won["replied"] is True  # created as won -> a reply is implied


async def test_deleting_lead_keeps_proposal_history(auth_client):
    lead = await mk_lead(auth_client)
    p = await mk_prop(auth_client, lead_id=lead["id"])
    await auth_client.delete(f"{P}/leads/{lead['id']}")
    got = (await auth_client.get(f"{P}/proposals")).json()
    assert got[0]["id"] == p["id"] and got[0]["lead_id"] is None and got[0]["lead_name"] == ""


async def test_proposals_are_per_user(auth_client, client):
    lead = await mk_lead(auth_client)
    p = await mk_prop(auth_client, lead_id=lead["id"])
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"{P}/proposals", headers=other)).json() == []
    assert (
        await client.patch(f"{P}/proposals/{p['id']}", json={"status": "won"}, headers=other)
    ).status_code == 404
    assert (await client.delete(f"{P}/proposals/{p['id']}", headers=other)).status_code == 404
    # cannot attach a proposal to someone else's lead
    assert (
        await client.post(
            f"{P}/proposals", json={"title": "x", "lead_id": lead["id"]}, headers=other
        )
    ).status_code == 404
    assert (await auth_client.get(f"{P}/leads/{lead['id']}")).json()[
        "status"
    ] == "proposal_sent"  # untouched


@pytest.mark.parametrize("method", ["get", "post"])
async def test_requires_auth(client, method):
    assert (await getattr(client, method)(f"{P}/proposals")).status_code == 401
