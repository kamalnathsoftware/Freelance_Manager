"""Project Finder: stats."""

from datetime import UTC, datetime, timedelta

from app.services.project_finder.stats import best_source, rate

P = "/api/v1/project-finder"


def today():
    return datetime.now(UTC).date()


async def prop(c, source, status="sent", amount=None, currency="USD", days_ago=0):
    r = await c.post(
        f"{P}/proposals",
        json={
            "title": f"{source}-{status}",
            "source": source,
            "status": status,
            "amount": amount,
            "currency": currency,
            "sent_on": str(today() - timedelta(days=days_ago)),
        },
    )
    assert r.status_code == 201, r.text


def test_rate_and_best_source_rules():
    assert rate(1, 3) == 0.3333 and rate(0, 0) is None
    row = lambda s, won, rep, sent: {"source": s, "won": won, "replied": rep, "sent": sent}  # noqa: E731
    assert best_source([]) is None
    assert best_source([row("A", 0, 0, 10)]) is None  # nothing has worked yet
    top = best_source([row("A", 1, 1, 1), row("B", 3, 5, 20), row("C", 3, 4, 5)])
    assert (
        top["source"] == "B" and top["reason"] == "3 wins from 20 proposals"
    )  # more wins, then more replies
    only_replies = best_source([row("A", 0, 2, 4), row("B", 0, 1, 1)])
    assert only_replies["source"] == "A" and "no wins yet" in only_replies["reason"]


async def test_empty_stats_are_safe(auth_client):
    s = (await auth_client.get(f"{P}/stats")).json()
    assert (
        s["proposals"]["sent"] == 0
        and s["proposals"]["reply_rate"] is None
        and s["proposals"]["win_rate"] is None
    )
    assert s["by_source"] == [] and s["best_source"] is None
    assert (
        s["leads"]["total"] == 0
        and s["leads"]["win_rate"] is None
        and set(s["leads"]["by_status"]) >= {"new", "won", "lost"}
    )
    assert s["outreach"] == {
        "last_7_days": 0,
        "last_30_days": 0,
        "today": 0,
        "goal": 5,
        "streak": 0,
        "best_streak": 0,
    }


async def test_rates_earnings_and_best_source(auth_client):
    # Reddit: 4 sent - 1 won (1000 USD), 1 interview, 1 lost, 1 no response
    await prop(auth_client, "Reddit", "won", 1000)
    await prop(auth_client, "Reddit", "interview", 400)
    await prop(auth_client, "Reddit", "lost", 300)
    await prop(auth_client, "Reddit", "no_response", 300)
    # LinkedIn: 2 sent, 0 replies, 1 won in EUR
    await prop(auth_client, "LinkedIn", "sent", 200)
    await prop(auth_client, "LinkedIn", "won", 700, "EUR")
    await prop(auth_client, "", "sent", None)  # no source recorded
    s = (await auth_client.get(f"{P}/stats")).json()
    p = s["proposals"]
    assert (p["sent"], p["won"], p["lost"], p["pending"]) == (7, 2, 1, 2)
    assert p["replied"] == 3  # Reddit won + interview, LinkedIn won (a win implies a reply)
    assert p["reply_rate"] == rate(3, 7) and p["win_rate"] == rate(2, 7)
    by = {r["source"]: r for r in s["by_source"]}
    assert set(by) == {"Reddit", "LinkedIn", "Unknown"}
    assert by["Reddit"]["earnings"] == {"USD": 1000.0} and by["LinkedIn"]["earnings"] == {
        "EUR": 700.0
    }
    assert by["Reddit"]["reply_rate"] == 0.5 and by["Reddit"]["win_rate"] == 0.25
    assert by["Unknown"]["win_rate"] == 0.0
    # tie on wins (1 each): Reddit has more replies
    assert (
        s["best_source"]["source"] == "Reddit"
        and "1 win from 4 proposals" == s["best_source"]["reason"]
    )
    assert "currency conversion" in s["earnings_basis"]


async def test_days_filter(auth_client):
    await prop(auth_client, "Old", "won", 100, days_ago=100)
    await prop(auth_client, "New", "sent", None, days_ago=2)
    assert (await auth_client.get(f"{P}/stats")).json()["proposals"]["sent"] == 2
    recent = (await auth_client.get(f"{P}/stats?days=30")).json()
    assert (
        recent["proposals"]["sent"] == 1
        and [r["source"] for r in recent["by_source"]] == ["New"]
        and recent["days"] == 30
    )
    assert (await auth_client.get(f"{P}/stats?days=0")).status_code == 422


async def test_leads_funnel_and_outreach(auth_client):
    a = (
        await auth_client.post(f"{P}/leads", json={"business_name": "A", "source": "Cold email"})
    ).json()
    b = (
        await auth_client.post(f"{P}/leads", json={"business_name": "B", "source": "Cold email"})
    ).json()
    await auth_client.post(
        f"{P}/leads",
        json={"business_name": "C", "next_follow_up": str(today() - timedelta(days=1))},
    )
    await auth_client.patch(f"{P}/leads/{a['id']}", json={"status": "contacted"})
    await auth_client.patch(f"{P}/leads/{b['id']}", json={"status": "won"})
    s = (await auth_client.get(f"{P}/stats")).json()
    assert (
        s["leads"]["total"] == 3
        and s["leads"]["by_status"]["new"] == 1
        and s["leads"]["by_status"]["won"] == 1
    )
    assert s["leads"]["follow_ups_due"] == 1 and s["leads"]["win_rate"] == rate(1, 3)
    cold = next(x for x in s["leads"]["by_source"] if x["source"] == "Cold email")
    assert cold == {"source": "Cold email", "leads": 2, "won": 1}
    assert (
        s["outreach"]["today"] == 1
        and s["outreach"]["last_7_days"] == 1
        and s["outreach"]["last_30_days"] == 1
    )


async def test_stats_are_per_user(auth_client, client):
    await prop(auth_client, "Reddit", "won", 50)
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"{P}/stats", headers=other)).json()["proposals"]["sent"] == 0
    assert (await auth_client.get(f"{P}/stats")).json()["proposals"][
        "sent"
    ] == 1  # the first user still sees theirs
