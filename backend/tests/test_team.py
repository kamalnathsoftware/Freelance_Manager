import pytest

from app.api.deps import member_allowed
from app.services import email as email_svc

P = "/api/v1"


async def signup(client, email):
    r = await client.post(
        f"{P}/auth/signup",
        json={"email": email, "password": "password123", "full_name": email.split("@")[0]},
    )
    return r.json()["access_token"]


@pytest.fixture
async def team(auth_client, client):
    """owner = a@example.com (auth_client); returns headers for owner and a helper to create members."""
    owner_h = {"Authorization": client.headers["Authorization"]}
    me = (await auth_client.get(f"{P}/me")).json()

    async def add(email, role):
        email_svc.OUTBOX.clear()
        inv = await auth_client.post(f"{P}/team/invite", json={"email": email, "role": role})
        assert inv.status_code == 201, inv.text
        token = email_svc.OUTBOX[-1]["body"].split("token=")[1].split()[0].strip()
        tok = await signup(client, email)
        h = {"Authorization": f"Bearer {tok}"}
        assert (
            await client.post(f"{P}/team/accept", json={"token": token}, headers=h)
        ).status_code == 200
        return {**h, "X-Workspace": me["id"]}

    return owner_h, me, add


def test_permission_matrix():
    ok = member_allowed
    assert ok("view_only", "GET", f"{P}/jobs") and not ok("view_only", "POST", f"{P}/jobs")
    assert (
        ok("full", "DELETE", f"{P}/gigs/x")
        and not ok("full", "GET", f"{P}/me")
        and not ok("full", "POST", f"{P}/team/invite")
    )
    assert not ok("full", "PUT", f"{P}/platforms/accounts/1/token") and not ok(
        "full", "GET", f"{P}/profile/contact"
    )
    assert ok("messaging_only", "GET", f"{P}/conversations/1/messages") and ok(
        "messaging_only", "POST", f"{P}/conversations/1/messages"
    )
    assert not ok("messaging_only", "GET", f"{P}/finance/summary") and not ok(
        "messaging_only", "DELETE", f"{P}/conversations/1"
    )
    assert not ok("messaging_only", "POST", f"{P}/jobs") and ok(
        "messaging_only", "POST", f"{P}/ai/translate"
    )
    assert ok("view_only", "POST", f"{P}/auth/logout") and not ok(
        "owner", "GET", f"{P}/x"
    )  # 'owner' never goes through this path


async def test_invite_accept_and_workspace_listing(team, auth_client, client):
    owner_h, me, add = team
    h = await add("va@example.com", "messaging_only")
    members = (await auth_client.get(f"{P}/team", headers=owner_h)).json()
    assert (
        members["members"][0]["accepted"] is True
        and members["members"][0]["role"] == "messaging_only"
        and "full" in members["roles"]
    )
    ws = (
        await client.get(f"{P}/me/workspaces", headers={"Authorization": h["Authorization"]})
    ).json()
    assert [w["role"] for w in ws] == ["owner", "messaging_only"] and ws[1]["owner_id"] == me["id"]
    # duplicate / self / bad role
    assert (
        await auth_client.post(
            f"{P}/team/invite", json={"email": "VA@example.com", "role": "full"}, headers=owner_h
        )
    ).status_code == 409
    assert (
        await auth_client.post(f"{P}/team/invite", json={"email": "a@example.com"}, headers=owner_h)
    ).status_code == 422
    assert (
        await auth_client.post(
            f"{P}/team/invite", json={"email": "x@example.com", "role": "owner"}, headers=owner_h
        )
    ).status_code == 422


async def test_invitation_must_match_email_and_is_single_use(team, auth_client, client):
    owner_h, _, _ = team
    email_svc.OUTBOX.clear()
    await auth_client.post(
        f"{P}/team/invite",
        json={"email": "right@example.com", "role": "view_only"},
        headers=owner_h,
    )
    token = email_svc.OUTBOX[-1]["body"].split("token=")[1].split()[0].strip()
    wrong = {"Authorization": f"Bearer {await signup(client, 'wrong@example.com')}"}
    assert (
        await client.post(f"{P}/team/accept", json={"token": token}, headers=wrong)
    ).status_code == 403
    assert (
        await client.post(f"{P}/team/accept", json={"token": "junk"}, headers=wrong)
    ).status_code == 400
    right = {"Authorization": f"Bearer {await signup(client, 'right@example.com')}"}
    assert (
        await client.post(f"{P}/team/accept", json={"token": token}, headers=right)
    ).status_code == 200


async def test_view_only_can_read_but_not_write(team, auth_client, client):
    owner_h, _, add = team
    await auth_client.post(
        f"{P}/jobs",
        json={"platform": "upwork", "title": "Visible job", "external_id": "v"},
        headers=owner_h,
    )
    h = await add("viewer@example.com", "view_only")
    jobs = (await client.get(f"{P}/jobs", headers=h)).json()
    assert [j["title"] for j in jobs] == ["Visible job"]  # sees the OWNER's data
    r = await client.post(
        f"{P}/jobs", json={"platform": "upwork", "title": "x", "external_id": "w"}, headers=h
    )
    assert r.status_code == 403 and "view only" in r.json()["error"]["message"]
    assert (
        await client.get(f"{P}/me", headers=h)
    ).status_code == 403  # no account access in the owner's workspace
    assert (await client.get(f"{P}/api-keys", headers=h)).status_code == 403
    assert (await client.get(f"{P}/team", headers=h)).status_code == 403


async def test_messaging_only_inbox_scope_and_audit(team, auth_client, client):
    owner_h, _, add = team
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "Hi", "client_name": "C", "body": "hello"},
            headers=owner_h,
        )
    ).json()
    h = await add("va@example.com", "messaging_only")
    assert len((await client.get(f"{P}/conversations", headers=h)).json()) == 1
    sent = await client.post(
        f"{P}/conversations/{conv['id']}/messages", json={"body": "On it!"}, headers=h
    )
    assert sent.status_code == 200 and sent.json()["message"]["delivery"] == "sent"
    assert (await client.get(f"{P}/finance/summary", headers=h)).status_code == 403
    assert (await client.get(f"{P}/jobs", headers=h)).status_code == 403
    assert (await client.delete(f"{P}/conversations/{conv['id']}", headers=h)).status_code == 403
    audit = [
        a
        for a in (await auth_client.get(f"{P}/me/audit-log", headers=owner_h)).json()
        if a["action"] == "team.member_action"
    ]
    assert (
        audit
        and audit[0]["meta"]["actor_email"] == "va@example.com"
        and audit[0]["meta"]["role"] == "messaging_only"
    )


async def test_full_member_manages_data_but_not_account_or_credentials(team, auth_client, client):
    owner_h, _, add = team
    acc = (
        await auth_client.post(
            f"{P}/platforms/accounts", json={"platform": "upwork"}, headers=owner_h
        )
    ).json()
    h = await add("full@example.com", "full")
    assert (
        await client.post(f"{P}/gigs", json={"title": "Team gig", "packages": []}, headers=h)
    ).status_code == 201
    assert (
        await client.put(
            f"{P}/platforms/accounts/{acc['id']}/token", json={"access_token": "steal"}, headers=h
        )
    ).status_code == 403
    assert (await client.put(f"{P}/profile/contact", json={"a": "b"}, headers=h)).status_code == 403
    assert (await client.get(f"{P}/ingest/gmail/auth-url", headers=h)).status_code == 403
    assert (
        await client.request(
            "DELETE",
            f"{P}/me",
            json={"current_password": "x", "new_password": "xxxxxxxx"},
            headers=h,
        )
    ).status_code == 403
    # the gig landed in the OWNER's workspace
    assert len((await auth_client.get(f"{P}/gigs", headers=owner_h)).json()) == 1


async def test_role_change_and_removal_take_effect_immediately(team, auth_client, client):
    owner_h, _, add = team
    h = await add("va@example.com", "full")
    tid = (await auth_client.get(f"{P}/team", headers=owner_h)).json()["members"][0]["id"]
    assert (
        await client.post(f"{P}/gigs", json={"title": "g", "packages": []}, headers=h)
    ).status_code == 201
    assert (
        await auth_client.patch(f"{P}/team/{tid}", json={"role": "view_only"}, headers=owner_h)
    ).json()["role"] == "view_only"
    assert (
        await client.post(f"{P}/gigs", json={"title": "g2", "packages": []}, headers=h)
    ).status_code == 403
    assert (
        await auth_client.patch(f"{P}/team/{tid}", json={"role": "owner"}, headers=owner_h)
    ).status_code == 422
    assert (await auth_client.delete(f"{P}/team/{tid}", headers=owner_h)).status_code == 200
    assert (await client.get(f"{P}/gigs", headers=h)).status_code == 403  # no longer a member
    assert (await auth_client.delete(f"{P}/team/{tid}", headers=owner_h)).status_code == 404


async def test_cannot_use_a_workspace_you_do_not_belong_to(team, auth_client, client):
    owner_h, me, _ = team
    stranger = {
        "Authorization": f"Bearer {await signup(client, 's@example.com')}",
        "X-Workspace": me["id"],
    }
    assert (await client.get(f"{P}/jobs", headers=stranger)).status_code == 403
    assert (
        await client.get(f"{P}/jobs", headers={**stranger, "X-Workspace": "not-a-uuid"})
    ).status_code == 400
    own = {"Authorization": stranger["Authorization"]}
    assert (await client.get(f"{P}/jobs", headers=own)).json() == []
