import pytest

from app.adapters.base import AdapterContext, Capability, NotConfiguredError, NotSupportedError
from app.adapters.registry import ADAPTERS, FreelancerAdapter, UpworkAdapter, get_adapter
from app.services.profiles import fit

P = "/api/v1"


async def add_account(c, platform="fiverr", **kw):
    r = await c.post(f"{P}/platforms/accounts", json={"platform": platform, **kw})
    assert r.status_code == 201, r.text
    return r.json()


MASTER = {
    "name": "Ann", "headline": "Senior Python developer building APIs " * 3,
    "bio": "I build things. " * 40, "skills": [f"skill{i}" for i in range(30)],
    "hourly_rate": 50, "languages": ["en"], "location": "Berlin", "timezone": "Europe/Berlin",
    "availability": "Full-time", "experience": [{"title": "Dev"}],
}  # fmt: skip


async def test_catalog_capabilities(auth_client):
    cat = {p["key"]: p for p in (await auth_client.get(f"{P}/platforms/catalog")).json()}
    assert set(cat) == set(ADAPTERS)
    assert "submit_proposal" in cat["upwork"]["capabilities"]
    assert "submit_proposal" not in cat["fiverr"]["capabilities"]  # no ToS-violating bidding
    assert "send_message" not in cat["fiverr"]["capabilities"]


async def test_account_lifecycle_and_token_vault(auth_client):
    assert (
        await auth_client.post(f"{P}/platforms/accounts", json={"platform": "nope"})
    ).status_code == 422
    fiv = await add_account(auth_client, "fiverr", username="ann")
    assert fiv["integration_status"] == "Via email"
    # no API => cannot store tokens
    r = await auth_client.put(
        f"{P}/platforms/accounts/{fiv['id']}/token", json={"access_token": "x"}
    )
    assert r.status_code == 400
    up = await add_account(auth_client, "upwork")
    assert up["integration_status"] == "Manual"
    r = await auth_client.put(
        f"{P}/platforms/accounts/{up['id']}/token", json={"access_token": "secret-token"}
    )
    assert r.json()["integration_status"] == "Connected via API"

    from sqlalchemy import select

    from app.core.db import get_db
    from app.main import app
    from app.models import IntegrationToken

    async for db in app.dependency_overrides[get_db]():
        tok = (await db.execute(select(IntegrationToken))).scalar_one()
        assert "secret-token" not in tok.access_token_enc

    # Upwork sync is pending API approval -> skipped, not a crash
    log = (await auth_client.post(f"{P}/platforms/accounts/{up['id']}/sync")).json()
    assert log["status"] == "skipped"
    log = (await auth_client.post(f"{P}/platforms/accounts/{fiv['id']}/sync")).json()
    assert log["status"] == "skipped"
    assert len((await auth_client.get(f"{P}/platforms/accounts/{up['id']}/logs")).json()) == 1

    r = await auth_client.patch(
        f"{P}/platforms/accounts/{fiv['id']}", json={"stats": {"unread": 3}}
    )
    assert r.json()["stats"] == {"unread": 3}
    assert (await auth_client.delete(f"{P}/platforms/accounts/{fiv['id']}")).status_code == 200
    assert len((await auth_client.get(f"{P}/platforms/accounts")).json()) == 1


async def test_tenant_isolation(auth_client, client):
    acc = await add_account(auth_client, "fiverr")
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "b@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.delete(f"{P}/platforms/accounts/{acc['id']}")).status_code == 404
    assert (await client.get(f"{P}/platforms/accounts")).json() == []


async def test_master_profile_derive_drift_completeness(auth_client):
    assert (await auth_client.get(f"{P}/profile/master")).json() is None
    assert (await auth_client.get(f"{P}/profile/completeness")).json()["score"] == 0
    acc = await add_account(auth_client, "upwork")
    assert (await auth_client.post(f"{P}/profile/platforms/{acc['id']}/derive")).status_code == 409

    assert (await auth_client.put(f"{P}/profile/master", json=MASTER)).status_code == 200
    pp = (await auth_client.post(f"{P}/profile/platforms/{acc['id']}/derive")).json()
    assert len(pp["headline"]) <= 70 and pp["sync_status"] == "in_sync"
    assert len(pp["skills"]) == 15 and pp["violations"] == []

    await auth_client.put(f"{P}/profile/master", json={**MASTER, "bio": "changed " * 50})
    d = (await auth_client.get(f"{P}/profile/platforms/{acc['id']}/diff")).json()
    assert d["sync_status"] == "drifted"
    assert any(f["field"] == "bio" and not f["same"] for f in d["fields"])

    r = await auth_client.patch(f"{P}/profile/platforms/{acc['id']}", json={"headline": "x" * 200})
    assert r.json()["violations"]
    comp = (
        await auth_client.get(f"{P}/profile/completeness", params={"platform": "upwork"})
    ).json()
    assert comp["score"] > 50 and comp["checklist"]
    assert len((await auth_client.get(f"{P}/profile/platforms")).json()) == 1


async def test_contact_details_encrypted(auth_client):
    await auth_client.put(f"{P}/profile/contact", json={"address": "1 Main St"})
    assert (await auth_client.get(f"{P}/profile/contact")).json() == {"address": "1 Main St"}


async def test_portfolio_crud(auth_client):
    r = await auth_client.post(
        f"{P}/portfolio", json={"title": "Site", "kind": "link", "url": "https://x.y"}
    )
    pid = r.json()["id"]
    assert (
        await auth_client.post(f"{P}/portfolio", json={"title": "x", "kind": "bogus"})
    ).status_code == 422
    r = await auth_client.put(f"{P}/portfolio/{pid}", json={"title": "Site2"})
    assert r.json()["title"] == "Site2"
    assert len((await auth_client.get(f"{P}/portfolio")).json()) == 1
    await auth_client.delete(f"{P}/portfolio/{pid}")
    assert (await auth_client.get(f"{P}/portfolio")).json() == []


GIG = {
    "title": "I will build a fast REST API with FastAPI and PostgreSQL for your startup product",
    "category": "Programming", "tags": ["python", "api", "fastapi", "postgres", "docker", "extra"],
    "description": "Detailed description. " * 20, "faq": [{"q": "Q", "a": "A"}], "gallery": ["https://i/1.png"],
    "packages": [
        {"tier": "basic", "name": "Basic", "price": 100, "delivery_days": 3},
        {"tier": "premium", "name": "Pro", "price": 500, "delivery_days": 10},
    ],
}  # fmt: skip


async def test_gig_clone_export_checklist_performance(auth_client):
    g = (await auth_client.post(f"{P}/gigs", json=GIG)).json()
    assert len(g["packages"]) == 2
    fiverr = await add_account(auth_client, "fiverr", username="ann")
    upwork = await add_account(auth_client, "upwork")

    assert (
        await auth_client.post(f"{P}/gigs/{g['id']}/clone", json={"account_ids": [upwork["id"]]})
    ).status_code == 422
    r = await auth_client.post(f"{P}/gigs/{g['id']}/clone", json={"account_ids": [fiverr["id"]]})
    li = r.json()[0]
    assert len(li["overrides"]["title"]) <= 80 and len(li["overrides"]["tags"]) == 5
    # idempotent
    again = (
        await auth_client.post(f"{P}/gigs/{g['id']}/clone", json={"account_ids": [fiverr["id"]]})
    ).json()
    assert again[0]["id"] == li["id"]

    ex = (await auth_client.get(f"{P}/gigs/{g['id']}/listings/{li['id']}/export")).json()
    assert [f["field"] for f in ex["fields"]] == ["title", "description", "tags"]
    assert not any(f["over_limit"] for f in ex["fields"])
    assert ex["packages"][0]["tier"] == "basic" and "fiverr.com" in ex["open_on_platform"]

    ck = (await auth_client.get(f"{P}/gigs/{g['id']}/listings/{li['id']}/checklist")).json()
    assert ck["ready"] is True

    r = await auth_client.patch(
        f"{P}/gigs/{g['id']}/listings/{li['id']}",
        json={"status": "live", "metrics": {"impressions": 1000, "clicks": 100, "orders": 5}},
    )
    assert r.json()["status"] == "live"
    perf = (await auth_client.get(f"{P}/gigs/{g['id']}/performance")).json()["total"]
    assert perf["ctr"] == 0.1 and perf["conversion"] == 0.05

    r = await auth_client.put(f"{P}/gigs/{g['id']}", json={**GIG, "packages": [GIG["packages"][0]]})
    assert len(r.json()["packages"]) == 1
    assert len((await auth_client.get(f"{P}/gigs", params={"status": "draft"})).json()) == 1
    assert (await auth_client.delete(f"{P}/gigs/{g['id']}")).status_code == 200


async def test_gig_validation_and_missing(auth_client):
    bad = {**GIG, "packages": [{"tier": "gold"}]}
    assert (await auth_client.post(f"{P}/gigs", json=bad)).status_code == 422
    assert (
        await auth_client.get(f"{P}/gigs/00000000-0000-0000-0000-000000000000")
    ).status_code == 404


async def test_ai_rewrite(auth_client, monkeypatch):
    r = await auth_client.post(f"{P}/ai/rewrite", json={"kind": "bio", "text": "hello"})
    assert r.status_code == 503  # not configured

    from app.core.config import get_settings
    from app.services import ai

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "k")
    seen = {}

    async def fake(system, prompt, max_tokens=800):
        seen["prompt"] = prompt
        return "Rewritten " * 100

    monkeypatch.setattr(ai, "complete", fake)
    r = await auth_client.post(
        f"{P}/ai/rewrite",
        json={
            "kind": "headline",
            "text": "dev",
            "platform": "upwork",
            "tone": "confident",
            "keywords": ["python"],
        },
    )
    body = r.json()
    assert body["ai_generated"] and body["requires_approval"] and len(body["text"]) <= 70
    assert "python" in seen["prompt"] and "70" in seen["prompt"]
    r = await auth_client.post(
        f"{P}/ai/rewrite", json={"kind": "bio", "text": "x", "tone": "angry"}
    )
    assert r.status_code == 422

    async def kw(system, prompt, max_tokens=800):
        return "python, api , fastapi"

    monkeypatch.setattr(ai, "complete", kw)
    r = await auth_client.post(f"{P}/ai/keywords", json={"title": "API"})
    assert r.json() == ["python", "api", "fastapi"]


async def test_adapter_contracts(monkeypatch):
    fiverr = get_adapter("fiverr")
    with pytest.raises(NotSupportedError):
        await fiverr.send_message(AdapterContext("a"), "t", "hi")
    with pytest.raises(NotSupportedError):
        await fiverr.submit_proposal(AdapterContext("a"), "j", {})
    assert fiverr.deep_link("inbox").startswith("https://www.fiverr.com")
    assert Capability.sync_profile not in fiverr.capabilities()
    with pytest.raises(NotConfiguredError):
        await UpworkAdapter().sync_profile(AdapterContext("a"))
    with pytest.raises(NotConfiguredError):
        await FreelancerAdapter().sync_profile(AdapterContext("a"))
    with pytest.raises(KeyError):
        get_adapter("nope")


async def test_freelancer_sync_uses_api(auth_client, monkeypatch):
    import httpx

    class R:
        status_code = 200

        def raise_for_status(self): ...
        def json(self):
            return {"result": {"username": "annf", "tagline": "t", "profile_description": "d"}}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def get(self, url, headers=None):
            assert headers["freelancer-oauth-v1"] == "tok"
            return R()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    acc = await add_account(auth_client, "freelancer")
    await auth_client.put(f"{P}/platforms/accounts/{acc['id']}/token", json={"access_token": "tok"})
    log = (await auth_client.post(f"{P}/platforms/accounts/{acc['id']}/sync")).json()
    assert log["status"] == "ok"
    acc = (await auth_client.get(f"{P}/platforms/accounts")).json()[0]
    assert acc["username"] == "annf" and acc["last_synced_at"]


async def test_sync_error_is_recorded(auth_client, monkeypatch):
    import httpx

    class Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def get(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "AsyncClient", Boom)
    acc = await add_account(auth_client, "freelancer")
    await auth_client.put(f"{P}/platforms/accounts/{acc['id']}/token", json={"access_token": "tok"})
    log = (await auth_client.post(f"{P}/platforms/accounts/{acc['id']}/sync")).json()
    assert log["status"] == "error"
    a = (await auth_client.get(f"{P}/platforms/accounts")).json()[0]
    assert a["status"] == "error" and "network down" in a["last_error"]


def test_fit_truncates_on_word_boundary():
    assert fit("hello world foo", 12) == "hello world…"
    assert fit("short", 100) == "short"
    assert fit("anything", 0) == "anything"
