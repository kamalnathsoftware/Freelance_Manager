"""Project Finder: leads CRM, outreach goal/streak, follow-up reminders."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import NotificationEvent
from app.services.project_finder.outreach import _streaks, scan_followups

P = "/api/v1/project-finder"


def lead(**kw):
    return {
        "business_name": "Acme Dental",
        "email": "owner@acme-dental.com",
        "problem": "Booking form is broken",
        **kw,
    }


async def other_headers(client):
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_lead_crud(auth_client):
    r = await auth_client.post(
        f"{P}/leads", json=lead(website="acme.test", timezone="America/New_York", currency="usd")
    )
    assert r.status_code == 201
    L = r.json()
    assert L["status"] == "new" and L["website"] == "https://acme.test" and L["currency"] == "USD"

    assert (await auth_client.get(f"{P}/leads/{L['id']}")).json()["business_name"] == "Acme Dental"
    r = await auth_client.patch(
        f"{P}/leads/{L['id']}", json={"notes": "met at expo", "contact_name": None}
    )
    assert (
        r.json()["notes"] == "met at expo" and r.json()["contact_name"] == ""
    )  # null = leave as is
    assert len((await auth_client.get(f"{P}/leads?q=dental")).json()) == 1
    assert (await auth_client.get(f"{P}/leads?q=zzz")).json() == []
    assert (await auth_client.delete(f"{P}/leads/{L['id']}")).status_code == 200
    assert (await auth_client.get(f"{P}/leads/{L['id']}")).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"business_name": ""},
        {"website": "javascript:alert(1)"},
        {"linkedin_url": "ftp://x.test"},
        {"email": "not-an-email"},
        {"timezone": "Nowhere/Land"},
        {"currency": "DOLLARS"},
        {"status": "ghosted"},
    ],
)
async def test_lead_validation(auth_client, body):
    assert (await auth_client.post(f"{P}/leads", json=lead(**body))).status_code == 422


async def test_leads_are_isolated_between_users(auth_client, client):
    L = (await auth_client.post(f"{P}/leads", json=lead())).json()
    other = await other_headers(client)
    assert (await client.get(f"{P}/leads", headers=other)).json() == []
    assert (await client.get(f"{P}/leads/{L['id']}", headers=other)).status_code == 404
    assert (
        await client.patch(f"{P}/leads/{L['id']}", json={"notes": "x"}, headers=other)
    ).status_code == 404
    assert (await client.delete(f"{P}/leads/{L['id']}", headers=other)).status_code == 404
    assert (
        await client.post(f"{P}/outreach/log", json={"lead_id": L["id"]}, headers=other)
    ).status_code == 404


async def test_first_contact_logs_outreach_and_schedules_followup(auth_client):
    L = (await auth_client.post(f"{P}/leads", json=lead())).json()
    r = await auth_client.patch(f"{P}/leads/{L['id']}", json={"status": "contacted"})
    body = r.json()
    assert body["status"] == "contacted" and body["last_contacted_at"]
    assert body["next_follow_up"] == str(
        datetime.now(UTC).date() + timedelta(days=3)
    )  # user tz defaults to UTC
    assert (await auth_client.get(f"{P}/outreach/goal")).json()["today"] == 1

    # moving around and back does not count a second message
    await auth_client.patch(f"{P}/leads/{L['id']}", json={"status": "replied"})
    await auth_client.patch(f"{P}/leads/{L['id']}", json={"status": "contacted"})
    assert (await auth_client.get(f"{P}/outreach/goal")).json()["today"] == 1


async def test_chosen_followup_is_kept_and_closing_clears_it(auth_client):
    day = str(datetime.now(UTC).date() + timedelta(days=10))
    L = (await auth_client.post(f"{P}/leads", json=lead())).json()
    r = await auth_client.patch(
        f"{P}/leads/{L['id']}", json={"status": "contacted", "next_follow_up": day}
    )
    assert r.json()["next_follow_up"] == day
    r = await auth_client.patch(f"{P}/leads/{L['id']}", json={"status": "won"})
    assert r.json()["next_follow_up"] is None and r.json()["follow_up_due"] is False


async def test_due_filter(auth_client):
    past = str(datetime.now(UTC).date() - timedelta(days=1))
    future = str(datetime.now(UTC).date() + timedelta(days=5))
    a = (
        await auth_client.post(f"{P}/leads", json=lead(business_name="Due", next_follow_up=past))
    ).json()
    await auth_client.post(f"{P}/leads", json=lead(business_name="Later", next_follow_up=future))
    due = (await auth_client.get(f"{P}/leads?due=true")).json()
    assert [d["id"] for d in due] == [a["id"]] and due[0]["follow_up_due"] is True


async def test_goal_log_undo_and_validation(auth_client):
    await auth_client.put(f"{P}/settings", json={"daily_goal": 2})
    g = (await auth_client.post(f"{P}/outreach/log", json={"channel": "linkedin"})).json()
    assert (g["today"], g["remaining"], g["goal_met"], g["streak"]) == (1, 1, False, 0)
    g = (await auth_client.post(f"{P}/outreach/log", json={})).json()
    assert g["goal_met"] is True and g["streak"] == 1 and g["days"][-1]["met"] is True
    assert len(g["days"]) == 14
    g = (await auth_client.delete(f"{P}/outreach/log/latest")).json()
    assert g["today"] == 1 and g["streak"] == 0
    await auth_client.delete(f"{P}/outreach/log/latest")
    assert (await auth_client.delete(f"{P}/outreach/log/latest")).status_code == 404
    assert (
        await auth_client.post(f"{P}/outreach/log", json={"channel": "pigeon"})
    ).status_code == 422


async def test_logging_against_new_lead_marks_it_contacted(auth_client):
    L = (await auth_client.post(f"{P}/leads", json=lead())).json()
    await auth_client.post(f"{P}/outreach/log", json={"lead_id": L["id"], "channel": "email"})
    got = (await auth_client.get(f"{P}/leads/{L['id']}")).json()
    assert got["status"] == "contacted" and got["next_follow_up"]
    assert (await auth_client.get(f"{P}/outreach/goal")).json()[
        "today"
    ] == 1  # logged once, not twice


def test_streak_math():
    t = date(2026, 3, 10)
    d = lambda *offs: {t - timedelta(days=o) for o in offs}  # noqa: E731
    assert _streaks(d(0, 1, 2), t) == (3, 3)
    assert _streaks(d(1, 2), t) == (2, 2)  # today not done yet: streak still alive
    assert _streaks(d(2, 3), t) == (0, 2)  # missed yesterday: broken
    assert _streaks(d(0, 1, 5, 6, 7, 8), t) == (2, 4)  # best run in the past
    assert _streaks(set(), t) == (0, 0)


async def test_followup_scan_notifies_once(auth_client):
    past = str(datetime.now(UTC).date() - timedelta(days=1))
    L = (await auth_client.post(f"{P}/leads", json=lead(next_follow_up=past))).json()
    closed = (
        await auth_client.post(f"{P}/leads", json=lead(business_name="Done", next_follow_up=past))
    ).json()
    await auth_client.patch(f"{P}/leads/{closed['id']}", json={"status": "lost"})

    from app.core.db import get_db
    from app.main import app as fastapi_app

    async for db in fastapi_app.dependency_overrides[get_db]():
        assert await scan_followups(db, datetime.now(UTC)) == 1
        assert await scan_followups(db, datetime.now(UTC)) == 0  # deduplicated
        await db.commit()
        evs = (await db.execute(select(NotificationEvent))).scalars().all()
        assert [e.type for e in evs] == ["follow_up_due"]
        assert L["id"] in evs[0].url
