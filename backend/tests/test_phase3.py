import httpx

from app.services.email_parser import classify, parse_email, platform_for
from app.services.matching import suggest_bid
from app.services.proposals import price_band, render

P = "/api/v1"

MASTER = {
    "name": "Ann Lee", "headline": "Python dev", "bio": "x", "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "hourly_rate": 50,
}  # fmt: skip
JOB = {
    "platform": "upwork", "title": "Build a FastAPI backend", "external_id": "u1",
    "description": "Need Python and PostgreSQL expert. Docker a plus.", "budget_min": 500, "budget_max": 1500,
    "skills": ["Python", "FastAPI"], "client": {"name": "Bob Smith", "verified": True}, "url": "https://upwork.com/jobs/u1",
}  # fmt: skip


async def mk_job(c, **kw):
    r = await c.post(f"{P}/jobs", json={**JOB, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_job_scoring_dedupe_and_filters(auth_client):
    await auth_client.put(f"{P}/profile/master", json=MASTER)
    good = await mk_job(auth_client)
    assert good["score"] >= 70 and any("Skills match" in r for r in good["score_reasons"])
    bad = await mk_job(
        auth_client,
        external_id="u2",
        title="Logo design",
        description="Photoshop",
        skills=["Photoshop"],
        budget_max=20,
    )
    assert bad["score"] < 30
    again = await mk_job(auth_client, title="Build a FastAPI backend v2")
    assert again["id"] == good["id"] and again["title"].endswith("v2")  # upsert, not duplicate
    jobs = (await auth_client.get(f"{P}/jobs", params={"min_score": 50})).json()
    assert [j["id"] for j in jobs] == [good["id"]]
    assert len((await auth_client.get(f"{P}/jobs", params={"q": "logo"})).json()) == 1
    assert len((await auth_client.get(f"{P}/jobs", params={"platform": "fiverr"})).json()) == 0
    await auth_client.patch(f"{P}/jobs/{bad['id']}/dismiss")
    assert len((await auth_client.get(f"{P}/jobs")).json()) == 1
    assert len((await auth_client.get(f"{P}/jobs", params={"include_dismissed": True})).json()) == 2
    assert (await auth_client.post(f"{P}/jobs/rescore")).status_code == 200
    assert (await auth_client.get(f"{P}/jobs/{good['id']}")).status_code == 200
    assert (await auth_client.delete(f"{P}/jobs/{bad['id']}")).status_code == 200


async def test_saved_search_alerts(auth_client):
    await auth_client.put(f"{P}/profile/master", json=MASTER)
    s = (
        await auth_client.post(
            f"{P}/searches",
            json={"name": "API work", "keywords": ["fastapi"], "alert_min_score": 60},
        )
    ).json()
    await mk_job(auth_client)
    await mk_job(
        auth_client, external_id="x", title="Wordpress site", description="php", skills=["PHP"]
    )
    ev = (await auth_client.get(f"{P}/events", params={"kind": "job_match"})).json()
    assert len(ev) == 1 and "API work" in ev[0]["summary"]
    s["name"] = "Renamed"
    assert (await auth_client.put(f"{P}/searches/{s['id']}", json=s)).json()["name"] == "Renamed"
    assert len((await auth_client.get(f"{P}/searches")).json()) == 1
    assert (await auth_client.delete(f"{P}/searches/{s['id']}")).status_code == 200


async def test_bid_suggestion(auth_client):
    await auth_client.put(f"{P}/profile/master", json=MASTER)
    j = await mk_job(auth_client)
    assert (await auth_client.get(f"{P}/jobs/{j['id']}/bid-suggestion")).json()["amount"] == 1250.0
    h = await mk_job(
        auth_client, external_id="h", budget_type="hourly", budget_min=30, budget_max=40
    )
    assert (await auth_client.get(f"{P}/jobs/{h['id']}/bid-suggestion")).json()["amount"] == 40


def test_suggest_bid_without_budget():
    from app.models import Job

    assert suggest_bid(Job(title="t", budget_type="fixed"), None)["amount"] is None


def test_template_render_and_price_band():
    assert render("Hi {client_name}, {unknown}", {"client_name": "Bob"}) == "Hi Bob, {unknown}"
    assert price_band(None) == "unknown" and price_band(30) == "<$50" and price_band(5000) == "$1k+"


async def test_proposal_flow_requires_approval_and_manual_fallback(auth_client):
    await auth_client.put(f"{P}/profile/master", json=MASTER)
    acc = (await auth_client.post(f"{P}/platforms/accounts", json={"platform": "upwork"})).json()
    await auth_client.post(
        f"{P}/platforms/accounts/{acc['id']}/credits", json={"delta": 20, "note": "bought"}
    )
    job = await mk_job(auth_client)
    tpl = (
        await auth_client.post(
            f"{P}/proposal-templates",
            json={
                "name": "API",
                "body": "Hi {client_name}, I match on {skill_match}. -{my_name} {oops}",
            },
        )
    ).json()
    sl = (await auth_client.post(f"{P}/jobs/{job['id']}/shortlist")).json()
    assert sl["stage"] == "shortlisted"
    assert (await auth_client.post(f"{P}/jobs/{job['id']}/shortlist")).json()["proposal_id"] == sl[
        "proposal_id"
    ]
    pid = sl["proposal_id"]

    r = await auth_client.post(f"{P}/proposals/{pid}/draft", json={"template_id": tpl["id"]})
    p = r.json()
    assert (
        p["stage"] == "drafted"
        and "Hi Bob," in p["body"]
        and "Python" in p["body"]
        and p["unresolved_variables"] == ["oops"]
    )

    # cannot approve with unresolved variables, cannot submit unapproved
    assert (await auth_client.post(f"{P}/proposals/{pid}/approve")).status_code == 422
    assert (await auth_client.post(f"{P}/proposals/{pid}/submit")).status_code == 409
    assert (await auth_client.post(f"{P}/proposals/{pid}/mark-submitted")).status_code == 409
    assert (
        await auth_client.patch(f"{P}/proposals/{pid}/move", json={"stage": "submitted"})
    ).status_code == 409

    await auth_client.patch(
        f"{P}/proposals/{pid}",
        json={
            "body": "Hi Bob, I match.",
            "account_id": acc["id"],
            "credits_used": 4,
            "bid_amount": 900,
        },
    )
    assert (await auth_client.post(f"{P}/proposals/{pid}/approve")).json()["approved_at"]
    # editing after approval revokes approval
    after = (
        await auth_client.patch(f"{P}/proposals/{pid}", json={"body": "Hi Bob, edited."})
    ).json()
    assert after["approved_at"] is None
    await auth_client.post(f"{P}/proposals/{pid}/approve")

    # upwork API token missing => manual assisted flow, not an automated bid
    sub = (await auth_client.post(f"{P}/proposals/{pid}/submit")).json()
    assert (
        sub["submitted"] is False
        and sub["via"] == "manual"
        and sub["open_url"].startswith("https://upwork.com")
    )
    done = (await auth_client.post(f"{P}/proposals/{pid}/mark-submitted")).json()
    assert (
        done["stage"] == "submitted" and done["submitted_via"] == "manual" and done["follow_up_at"]
    )
    assert (await auth_client.post(f"{P}/proposals/{pid}/mark-submitted")).status_code == 409
    credits = (await auth_client.get(f"{P}/platforms/accounts/{acc['id']}/credits")).json()
    assert credits["balance"] == 16


async def test_api_submission_when_supported(auth_client, monkeypatch):
    from app.adapters.registry import UpworkAdapter

    called = {}

    async def fake_submit(self, ctx, job_id, proposal):
        called.update(job_id=job_id, body=proposal["body"], token=ctx.access_token)
        return {}

    monkeypatch.setattr(UpworkAdapter, "submit_proposal", fake_submit)
    acc = (await auth_client.post(f"{P}/platforms/accounts", json={"platform": "upwork"})).json()
    await auth_client.put(f"{P}/platforms/accounts/{acc['id']}/token", json={"access_token": "tok"})
    job = await mk_job(auth_client)
    p = (
        await auth_client.post(
            f"{P}/proposals", json={"job_id": job["id"], "account_id": acc["id"]}
        )
    ).json()
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "Hello"})
    assert (await auth_client.post(f"{P}/proposals/{p['id']}/submit")).status_code == 409
    await auth_client.post(f"{P}/proposals/{p['id']}/approve")
    r = (await auth_client.post(f"{P}/proposals/{p['id']}/submit")).json()
    assert r == {"submitted": True, "via": "api"} and called == {
        "job_id": "u1",
        "body": "Hello",
        "token": "tok",
    }


async def test_ai_draft_is_labeled(auth_client, monkeypatch):
    from app.services import ai

    async def fake(system, prompt, max_tokens=800):
        return "AI proposal text"

    monkeypatch.setattr(ai, "complete", fake)
    job = await mk_job(auth_client)
    p = (
        await auth_client.post(f"{P}/proposals", json={"job_id": job["id"], "stage": "found"})
    ).json()
    r = (await auth_client.post(f"{P}/proposals/{p['id']}/draft", json={"use_ai": True})).json()
    assert r["ai_generated"] is True and r["approved_at"] is None and r["stage"] == "drafted"
    assert (await auth_client.post(f"{P}/proposals/{p['id']}/draft", json={})).status_code == 422


async def test_pipeline_board_loss_reason_followups_and_analytics(auth_client):
    tpl = (
        await auth_client.post(f"{P}/proposal-templates", json={"name": "T1", "body": "hi"})
    ).json()
    ids = []
    for i in range(3):
        j = await mk_job(
            auth_client, external_id=f"j{i}", platform="upwork" if i < 2 else "freelancer", url=""
        )
        p = (
            await auth_client.post(
                f"{P}/proposals", json={"job_id": j["id"], "template_id": tpl["id"]}
            )
        ).json()
        await auth_client.patch(
            f"{P}/proposals/{p['id']}", json={"body": "hello", "bid_amount": 100 * (i + 1)}
        )
        await auth_client.post(f"{P}/proposals/{p['id']}/approve")
        await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
        ids.append(p["id"])
    assert (
        await auth_client.patch(f"{P}/proposals/{ids[0]}/move", json={"stage": "lost"})
    ).status_code == 422
    assert (
        await auth_client.patch(
            f"{P}/proposals/{ids[0]}/move", json={"stage": "lost", "lost_reason": "Too pricey"}
        )
    ).json()["lost_reason"] == "Too pricey"
    await auth_client.patch(f"{P}/proposals/{ids[1]}/move", json={"stage": "interview"})
    await auth_client.patch(f"{P}/proposals/{ids[1]}/move", json={"stage": "won"})
    board = (await auth_client.get(f"{P}/pipeline")).json()
    assert [len(board[s]) for s in ("submitted", "lost", "won")] == [1, 1, 1]
    assert set(board) == {
        "found",
        "shortlisted",
        "drafted",
        "submitted",
        "viewed",
        "interview",
        "won",
        "lost",
    }

    # follow-up due
    from datetime import UTC, datetime, timedelta

    await auth_client.patch(
        f"{P}/proposals/{ids[2]}",
        json={"follow_up_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    )
    assert [f["id"] for f in (await auth_client.get(f"{P}/pipeline/follow-ups")).json()] == [ids[2]]

    a = (await auth_client.get(f"{P}/analytics/proposals")).json()
    assert a["submitted"] == 3 and a["won"] == 1 and abs(a["win_rate"] - 0.333) < 0.01
    up = next(x for x in a["by_platform"] if x["key"] == "upwork")
    assert up["submitted"] == 2 and up["won"] == 1
    assert a["by_template"][0]["key"] == "T1" and a["by_hour"] and a["by_price_band"]
    # wins feed back into scoring: platform bonus
    assert (await auth_client.delete(f"{P}/proposals/{ids[2]}")).status_code == 200
    assert (await auth_client.get(f"{P}/proposals/{ids[0]}")).status_code == 200


async def test_templates_crud(auth_client):
    t = (await auth_client.post(f"{P}/proposal-templates", json={"name": "A", "body": "b"})).json()
    assert (
        await auth_client.put(f"{P}/proposal-templates/{t['id']}", json={"name": "A2", "body": "b"})
    ).json()["name"] == "A2"
    assert len((await auth_client.get(f"{P}/proposal-templates")).json()) == 1
    await auth_client.delete(f"{P}/proposal-templates/{t['id']}")
    assert (await auth_client.get(f"{P}/proposal-templates")).json() == []


# ---------------- email ingestion ----------------
def test_email_parser_classification():
    assert platform_for("Fiverr <no-reply@e.fiverr.com>") == "fiverr"
    assert platform_for("x@evilfiverr.com") is None
    assert classify("You have a new message from Sam", "") == "message"
    assert classify("Congrats! New order #FO123ABC", "") == "order"
    assert classify("Hello", "Sam sent you a custom offer worth $200") == "offer"
    assert classify("Weekly newsletter", "tips and tricks") is None
    p = parse_email(
        "notifications@fiverr.com",
        "New order #FO9A8B7C from Sam Jones",
        "Order total $250.00 https://www.fiverr.com/orders/FO9A8B7C/activities https://www.fiverr.com/unsubscribe",
        "m1",
    )
    assert (
        p and p.kind == "order" and p.meta["order_id"] == "FO9A8B7C" and p.meta["amount"] == 250.0
    )
    assert (
        p.url == "https://www.fiverr.com/orders/FO9A8B7C/activities"
        and p.meta["counterparty"] == "Sam Jones"
    )
    assert parse_email("spam@random.com", "new order", "") is None


async def test_ingest_email_events_dedupe_stats_and_jobs(auth_client):
    acc = (await auth_client.post(f"{P}/platforms/accounts", json={"platform": "fiverr"})).json()
    msg = {
        "from": "notifications@fiverr.com",
        "subject": "You have a new message from Sam",
        "body": "Hi! https://www.fiverr.com/inbox/sam",
        "message_id": "m-1",
    }
    r = (await auth_client.post(f"{P}/ingest/email", json=msg)).json()
    assert r["kind"] == "message" and r["duplicate"] is False
    assert (await auth_client.post(f"{P}/ingest/email", json=msg)).json()["duplicate"] is True
    assert (
        await auth_client.post(f"{P}/ingest/email", json={"from": "a@b.com", "subject": "hi"})
    ).json() == {"ignored": True}
    accs = (await auth_client.get(f"{P}/platforms/accounts")).json()
    assert accs[0]["id"] == acc["id"] and accs[0]["stats"]["unread"] == 1

    inv = {
        "from": "no-reply@upwork.com",
        "subject": "Sam invited you to apply: Build a data pipeline",
        "body": "See https://www.upwork.com/jobs/~0123",
        "message_id": "m-2",
    }
    out = (await auth_client.post(f"{P}/ingest/email", json=inv)).json()
    assert out["kind"] == "job_invite" and out["job_id"]
    job = (await auth_client.get(f"{P}/jobs/{out['job_id']}")).json()
    assert job["source"] == "email" and job["url"] == "https://www.upwork.com/jobs/~0123"

    evs = (await auth_client.get(f"{P}/events", params={"platform": "fiverr"})).json()
    assert len(evs) == 1
    assert (await auth_client.post(f"{P}/events/{evs[0]['id']}/handled")).json()["handled"] is True


# ---------------- browser extension / API keys ----------------
async def test_api_key_capture_flow(auth_client, client):
    created = (await auth_client.post(f"{P}/api-keys", json={"name": "Chrome"})).json()
    key = created["key"]
    assert key.startswith("fmk_")
    listed = (await auth_client.get(f"{P}/api-keys")).json()
    assert listed[0]["prefix"] == key[:8] and "key" not in listed[0]

    auth_client.tokens_header = client.headers["Authorization"]
    del client.headers["Authorization"]  # extension: API key only
    cap = {
        "kind": "job",
        "platform": "upwork",
        "url": "https://www.upwork.com/jobs/~99",
        "title": "Scrape-free job",
        "description": "python",
    }
    assert (await client.post(f"{P}/ingest/capture", json=cap)).status_code == 401
    r = await client.post(f"{P}/ingest/capture", json=cap, headers={"X-API-Key": key})
    assert r.status_code == 200 and r.json()["source"] == "extension"
    # key scope is limited to ingest endpoints
    assert (await client.get(f"{P}/me", headers={"X-API-Key": key})).status_code == 401
    msg = {
        "kind": "message",
        "platform": "fiverr",
        "url": "https://www.fiverr.com/inbox/x",
        "title": "Msg",
        "description": "hello",
    }
    assert (await client.post(f"{P}/ingest/capture", json=msg, headers={"X-API-Key": key})).json()[
        "kind"
    ] == "message"
    assert (
        await client.post(
            f"{P}/ingest/capture", json={**cap, "platform": "nope"}, headers={"X-API-Key": key}
        )
    ).status_code == 422

    client.headers["Authorization"] = auth_client.tokens_header
    await auth_client.delete(f"{P}/api-keys/{created['id']}")
    del client.headers["Authorization"]
    assert (
        await client.post(f"{P}/ingest/capture", json=cap, headers={"X-API-Key": key})
    ).status_code == 401


# ---------------- gmail ----------------
async def test_gmail_oauth_and_poll(auth_client, monkeypatch):
    from app.core.config import get_settings

    assert (await auth_client.get(f"{P}/ingest/gmail/auth-url")).status_code == 501
    assert (await auth_client.post(f"{P}/ingest/gmail/poll")).status_code == 404
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "cid")
    monkeypatch.setattr(s, "google_client_secret", "sec")
    url = (await auth_client.get(f"{P}/ingest/gmail/auth-url")).json()["url"]
    assert "gmail.readonly" in url and "access_type=offline" in url

    class Resp:
        def __init__(self, status, data):
            self.status_code, self._d = status, data

        def json(self):
            return self._d

        def raise_for_status(self): ...

    class Fake:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def post(self, url, data=None):
            return Resp(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

        async def get(self, url, params=None):
            if url.endswith("/messages"):
                return Resp(200, {"messages": [{"id": "g1"}, {"id": "g2"}]})
            subj = "New order #AB12CD from Sam" if url.endswith("g1") else "Your weekly digest"
            return Resp(
                200,
                {
                    "snippet": "Order total $99",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Fiverr <noreply@fiverr.com>"},
                            {"name": "Subject", "value": subj},
                        ]
                    },
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    assert (
        await auth_client.post(f"{P}/ingest/gmail/connect", json={"code": "c"})
    ).status_code == 200
    assert (await auth_client.post(f"{P}/ingest/gmail/poll")).json() == {"seen": 2, "ingested": 1}
    assert (await auth_client.post(f"{P}/ingest/gmail/poll")).json() == {
        "seen": 2,
        "ingested": 0,
    }  # idempotent
