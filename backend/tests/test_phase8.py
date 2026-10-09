import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings

P = "/api/v1"


# ---------------- seed ----------------
async def seed_into_test_db():
    from app.core.db import get_db
    from app.main import app
    from app.seed import seed

    async for db in app.dependency_overrides[get_db]():
        user = await seed(db, "seed@example.com", "demo1234!")
        await db.commit()
        return user.id


async def login_seeded(client):
    await seed_into_test_db()
    r = await client.post(
        f"{P}/auth/login", json={"email": "seed@example.com", "password": "demo1234!"}
    )
    client.headers["Authorization"] = f"Bearer {r.json()['tokens']['access_token']}"


async def test_seed_populates_every_screen(client):
    await login_seeded(client)
    expect_nonempty = ["platforms/accounts", "gigs", "jobs", "pipeline", "conversations", "clients", "orders", "projects", "finance/invoices", "finance/expenses", "finance/payments",
                       "forms", "automations", "calendar", "proposal-templates", "portfolio", "canned-responses", "notifications", "searches"]  # fmt: skip
    for path in expect_nonempty:
        r = await client.get(f"{P}/{path}")
        body = r.json()
        data = body["items"] if isinstance(body, dict) and "items" in body else body
        if isinstance(data, dict):  # pipeline board
            assert any(data.values()), path
        else:
            assert len(data) > 0, path
    assert (await client.get(f"{P}/profile/master")).json()["name"] == "Alex Demo"
    ov = (
        await client.get(f"{P}/analytics/overview", params={"days": 180, "granularity": "month"})
    ).json()
    assert (
        ov["kpis"]["net_earnings"] > 0
        and ov["utilization"]["tracked_hours"] > 0
        and len(ov["earnings_series"]) >= 6
    )
    assert (await client.get(f"{P}/finance/summary")).json()["overdue_invoices"] == 1


async def test_seed_is_repeatable(client):
    await seed_into_test_db()
    await (
        seed_into_test_db()
    )  # second run replaces the first rather than failing on unique constraints
    r = await client.post(
        f"{P}/auth/login", json={"email": "seed@example.com", "password": "demo1234!"}
    )
    assert r.status_code == 200


# ---------------- analytics & goals ----------------
async def test_overview_validation_and_empty_state(auth_client):
    assert (await auth_client.get(f"{P}/analytics/overview", params={"days": 0})).status_code == 422
    assert (
        await auth_client.get(f"{P}/analytics/overview", params={"granularity": "hour"})
    ).status_code == 422
    ov = (await auth_client.get(f"{P}/analytics/overview")).json()
    assert (
        ov["kpis"]["net_earnings"] == 0
        and ov["kpis"]["change_pct"] is None
        and len(ov["earnings_series"]) == 30
    )
    assert [f["stage"] for f in ov["funnel"]][0] == "found" and ov["utilization"][
        "utilization_pct"
    ] == 0.0
    assert ov["response_times"] == [] and ov["top_clients"] == []


async def test_overview_earnings_conversion_change_and_granularity(auth_client):
    await auth_client.patch(f"{P}/me", json={"settings": {"fx": {"EUR": 2.0}}})
    today = datetime.now(UTC).date()
    await auth_client.post(
        f"{P}/finance/payments",
        json={
            "platform": "direct",
            "gross": 100,
            "fee": 0,
            "currency": "USD",
            "received_on": today.isoformat(),
        },
    )
    await auth_client.post(
        f"{P}/finance/payments",
        json={
            "platform": "direct",
            "gross": 50,
            "fee": 0,
            "currency": "EUR",
            "received_on": today.isoformat(),
        },
    )
    await auth_client.post(
        f"{P}/finance/payments",
        json={
            "platform": "upwork",
            "gross": 100,
            "currency": "USD",
            "received_on": (today - timedelta(days=40)).isoformat(),
        },
    )
    ov = (await auth_client.get(f"{P}/analytics/overview", params={"days": 30})).json()
    assert ov["kpis"]["net_earnings"] == 200  # 100 USD + 50 EUR * 2
    assert ov["kpis"]["previous_net_earnings"] == 90  # upwork 100 less 10% fee
    assert ov["kpis"]["change_pct"] == round((200 - 90) / 90 * 100, 1)
    assert ov["earnings_series"][-1]["net"] == 200 and ov["by_platform"][0]["key"] == "direct"
    weekly = (
        await auth_client.get(f"{P}/analytics/overview", params={"days": 60, "granularity": "week"})
    ).json()
    assert (
        all("-W" in p["key"] for p in weekly["earnings_series"])
        and round(sum(p["net"] for p in weekly["earnings_series"])) == 290
    )
    monthly = (
        await auth_client.get(
            f"{P}/analytics/overview", params={"days": 90, "granularity": "month"}
        )
    ).json()
    assert 3 <= len(monthly["earnings_series"]) <= 4


async def test_funnel_win_rates_utilization_and_deadlines(auth_client):
    async def proposal(i, stage, reason=""):
        j = (
            await auth_client.post(
                f"{P}/jobs", json={"platform": "upwork", "title": f"J{i}", "external_id": f"f{i}"}
            )
        ).json()
        p = (await auth_client.post(f"{P}/proposals", json={"job_id": j["id"]})).json()
        if stage in ("found", "shortlisted"):
            return
        await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "hi", "bid_amount": 300})
        await auth_client.post(f"{P}/proposals/{p['id']}/approve")
        await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
        if stage != "submitted":
            await auth_client.patch(
                f"{P}/proposals/{p['id']}/move", json={"stage": stage, "lost_reason": reason}
            )

    for i, (st, why) in enumerate(
        [("found", ""), ("submitted", ""), ("interview", ""), ("won", ""), ("lost", "price")]
    ):
        await proposal(i, st, why)
    p = (await auth_client.get(f"{P}/projects")).json()
    pr = (await auth_client.post(f"{P}/projects", json={"name": "P", "hourly_rate": 50})).json()
    await auth_client.post(
        f"{P}/time",
        json={
            "project_id": pr["id"],
            "started_at": (datetime.now(UTC) - timedelta(hours=5)).isoformat(),
            "minutes": 120,
        },
    )
    await auth_client.post(
        f"{P}/time",
        json={
            "project_id": pr["id"],
            "started_at": (datetime.now(UTC) - timedelta(hours=9)).isoformat(),
            "minutes": 60,
            "billable": False,
        },
    )
    await auth_client.post(
        f"{P}/orders",
        json={
            "platform": "fiverr",
            "title": "Due",
            "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    ov = (await auth_client.get(f"{P}/analytics/overview")).json()
    f = {x["stage"]: x["count"] for x in ov["funnel"]}
    assert (
        f["found"] == 5 and f["submitted"] == 4 and f["interview"] == 2 and f["won"] == 1
    )  # lost-after-submit counts as having been submitted
    assert (
        ov["kpis"]["proposals_submitted"] == 4
        and ov["kpis"]["win_rate"] == 0.25
        and ov["kpis"]["open_pipeline_value"] == 600
    )
    u = ov["utilization"]
    assert u["tracked_hours"] == 3.0 and u["billable_hours"] == 2.0 and u["billable_pct"] == 66.7
    assert (
        ov["upcoming_deadlines"][0]["title"] == "Due: Due"
        and ov["win_rate_by"]["platform"][0]["key"] == "upwork"
    )
    assert p == []


async def test_goals_progress_and_forecast(auth_client):
    g = (await auth_client.get(f"{P}/goals")).json()
    assert g["month"]["pct"] is None and g["month"]["status"] is None
    assert (await auth_client.put(f"{P}/goals", json={"monthly_income": -1})).status_code == 422
    assert (await auth_client.put(f"{P}/goals", json={"weekly_hours": 0})).status_code == 422
    # make "today" payments + an open order + an open bid, then set goals
    await auth_client.post(
        f"{P}/finance/payments", json={"platform": "direct", "gross": 1000, "fee": 0}
    )
    o = (
        await auth_client.post(
            f"{P}/orders", json={"platform": "upwork", "title": "Open", "amount": 1000}
        )
    ).json()
    await auth_client.post(f"{P}/orders/{o['id']}/milestones", json={"title": "M1", "amount": 400})
    j = (
        await auth_client.post(
            f"{P}/jobs", json={"platform": "upwork", "title": "Bid", "external_id": "b"}
        )
    ).json()
    p = (await auth_client.post(f"{P}/proposals", json={"job_id": j["id"]})).json()
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "x", "bid_amount": 1000})
    await auth_client.post(f"{P}/proposals/{p['id']}/approve")
    await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
    g = (
        await auth_client.put(
            f"{P}/goals", json={"monthly_income": 2000, "yearly_income": 24000, "weekly_hours": 30}
        )
    ).json()
    assert (
        g["month"]["earned"] == 1000
        and g["month"]["pct"] == 50.0
        and g["year"]["pct"] == round(1000 / 24000 * 100, 1)
    )
    assert g["month"]["status"] in ("ahead", "on_track", "behind")
    fc = g["forecast"]
    assert fc["committed_orders_net"] == 900  # 1000 gross - 10% upwork fee
    assert (
        fc["pipeline_weighted"] == 100.0
        and fc["assumptions"]["stage_win_probability"]["submitted"] == 0.1
        and "defaults" in fc["assumptions"]["stage_win_probability"]["source"]
    )
    assert fc["month_end_with_committed"] == 1900 and fc["month_end_with_pipeline"] == 2000
    assert (await auth_client.get(f"{P}/finance/summary")).json()[
        "monthly_income_goal"
    ] == 2000  # one source of truth
    assert g["goals"]["weekly_hours"] == 30


async def test_stage_probabilities_use_history_when_enough_data():
    from app.models import Proposal, Stage
    from app.services.analytics import stage_probabilities

    now = datetime.now(UTC)
    ps = [Proposal(stage=Stage.won, submitted_at=now) for _ in range(2)] + [
        Proposal(stage=Stage.lost, submitted_at=now) for _ in range(3)
    ]
    pr = stage_probabilities(ps)
    assert (
        pr["submitted"] == 0.4
        and pr["viewed"] == 0.64
        and pr["interview"] == 0.9
        and "your history" in pr["source"]
    )


async def test_report_pdf(auth_client):
    await auth_client.post(f"{P}/finance/payments", json={"platform": "fiverr", "gross": 200})
    r = await auth_client.get(f"{P}/analytics/report.pdf", params={"days": 90})
    assert (
        r.status_code == 200
        and r.content.startswith(b"%PDF")
        and r.headers["content-type"] == "application/pdf"
    )
    assert (
        await auth_client.get(f"{P}/analytics/report.pdf", params={"days": 999})
    ).status_code == 422


# ---------------- GDPR ----------------
async def test_export_contains_everything_and_no_secrets(client):
    await login_seeded(client)
    await client.put(f"{P}/profile/contact", json={"address": "1 Demo St"})
    acc = (await client.get(f"{P}/platforms/accounts")).json()
    up = next(a for a in acc if a["platform"] == "upwork")
    await client.put(
        f"{P}/platforms/accounts/{up['id']}/token", json={"access_token": "SUPER-SECRET-TOKEN"}
    )
    await client.post(f"{P}/me/2fa/setup")
    exp = await client.get(f"{P}/me/export")
    text = exp.text
    data = exp.json()
    for k in ("user", "master_profile", "platform_accounts", "gigs", "gig_packages", "jobs", "proposals", "clients", "conversations", "messages", "orders", "milestones", "projects", "tasks", "time_entries", "invoices", "expenses", "payments", "forms", "form_fields", "form_submissions", "automation_rules", "notifications", "calendar_events", "audit_log", "contact_details", "platform_profiles"):  # fmt: skip
        assert data[k], k
    assert data["contact_details"] == {"address": "1 Demo St"}
    for secret in (
        "SUPER-SECRET-TOKEN",
        "password_hash",
        "totp_secret",
        "access_token_enc",
        "key_hash",
    ):
        assert secret not in text
    assert data["user"]["email"] == "seed@example.com"


async def test_account_deletion_erases_all_rows_and_files(client):
    from sqlalchemy import text

    from app.core.db import Base, get_db
    from app.main import app

    await login_seeded(client)
    key = (await client.get(f"{P}/forms")).json()[0]["public_key"]
    up = await client.post(f"{P}/files", files={"file": ("a.pdf", b"%PDF-1", "application/pdf")})
    assert up.status_code == 201
    from app.models import UploadedFile

    async for db in app.dependency_overrides[get_db]():
        path = (await db.execute(select(UploadedFile.path))).scalars().first()
    assert os.path.exists(path)
    # a second user's data must survive
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "keep@example.com", "password": "password123"}
        )
    ).json()
    keep_h = {"Authorization": f"Bearer {other['access_token']}"}
    await client.post(f"{P}/clients", json={"name": "Keep me"}, headers=keep_h)
    assert key
    r = await client.request(
        "DELETE", f"{P}/me", json={"current_password": "demo1234!", "new_password": "unused-value"}
    )
    assert r.status_code == 200
    assert not os.path.exists(path)
    async for db in app.dependency_overrides[get_db]():
        leftovers = {}
        for t in Base.metadata.sorted_tables:
            if "user_id" in t.c:
                n = (
                    await db.execute(
                        text(f"SELECT COUNT(*) FROM {t.name} WHERE user_id IS NOT NULL")
                    )
                ).scalar_one()
                leftovers[t.name] = n
        assert leftovers["clients"] == 1  # only the other user's client
        for name, n in leftovers.items():
            if name not in ("clients", "audit_logs", "auth_sessions", "master_profiles") and n:
                pytest.fail(f"{name} still has {n} rows after account deletion")
        assert leftovers["master_profiles"] == 0
    assert (await client.get(f"{P}/clients", headers=keep_h)).json()[0]["name"] == "Keep me"


# ---------------- ops ----------------
async def test_ops_overview_is_admin_only(auth_client, monkeypatch):
    assert (await auth_client.get(f"{P}/ops/overview")).status_code == 403
    monkeypatch.setattr(get_settings(), "admin_emails", ["A@example.com"])
    ov = (await auth_client.get(f"{P}/ops/overview")).json()
    assert (
        ov["db_ok"] is True
        and ov["users"] >= 1
        and "deliveries" in ov["last_24h"]
        and "recent_failures" in ov
    )
    assert ov["celery"]["online"] == 0  # no broker in tests: reported, not crashed


async def test_ops_lists_recent_failures(auth_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ["a@example.com"])
    await auth_client.put(
        f"{P}/notifications/preferences",
        json={"matrix": {"new_message": {"telegram": {"enabled": True}}}},
    )
    await auth_client.put(
        f"{P}/notifications/channels",
        json={"channel": "telegram", "address": "1", "opted_in": True},
    )
    await auth_client.post(
        f"{P}/conversations",
        json={"platform": "direct", "subject": "s", "client_name": "c", "body": "b"},
    )
    ov = (await auth_client.get(f"{P}/ops/overview")).json()
    assert (
        ov["recent_failures"]["deliveries"]
        and ov["recent_failures"]["deliveries"][0]["channel"] == "telegram"
    )
    assert ov["last_24h"]["deliveries"].get("failed", 0) >= 1


async def test_gzip_compresses_large_responses(auth_client):
    for i in range(30):
        await auth_client.post(
            f"{P}/jobs",
            json={
                "platform": "upwork",
                "title": f"Job {i} " + "x" * 40,
                "external_id": f"g{i}",
                "description": "lorem ipsum " * 40,
            },
        )
    r = await auth_client.get(
        f"{P}/jobs", params={"limit": 100}, headers={"Accept-Encoding": "gzip"}
    )
    assert r.headers.get("content-encoding") == "gzip" and len(r.json()) == 30


def test_openapi_documents_all_routers():
    from app.main import app

    paths = app.openapi()["paths"]
    for p in (
        "/api/v1/team",
        "/api/v1/analytics/overview",
        "/api/v1/goals",
        "/api/v1/forms",
        "/api/v1/automations",
        "/api/v1/ops/overview",
        "/api/v1/webhooks/whatsapp",
        "/health",
    ):
        assert p in paths, p
    assert json.dumps(app.openapi())
