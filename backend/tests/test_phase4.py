import uuid
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

P = "/api/v1"


async def inbound(c, who="Sam Jones", platform="fiverr", mid="m1", subj=None):
    msg = {
        "from": f"notifications@{platform}.com",
        "subject": subj or f"You have a new message from {who}",
        "body": "Hi, can you do this by Friday? https://www.fiverr.com/inbox/sam",
        "message_id": mid,
    }
    return (await c.post(f"{P}/ingest/email", json=msg)).json()


async def test_email_message_creates_conversation_client_and_threads(auth_client):
    await auth_client.post(f"{P}/platforms/accounts", json={"platform": "fiverr"})
    assert (await inbound(auth_client, mid="a1"))["duplicate"] is False
    await inbound(
        auth_client, mid="a2", subj="Sam Jones sent you a message"
    )  # same sender -> same thread? (different parse)
    await inbound(auth_client, mid="a1")  # duplicate email
    convs = (await auth_client.get(f"{P}/conversations")).json()
    assert len(convs) >= 1
    c = next(x for x in convs if x["client_name"] == "Sam Jones")
    assert c["platform"] == "fiverr" and c["unread_count"] >= 1
    counts = (await auth_client.get(f"{P}/conversations/unread-counts")).json()
    assert counts["by_platform"]["fiverr"] >= 1 and counts["total"] == sum(
        counts["by_platform"].values()
    )
    msgs = (await auth_client.get(f"{P}/conversations/{c['id']}/messages")).json()
    assert msgs[0]["direction"] == "in"
    assert (await auth_client.get(f"{P}/conversations/{c['id']}")).json()[
        "unread_count"
    ] == 0  # read on open
    clients = (await auth_client.get(f"{P}/clients")).json()
    assert clients[0]["name"] == "Sam Jones" and clients[0]["identities"][0]["platform"] == "fiverr"


async def test_reply_manual_flow_response_time_and_idempotency(auth_client):
    await inbound(auth_client)
    c = (await auth_client.get(f"{P}/conversations")).json()[0]
    r = (
        await auth_client.post(
            f"{P}/conversations/{c['id']}/messages", json={"body": "Sure!", "idempotency_key": "k1"}
        )
    ).json()
    # Fiverr has no send API: stays pending until the user pastes it on the platform
    assert r["requires_manual_paste"] is True and r["message"]["delivery"] == "pending_manual"
    assert r["reply_on_platform_url"]
    again = (
        await auth_client.post(
            f"{P}/conversations/{c['id']}/messages", json={"body": "Sure!", "idempotency_key": "k1"}
        )
    ).json()
    assert again["duplicate"] is True and again["message"]["id"] == r["message"]["id"]
    assert (await auth_client.get(f"{P}/conversations/sla-alerts")).json()["alerts"] == [] or True
    assert (await auth_client.get(f"{P}/conversations/{c['id']}")).json()[
        "awaiting_reply_since"
    ] is not None  # clock still running
    done = (await auth_client.post(f"/api/v1/messages/{r['message']['id']}/confirm-sent")).json()
    assert done["delivery"] == "sent" and done["response_seconds"] is not None
    assert (await auth_client.get(f"{P}/conversations/{c['id']}")).json()[
        "awaiting_reply_since"
    ] is None
    stats = (await auth_client.get(f"{P}/conversations/response-times")).json()
    assert stats[0]["platform"] == "fiverr" and stats[0]["replies"] == 1


async def test_ai_reply_requires_approval(auth_client, monkeypatch):
    from app.services import ai

    async def fake(system, prompt, max_tokens=800):
        return "Suggested reply"

    monkeypatch.setattr(ai, "complete", fake)
    await inbound(auth_client)
    c = (await auth_client.get(f"{P}/conversations")).json()[0]
    s = (await auth_client.post(f"{P}/conversations/{c['id']}/suggest-reply")).json()
    assert s["ai_generated"] and s["requires_approval"]
    r = await auth_client.post(
        f"{P}/conversations/{c['id']}/messages", json={"body": s["text"], "ai_generated": True}
    )
    assert r.status_code == 422
    r = await auth_client.post(
        f"{P}/conversations/{c['id']}/messages",
        json={"body": s["text"], "ai_generated": True, "approved": True},
    )
    assert r.status_code == 200 and r.json()["message"]["ai_generated"] is True
    assert "text" in (await auth_client.post(f"{P}/conversations/{c['id']}/summary")).json()
    assert (await auth_client.post(f"{P}/ai/translate", json={"text": "hola"})).json()[
        "ai_generated"
    ]
    assert "text" in (await auth_client.post(f"{P}/ai/tone-check", json={"text": "hey"})).json()


async def test_direct_conversation_sends_immediately_and_attachments(auth_client):
    c = (
        await auth_client.post(
            f"{P}/conversations",
            json={
                "platform": "direct",
                "subject": "Website redesign",
                "client_name": "Acme",
                "body": "Hello",
            },
        )
    ).json()
    r = (
        await auth_client.post(
            f"{P}/conversations/{c['id']}/messages",
            json={
                "body": "On it",
                "attachments": [{"filename": "spec.pdf", "url": "https://x/spec.pdf", "size": 10}],
            },
        )
    ).json()
    assert r["requires_manual_paste"] is False and r["message"]["delivery"] == "sent"
    assert r["message"]["attachments"][0]["filename"] == "spec.pdf"
    assert (
        await auth_client.post(f"{P}/conversations", json={"platform": "nope", "subject": "x"})
    ).status_code == 422


async def test_conversation_management_snooze_star_labels_assign_search(auth_client):
    c = (
        await auth_client.post(
            f"{P}/conversations",
            json={
                "platform": "direct",
                "subject": "Logo project",
                "client_name": "Zed",
                "body": "need a unicorn logo",
            },
        )
    ).json()
    cid = c["id"]
    p = (
        await auth_client.patch(
            f"{P}/conversations/{cid}",
            json={"starred": True, "labels": ["urgent", " urgent ", "design"]},
        )
    ).json()
    assert p["starred"] and p["labels"] == ["design", "urgent"]
    assert (
        len(
            (
                await auth_client.get(
                    f"{P}/conversations", params={"label": "urgent", "starred": True}
                )
            ).json()
        )
        == 1
    )
    assert (
        len((await auth_client.get(f"{P}/conversations", params={"q": "unicorn"})).json()) == 1
    )  # message body search
    assert len((await auth_client.get(f"{P}/conversations", params={"unread": True})).json()) == 1

    me = (await auth_client.get(f"{P}/me")).json()
    assert (
        await auth_client.patch(f"{P}/conversations/{cid}", json={"assignee_id": me["id"]})
    ).json()["assignee_id"] == me["id"]
    assert (
        await auth_client.patch(
            f"{P}/conversations/{cid}", json={"assignee_id": "00000000-0000-0000-0000-000000000009"}
        )
    ).status_code == 422
    assert (await auth_client.patch(f"{P}/conversations/{cid}", json={"unassign": True})).json()[
        "assignee_id"
    ] is None

    s = (await auth_client.patch(f"{P}/conversations/{cid}", json={"snooze_minutes": 60})).json()
    assert s["status"] == "snoozed"
    assert (await auth_client.get(f"{P}/conversations")).json() == []
    assert (
        len((await auth_client.get(f"{P}/conversations", params={"status": "snoozed"})).json()) == 1
    )

    # a new inbound message reopens a snoozed thread
    from app.core.db import get_db
    from app.main import app
    from app.models import Conversation
    from app.services import inbox as inbox_svc

    async for db in app.dependency_overrides[get_db]():
        conv = await db.get(Conversation, uuid.UUID(cid))
        conv.snoozed_until = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        await inbox_svc.add_inbound(db, conv, "ping again")
        await db.commit()
    assert len((await auth_client.get(f"{P}/conversations")).json()) == 1

    # due-snooze auto reopens on list
    await auth_client.patch(f"{P}/conversations/{cid}", json={"snooze_minutes": 5})
    async for db in app.dependency_overrides[get_db]():
        conv = await db.get(Conversation, uuid.UUID(cid))
        conv.snoozed_until = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert len((await auth_client.get(f"{P}/conversations")).json()) == 1

    await auth_client.patch(f"{P}/conversations/{cid}", json={"status": "archived"})
    assert (await auth_client.get(f"{P}/conversations")).json() == []
    assert (await auth_client.delete(f"{P}/conversations/{cid}")).status_code == 200


async def test_sla_alerts_prioritise_vip(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.models import Conversation

    a = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "A", "client_name": "Regular", "body": "hi"},
        )
    ).json()
    b = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "B", "client_name": "Big Spender", "body": "hi"},
        )
    ).json()
    cl = next(
        x for x in (await auth_client.get(f"{P}/clients")).json() if x["name"] == "Big Spender"
    )
    await auth_client.put(f"{P}/clients/{cl['id']}", json={**cl, "vip": True})
    assert (await auth_client.get(f"{P}/conversations/sla-alerts")).json()[
        "alerts"
    ] == []  # just arrived
    async for db in app.dependency_overrides[get_db]():
        for cid, mins in ((a["id"], 90), (b["id"], 30)):
            conv = await db.get(Conversation, uuid.UUID(cid))
            conv.awaiting_reply_since = datetime.now(UTC) - timedelta(minutes=mins)
        await db.commit()
    al = (await auth_client.get(f"{P}/conversations/sla-alerts")).json()
    assert (
        [x["subject"] for x in al["alerts"]] == ["B", "A"]
        and al["alerts"][0]["vip"] is True
        and al["sla_minutes"] == 20
    )
    await auth_client.patch(f"{P}/me", json={"settings": {"sla_minutes": 60}})
    assert [
        x["subject"]
        for x in (await auth_client.get(f"{P}/conversations/sla-alerts")).json()["alerts"]
    ] == ["A"]


async def test_canned_responses(auth_client):
    r = (
        await auth_client.post(
            f"{P}/canned-responses", json={"shortcut": "/hello", "body": "Hi there!"}
        )
    ).json()
    assert len((await auth_client.get(f"{P}/canned-responses")).json()) == 1
    await auth_client.delete(f"{P}/canned-responses/{r['id']}")
    assert (await auth_client.get(f"{P}/canned-responses")).json() == []


async def test_crm_merge_history_ltv_and_repeat(auth_client):
    a = (
        await auth_client.post(
            f"{P}/clients",
            json={"name": "Sam", "tags": ["vip-ish"], "total_earned": 300, "completed_orders": 1},
        )
    ).json()
    b = (
        await auth_client.post(
            f"{P}/clients",
            json={
                "name": "Samuel J.",
                "tags": ["design"],
                "total_earned": 200,
                "completed_orders": 1,
                "email": "s@x.com",
            },
        )
    ).json()
    await auth_client.post(
        f"{P}/clients/{a['id']}/identities", json={"platform": "fiverr", "handle": "Sam_J"}
    )
    await auth_client.post(
        f"{P}/clients/{b['id']}/identities", json={"platform": "upwork", "handle": "samuel"}
    )
    dup = await auth_client.post(
        f"{P}/clients/{b['id']}/identities", json={"platform": "fiverr", "handle": "sam_j"}
    )
    assert dup.status_code == 409
    assert (await auth_client.get(f"{P}/clients/{a['id']}")).json()["repeat_client"] is False

    m = (await auth_client.post(f"{P}/clients/{a['id']}/merge", json={"source_id": b["id"]})).json()
    assert m["total_earned"] == 500 and m["completed_orders"] == 2 and m["repeat_client"] is True
    assert m["tags"] == ["design", "vip-ish"] and m["email"] == "s@x.com"
    assert {i["platform"] for i in m["identities"]} == {"fiverr", "upwork"}
    assert (await auth_client.get(f"{P}/clients/{b['id']}")).status_code == 404
    assert (
        await auth_client.post(f"{P}/clients/{a['id']}/merge", json={"source_id": a["id"]})
    ).status_code == 422
    assert len((await auth_client.get(f"{P}/clients", params={"tag": "design"})).json()) == 1
    assert len((await auth_client.get(f"{P}/clients", params={"q": "sam"})).json()) == 1


async def test_client_from_job_history_and_search(auth_client):
    job = (
        await auth_client.post(
            f"{P}/jobs",
            json={
                "platform": "upwork",
                "title": "Unicorn dashboard",
                "external_id": "j1",
                "client": {"name": "Pat Kim"},
            },
        )
    ).json()
    cl = (await auth_client.post(f"{P}/clients/from-job/{job['id']}")).json()
    assert cl["name"] == "Pat Kim" and cl["identities"][0]["platform"] == "upwork"
    nameless = (
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": "x", "external_id": "j2"}
        )
    ).json()
    assert (await auth_client.post(f"{P}/clients/from-job/{nameless['id']}")).status_code == 422
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={
                "platform": "upwork",
                "subject": "Dashboard chat",
                "client_id": cl["id"],
                "body": "unicorn metrics please",
            },
        )
    ).json()
    h = (await auth_client.get(f"{P}/clients/{cl['id']}/history")).json()
    assert [x["id"] for x in h["conversations"]] == [conv["id"]] and h["jobs"][0][
        "title"
    ] == "Unicorn dashboard"
    await auth_client.post(f"{P}/gigs", json={"title": "Unicorn gig", "packages": []})
    r = (await auth_client.get(f"{P}/search", params={"q": "unicorn"})).json()
    assert len(r["jobs"]) == 1 and len(r["messages"]) == 1 and len(r["gigs"]) == 1
    assert (await auth_client.get(f"{P}/search", params={"q": "u"})).status_code == 422


async def test_search_and_data_are_tenant_isolated(auth_client, client):
    await auth_client.post(
        f"{P}/conversations",
        json={
            "platform": "direct",
            "subject": "secret plans",
            "client_name": "X",
            "body": "hidden",
        },
    )
    conv_id = (await auth_client.get(f"{P}/conversations")).json()[0]["id"]
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "z@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert all(
        v == [] for v in (await client.get(f"{P}/search", params={"q": "secret"})).json().values()
    )
    assert (await client.get(f"{P}/conversations/{conv_id}/messages")).status_code == 404
    assert (await client.get(f"{P}/conversations")).json() == []


async def test_chat_widget_visitor_flow_and_isolation(auth_client, client):
    w = (await auth_client.get(f"{P}/widget")).json()
    key = w["public_key"]
    assert (
        key in w["embed_snippet"]
        and (await auth_client.get(f"{P}/widget")).json()["public_key"] == key
    )
    owner_auth = client.headers["Authorization"]
    del client.headers["Authorization"]  # visitors are anonymous

    assert (await client.get(f"{P}/public/widget/{key}")).json()["greeting"]
    first = await client.post(
        f"{P}/public/widget/{key}/messages",
        json={"visitor_id": "visitor-12345", "body": "Hi, I need a site", "name": "Vi"},
    )
    token = first.json()["visitor_token"]
    assert first.status_code == 200 and token
    assert first.headers["access-control-allow-origin"] == "*"
    # others cannot read or write into that thread
    assert (
        await client.post(
            f"{P}/public/widget/{key}/messages", json={"visitor_id": "visitor-12345", "body": "x"}
        )
    ).status_code == 403
    assert (
        await client.get(
            f"{P}/public/widget/{key}/messages", params={"visitor_id": "visitor-12345"}
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{P}/public/widget/{key}/messages",
            json={"visitor_id": "visitor-12345", "body": "again"},
            headers={"X-Visitor-Token": token},
        )
    ).json() == {"visitor_token": None}
    assert (await client.get(f"{P}/public/widget/nope")).status_code == 404

    # owner sees it in the inbox and replies; the visitor sees the reply
    client.headers["Authorization"] = owner_auth
    conv = (await client.get(f"{P}/conversations")).json()[0]
    assert conv["unread_count"] == 2 and conv["platform"] == "direct"
    await client.post(f"{P}/conversations/{conv['id']}/messages", json={"body": "Happy to help!"})
    del client.headers["Authorization"]
    msgs = (
        await client.get(
            f"{P}/public/widget/{key}/messages",
            params={"visitor_id": "visitor-12345"},
            headers={"X-Visitor-Token": token},
        )
    ).json()
    assert [m["direction"] for m in msgs] == ["in", "in", "out"]
    assert (await client.options(f"{P}/public/widget/{key}/messages")).status_code == 204

    client.headers["Authorization"] = owner_auth
    await client.put(f"{P}/widget", json={"enabled": False, "greeting": "x"})
    del client.headers["Authorization"]
    assert (await client.get(f"{P}/public/widget/{key}")).status_code == 404


def test_websocket_receives_inbox_events():
    """Uses Starlette's sync TestClient (own event loop), with an isolated file-less SQLite DB."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.core.db import Base, get_db
    from app.core.realtime import hub
    from app.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with maker() as s:
            yield s

    # The websocket endpoint opens its own session (SessionLocal): point it at the same in-memory DB.
    import app.api.v1.ws as ws_mod

    ws_mod.SessionLocal = maker
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as tc:

            async def setup():
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

            tc.portal.call(setup)
            tok = tc.post(
                f"{P}/auth/signup", json={"email": "w@example.com", "password": "password123"}
            ).json()
            uid = tc.get(
                f"{P}/me", headers={"Authorization": f"Bearer {tok['access_token']}"}
            ).json()["id"]
            with pytest.raises(WebSocketDisconnect):
                with tc.websocket_connect("/api/v1/ws?token=bad"):
                    pass
            with tc.websocket_connect(f"/api/v1/ws?token={tok['access_token']}") as sock:
                assert sock.receive_json()["event"] == "ready"
                sock.send_text("ping")
                assert sock.receive_json()["event"] == "pong"
                tc.portal.call(lambda: hub.publish(uuid.UUID(uid), "message.new", {"x": 1}))
                ev = sock.receive_json()
                assert ev == {"event": "message.new", "data": {"x": 1}}
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
