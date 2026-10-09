import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.notify import channels as ch
from app.services import email as email_svc

P = "/api/v1"


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._d, self.text = status, data or {}, text

    def json(self):
        return self._d


class FakeHttp:
    """Records outbound provider calls; behaviour controlled by FakeHttp.responder."""

    calls: list = []
    responder = staticmethod(
        lambda url, **kw: Resp(
            200, {"messages": [{"id": "wamid.1"}], "sid": "SM1", "result": {"message_id": 7}}
        )
    )

    def __init__(self, *a, **k): ...
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a): ...
    async def post(self, url, **kw):
        FakeHttp.calls.append((url, kw))
        return FakeHttp.responder(url, **kw)


@pytest.fixture
def http(monkeypatch):
    FakeHttp.calls = []
    FakeHttp.responder = staticmethod(
        lambda url, **kw: Resp(
            200, {"messages": [{"id": "wamid.1"}], "sid": "SM1", "result": {"message_id": 7}}
        )
    )
    monkeypatch.setattr(httpx, "AsyncClient", FakeHttp)
    s = get_settings()
    for k, v in dict(
        whatsapp_token="t",
        whatsapp_phone_number_id="123",
        whatsapp_verify_token="vt",
        whatsapp_app_secret="appsecret",
        twilio_account_sid="AC",
        twilio_auth_token="tk",
        twilio_from="+1000",
        telegram_bot_token="bot",
        telegram_webhook_secret="tgsecret",
    ).items():
        monkeypatch.setattr(s, k, v)
    return FakeHttp


async def prefs(c, matrix, **settings):
    r = await c.put(f"{P}/notifications/preferences", json={"matrix": matrix, **settings})
    assert r.status_code == 200, r.text
    return r.json()


async def deliveries(c, **q):
    return (await c.get(f"{P}/notifications/deliveries", params=q)).json()


async def make_conv(c, body="hello", name="Acme", platform="direct"):
    return (
        await c.post(
            f"{P}/conversations",
            json={"platform": platform, "subject": "Project", "client_name": name, "body": body},
        )
    ).json()


async def test_inbound_message_creates_in_app_notification_and_read_flow(auth_client):
    await make_conv(auth_client)
    n = (await auth_client.get(f"{P}/notifications")).json()
    assert n["unread"] == 1 and n["items"][0]["type"] == "new_message"
    nid = n["items"][0]["id"]
    assert (await auth_client.post(f"{P}/notifications/{nid}/read")).json()["read_at"]
    assert (await auth_client.get(f"{P}/notifications", params={"unread": True})).json()[
        "items"
    ] == []
    await make_conv(auth_client, name="Other")
    await auth_client.post(f"{P}/notifications/read-all")
    assert (await auth_client.get(f"{P}/notifications")).json()["unread"] == 0
    assert (await auth_client.get(f"{P}/notifications", params={"type": "job_match"})).json()[
        "items"
    ] == []


async def test_preference_matrix_and_defaults(auth_client):
    p = (await auth_client.get(f"{P}/notifications/preferences")).json()
    assert p["matrix"]["new_message"]["in_app"]["enabled"] is True
    assert p["matrix"]["new_message"]["whatsapp"]["enabled"] is False  # paid channels are opt-in
    assert len(p["event_types"]) == 17
    p = await prefs(auth_client, {"new_message": {"email": {"enabled": True, "mode": "instant"}}})
    assert p["matrix"]["new_message"]["email"]["enabled"] is True
    assert (
        await auth_client.put(f"{P}/notifications/preferences", json={"matrix": {"bogus": {}}})
    ).status_code == 422
    assert (
        await auth_client.put(
            f"{P}/notifications/preferences", json={"matrix": {"new_message": {"nope": {}}}}
        )
    ).status_code == 422
    r = await auth_client.put(
        f"{P}/notifications/preferences",
        json={"matrix": {"new_message": {"email": {"mode": "weekly"}}}},
    )
    assert r.status_code == 422


async def test_email_channel_delivery_and_log(auth_client):
    await prefs(auth_client, {"new_message": {"email": {"enabled": True}}})
    email_svc.OUTBOX.clear()
    await make_conv(auth_client, body="Need a quote")
    assert email_svc.OUTBOX and "message" in email_svc.OUTBOX[-1]["subject"].lower()
    log = await deliveries(auth_client, channel="email")
    assert log[0]["status"] == "sent" and log[0]["event_title"]


async def test_dedupe_same_source_message(auth_client):
    msg = {
        "from": "n@fiverr.com",
        "subject": "You have a new message from Sam Jones",
        "body": "hi",
        "message_id": "dup-1",
    }
    await auth_client.post(f"{P}/ingest/email", json=msg)
    await auth_client.post(f"{P}/ingest/email", json=msg)
    assert (await auth_client.get(f"{P}/notifications")).json()["unread"] == 1


async def test_platform_events_map_to_types(auth_client):
    for i, (subj, _typ) in enumerate(
        [
            ("New order #AB12CD from Sam", "new_order"),
            ("Sam requested a revision", "revision_requested"),
            ("Payment received $50", "payment_received"),
            ("Sam left you a 5-star review", "review_received"),
            ("Sam viewed your proposal", "bid_viewed"),
            ("Sam accepted your proposal", "bid_accepted"),
            ("Sam declined your proposal", "bid_declined"),
        ]
    ):
        await auth_client.post(
            f"{P}/ingest/email",
            json={"from": "x@upwork.com", "subject": subj, "body": "b", "message_id": f"t{i}"},
        )
    types = {n["type"] for n in (await auth_client.get(f"{P}/notifications")).json()["items"]}
    assert {
        "new_order",
        "revision_requested",
        "payment_received",
        "review_received",
        "bid_viewed",
        "bid_accepted",
        "bid_declined",
    } <= types


async def test_whatsapp_requires_optin_and_sends_template(auth_client, http):
    await prefs(auth_client, {"new_message": {"whatsapp": {"enabled": True}}})
    await make_conv(auth_client)
    d = await deliveries(auth_client, channel="whatsapp")
    assert d[0]["status"] == "skipped"  # no number / no opt-in => never sent
    assert not http.calls
    assert (
        await auth_client.put(
            f"{P}/notifications/channels",
            json={"channel": "whatsapp", "address": "", "opted_in": True},
        )
    ).status_code == 422
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "whatsapp", "address": "+44 7700 900123", "opted_in": False},
    )
    await make_conv(auth_client, name="B")
    assert (await deliveries(auth_client, channel="whatsapp"))[0]["status"] == "skipped"
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "whatsapp", "address": "+44 7700 900123", "opted_in": True},
    )
    await make_conv(auth_client, name="C")
    d = (await deliveries(auth_client, channel="whatsapp"))[0]
    assert d["status"] == "sent"
    url, kw = http.calls[-1]
    assert (
        url.endswith("/123/messages")
        and kw["json"]["to"] == "447700900123"
        and kw["json"]["type"] == "template"
    )
    params = [p["text"] for p in kw["json"]["template"]["components"][0]["parameters"]]
    assert len(params) == 3 and len(params[2]) == 4  # reply code


async def test_retry_with_backoff_then_fallback_to_email(auth_client, http):
    await prefs(auth_client, {"new_message": {"whatsapp": {"enabled": True}}})
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "whatsapp", "address": "+15550001", "opted_in": True},
    )
    http.responder = staticmethod(lambda url, **kw: Resp(503))
    email_svc.OUTBOX.clear()
    await make_conv(auth_client)
    d = (await deliveries(auth_client, channel="whatsapp"))[0]
    assert (
        d["status"] == "pending"
        and d["attempts"] == 1
        and "503" in d["error"]
        and d["next_attempt_at"]
    )

    from app.core.db import get_db
    from app.main import app
    from app.services.notifications import process_due

    async for db in app.dependency_overrides[get_db]():
        assert await process_due(db) == 0  # backoff not elapsed yet
        for step in range(3):
            n = await process_due(db, datetime.now(UTC) + timedelta(hours=2 * (step + 1)))
            assert n == 1
        await db.commit()
    d = (await deliveries(auth_client, channel="whatsapp"))[0]
    assert d["status"] == "failed" and d["attempts"] == 4
    fb = (await deliveries(auth_client, channel="email"))[0]
    assert fb["status"] == "sent" and fb["fallback_of"] == d["id"]
    assert email_svc.OUTBOX  # fallback email actually went out


async def test_non_retryable_error_goes_straight_to_fallback(auth_client, http):
    await prefs(auth_client, {"new_message": {"sms": {"enabled": True}}})
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "sms", "address": "+15550002", "opted_in": True},
    )
    http.responder = staticmethod(lambda url, **kw: Resp(400, text="bad number"))
    await make_conv(auth_client)
    sms = (await deliveries(auth_client, channel="sms"))[0]
    assert sms["status"] == "failed" and sms["attempts"] == 1
    assert (await deliveries(auth_client, channel="email"))[0]["status"] == "sent"
    # manual retry endpoint
    http.responder = staticmethod(lambda url, **kw: Resp(200, {"sid": "SM9"}))
    r = await auth_client.post(f"{P}/notifications/deliveries/{sms['id']}/retry")
    assert r.json()["status"] == "sent"
    assert (
        await auth_client.post(f"{P}/notifications/deliveries/{sms['id']}/retry")
    ).status_code == 409


async def test_unconfigured_channel_is_failed_and_falls_back(auth_client):
    await prefs(auth_client, {"new_message": {"telegram": {"enabled": True}}})
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "telegram", "address": "99", "opted_in": True},
    )
    await make_conv(auth_client)
    t = (await deliveries(auth_client, channel="telegram"))[0]
    assert t["status"] == "failed" and "not configured" in t["error"]


async def test_telegram_link_and_send(auth_client, client, http):
    link = (await auth_client.post(f"{P}/notifications/channels/telegram/link")).json()
    r = await client.post(
        f"{P}/webhooks/telegram",
        json={"message": {"text": f"/start {link['code']}", "chat": {"id": 4242}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "bad"},
    )
    assert r.status_code == 403
    r = await client.post(
        f"{P}/webhooks/telegram",
        json={"message": {"text": f"/start {link['code']}", "chat": {"id": 4242}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "tgsecret"},
    )
    assert r.status_code == 200
    chans = {c["channel"]: c for c in (await auth_client.get(f"{P}/notifications/channels")).json()}
    assert chans["telegram"]["address"] == "4242" and chans["telegram"]["opted_in"]
    await prefs(auth_client, {"new_message": {"telegram": {"enabled": True}}})
    await make_conv(auth_client)
    assert (await deliveries(auth_client, channel="telegram"))[0]["status"] == "sent"
    assert http.calls[-1][1]["json"]["chat_id"] == "4242"


async def test_quiet_hours_defer_but_high_priority_bypasses(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.models import Conversation

    await auth_client.patch(f"{P}/me", json={"timezone": "UTC"})
    now = datetime.now(UTC)
    start = (now - timedelta(hours=1)).strftime("%H:%M")
    end = (now + timedelta(hours=1)).strftime("%H:%M")
    await prefs(
        auth_client, {"new_message": {"email": {"enabled": True}}}, quiet_start=start, quiet_end=end
    )
    email_svc.OUTBOX.clear()
    await make_conv(auth_client, name="Regular")
    d = (await deliveries(auth_client, channel="email"))[0]
    assert d["status"] == "pending" and d["next_attempt_at"] and not email_svc.OUTBOX
    # VIP client bypasses quiet hours
    vip = (await auth_client.post(f"{P}/clients", json={"name": "Whale", "vip": True})).json()
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={"platform": "direct", "subject": "V", "client_id": vip["id"]},
        )
    ).json()
    async for db in app.dependency_overrides[get_db]():
        from app.services import inbox

        await inbox.add_inbound(db, await db.get(Conversation, uuid.UUID(conv["id"])), "urgent!")
        await db.commit()
    assert email_svc.OUTBOX and "urgent" in email_svc.OUTBOX[-1]["body"]
    # once quiet hours end, the deferred one is delivered
    from app.services.notifications import process_due

    async for db in app.dependency_overrides[get_db]():
        assert await process_due(db, now + timedelta(hours=2)) >= 1
        await db.commit()
    assert all(x["status"] == "sent" for x in await deliveries(auth_client, channel="email"))


async def test_digest_mode_batches_then_flushes(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.services.notifications import flush_digests

    await prefs(auth_client, {"new_message": {"email": {"enabled": True, "mode": "hourly"}}})
    email_svc.OUTBOX.clear()
    await make_conv(auth_client, name="A")
    await make_conv(auth_client, name="B")
    assert not email_svc.OUTBOX
    assert [d["status"] for d in await deliveries(auth_client, channel="email")] == [
        "digest",
        "digest",
    ]
    async for db in app.dependency_overrides[get_db]():
        assert await flush_digests(db) == 1
        await db.commit()
    assert len(email_svc.OUTBOX) == 1 and "2 update" in email_svc.OUTBOX[0]["subject"]
    assert {d["status"] for d in await deliveries(auth_client, channel="email")} == {"sent"}

    # daily digests only go out at the user's digest hour
    await prefs(
        auth_client, {"new_message": {"email": {"enabled": True, "mode": "daily"}}}, digest_hour=8
    )
    await make_conv(auth_client, name="C")
    async for db in app.dependency_overrides[get_db]():
        off = datetime.now(UTC).replace(hour=3, minute=0)
        assert await flush_digests(db, off) == 0
        on = datetime.now(UTC).replace(hour=8, minute=5)
        assert await flush_digests(db, on) == 1
        await db.commit()


async def test_push_devices_expo_and_webpush(auth_client, http):
    await prefs(auth_client, {"new_message": {"push": {"enabled": True}}})
    await make_conv(auth_client)
    assert (await deliveries(auth_client, channel="push"))[0][
        "status"
    ] == "skipped"  # no device yet
    assert (
        await auth_client.post(
            f"{P}/notifications/devices", json={"kind": "webpush", "token": "not-json"}
        )
    ).status_code == 422
    dev = (
        await auth_client.post(
            f"{P}/notifications/devices",
            json={"kind": "expo", "token": "ExponentPushToken[abc]", "label": "Pixel"},
        )
    ).json()
    again = (
        await auth_client.post(
            f"{P}/notifications/devices", json={"kind": "expo", "token": "ExponentPushToken[abc]"}
        )
    ).json()
    assert again["id"] == dev["id"]
    await make_conv(auth_client, name="Z")
    assert (await deliveries(auth_client, channel="push"))[0]["status"] == "sent"
    url, kw = http.calls[-1]
    assert "exp.host" in url and kw["json"][0]["to"] == "ExponentPushToken[abc]"
    assert len((await auth_client.get(f"{P}/notifications/devices")).json()) == 1
    await auth_client.delete(f"{P}/notifications/devices/{dev['id']}")
    assert (await auth_client.get(f"{P}/notifications/devices")).json() == []
    assert (await auth_client.get(f"{P}/notifications/vapid-key")).json() == {"public_key": ""}


async def test_webpush_without_library_or_config(auth_client, monkeypatch):
    sub = json.dumps({"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}})
    await auth_client.post(f"{P}/notifications/devices", json={"kind": "webpush", "token": sub})
    await prefs(auth_client, {"new_message": {"push": {"enabled": True}}})
    await make_conv(auth_client)
    d = (await deliveries(auth_client, channel="push"))[0]
    assert d["status"] in ("failed", "skipped") and d["error"]
    with pytest.raises(ch.ChannelError):
        await ch.WebPushChannel().send([sub], ch.Message("t", "b"))


async def test_test_notification_endpoint(auth_client):
    assert (await auth_client.post(f"{P}/notifications/test")).json()["status"] == "sent"
    assert (await auth_client.post(f"{P}/notifications/test", params={"channel": "email"})).json()[
        "status"
    ] == "sent"
    assert (
        await auth_client.post(f"{P}/notifications/test", params={"channel": "whatsapp"})
    ).status_code == 409
    assert (
        await auth_client.post(f"{P}/notifications/test", params={"channel": "pigeon"})
    ).status_code == 422


async def test_sync_failure_and_low_credit_notifications(auth_client, monkeypatch):
    acc = (
        await auth_client.post(f"{P}/platforms/accounts", json={"platform": "freelancer"})
    ).json()
    await auth_client.put(f"{P}/platforms/accounts/{acc['id']}/token", json={"access_token": "t"})

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def get(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr(httpx, "AsyncClient", Boom)
    await auth_client.post(f"{P}/platforms/accounts/{acc['id']}/sync")
    await auth_client.post(f"{P}/platforms/accounts/{acc['id']}/sync")  # same day => deduped
    r = await auth_client.post(f"{P}/platforms/accounts/{acc['id']}/credits", json={"delta": 5})
    assert r.json()["low"] is True
    types = [n["type"] for n in (await auth_client.get(f"{P}/notifications")).json()["items"]]
    assert types.count("sync_failure") == 1 and types.count("low_credits") == 1


async def test_scan_reminders_followup_and_sla(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.models import Conversation
    from app.services.notifications import scan_reminders

    job = (
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": "J", "external_id": "z"}
        )
    ).json()
    p = (await auth_client.post(f"{P}/proposals", json={"job_id": job["id"]})).json()
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "hi"})
    await auth_client.post(f"{P}/proposals/{p['id']}/approve")
    await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
    await auth_client.patch(
        f"{P}/proposals/{p['id']}",
        json={"follow_up_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    c = await make_conv(auth_client)
    async for db in app.dependency_overrides[get_db]():
        conv = await db.get(Conversation, uuid.UUID(c["id"]))
        conv.awaiting_reply_since = datetime.now(UTC) - timedelta(minutes=45)
        await db.commit()
        assert await scan_reminders(db) == 2
        assert await scan_reminders(db) == 0  # idempotent
        await db.commit()
    items = (await auth_client.get(f"{P}/notifications")).json()["items"]
    assert {"follow_up_due", "sla_breach"} <= {i["type"] for i in items}
    assert next(i for i in items if i["type"] == "sla_breach")["priority"] == "high"


# ---------------- WhatsApp webhook ----------------
def sign(body: bytes, secret="appsecret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def wa_payload(text, sender="447700900123", context_id=None):
    m = {"from": sender, "id": "wamid.in", "type": "text", "text": {"body": text}}
    if context_id:
        m["context"] = {"id": context_id}
    return {"entry": [{"changes": [{"value": {"messages": [m]}}]}]}


async def post_wa(client, payload, secret="appsecret"):
    raw = json.dumps(payload).encode()
    return await client.post(
        f"{P}/webhooks/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": sign(raw, secret), "Content-Type": "application/json"},
    )


async def test_whatsapp_verify_and_signature(client, http):
    ok = await client.get(
        f"{P}/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"
    assert (
        await client.get(
            f"{P}/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"},
        )
    ).status_code == 403
    assert (await post_wa(client, wa_payload("hi"), secret="wrong")).status_code == 403
    assert (await post_wa(client, wa_payload("hi"))).status_code == 200


async def test_whatsapp_not_configured_rejects(client, monkeypatch):
    assert (await client.post(f"{P}/webhooks/whatsapp", json={})).status_code == 503
    assert (await client.post(f"{P}/webhooks/telegram", json={})).status_code == 503


async def test_whatsapp_reply_routes_to_thread_and_opt_out(auth_client, client, http):
    await prefs(auth_client, {"new_message": {"whatsapp": {"enabled": True}}})
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "whatsapp", "address": "+447700900123", "opted_in": True},
    )
    # a Fiverr-style thread (no send API) so the reply must stay for manual paste
    await auth_client.post(f"{P}/platforms/accounts", json={"platform": "fiverr"})
    conv = (
        await auth_client.post(
            f"{P}/conversations",
            json={
                "platform": "fiverr",
                "subject": "Logo",
                "client_name": "Sam",
                "body": "need logo",
            },
        )
    ).json()
    wa_id = (await deliveries(auth_client, channel="whatsapp"))[0]
    assert wa_id["status"] == "sent"

    # reply via WhatsApp "reply-to" context (provider id returned by the Cloud API)
    r = await post_wa(client, wa_payload("Sure, 2 days!", context_id="wamid.1"))
    assert r.status_code == 200
    msgs = (await auth_client.get(f"{P}/conversations/{conv['id']}/messages")).json()
    out = [m for m in msgs if m["direction"] == "out"]
    assert out and out[0]["body"] == "Sure, 2 days!" and out[0]["delivery"] == "pending_manual"

    # reply with the short code instead of context
    code = http.calls[-1][1]["json"]["template"]["components"][0]["parameters"][2]["text"]
    await post_wa(client, wa_payload(f"#{code} Also include source files"))
    msgs = (await auth_client.get(f"{P}/conversations/{conv['id']}/messages")).json()
    assert any(m["body"] == "Also include source files" for m in msgs)

    # unroutable text => user told how to reply; unknown senders ignored
    before = (await auth_client.get(f"{P}/notifications")).json()["unread"]
    await post_wa(client, wa_payload("random words with no context"))
    assert (await auth_client.get(f"{P}/notifications")).json()["unread"] == before + 1
    await post_wa(client, wa_payload("hello", sender="19998887777"))

    # STOP opts out; further WhatsApp notifications are skipped
    await post_wa(client, wa_payload("STOP"))
    chans = {c["channel"]: c for c in (await auth_client.get(f"{P}/notifications/channels")).json()}
    assert chans["whatsapp"]["opted_in"] is False
    await make_conv(auth_client, name="After stop")
    assert (await deliveries(auth_client, channel="whatsapp"))[0]["status"] == "skipped"
    await post_wa(client, wa_payload("START"))
    assert {c["channel"]: c for c in (await auth_client.get(f"{P}/notifications/channels")).json()}[
        "whatsapp"
    ]["opted_in"] is True


async def test_whatsapp_status_failed_triggers_fallback(auth_client, client, http):
    await prefs(auth_client, {"new_message": {"whatsapp": {"enabled": True}}})
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "whatsapp", "address": "+447700900123", "opted_in": True},
    )
    email_svc.OUTBOX.clear()
    await make_conv(auth_client)
    payload = {
        "entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.1", "status": "failed"}]}}]}]
    }
    assert (await post_wa(client, payload)).status_code == 200
    assert (await deliveries(auth_client, channel="whatsapp"))[0]["status"] == "failed"
    assert email_svc.OUTBOX


async def test_notifications_are_tenant_isolated(auth_client, client):
    await make_conv(auth_client)
    nid = (await auth_client.get(f"{P}/notifications")).json()["items"][0]["id"]
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "o@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.post(f"{P}/notifications/{nid}/read")).status_code == 404
    assert (await client.get(f"{P}/notifications")).json()["items"] == []
    assert await deliveries(client) == []
