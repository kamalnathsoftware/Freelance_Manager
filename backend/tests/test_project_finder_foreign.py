"""Project Finder: foreign-client helper (time-zone overlap, invoices)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app.services.project_finder.tz import overlap, suggest_timezone

P = "/api/v1/project-finder"
IST = "Asia/Kolkata"


def ov(client_tz, d, **kw):
    return overlap(IST, client_tz, on=d, now=datetime(d.year, d.month, d.day, 12, tzinfo=UTC), **kw)


# ---------------------------------------------------------------- overlap maths (hand-checked vectors)
def test_london_winter_and_summer_shift_with_dst():
    w = ov("Europe/London", date(2026, 1, 15))
    assert (w["client_offset"], w["difference_hours"], w["overlap_hours"], w["rating"]) == (
        "+00:00",
        -5.5,
        3.5,
        "workable",
    )
    assert w["windows"] == [
        {"home_start": "14:30", "home_end": "18:00", "client_start": "09:00", "client_end": "12:30"}
    ]
    s = ov("Europe/London", date(2026, 7, 15))  # BST: London is an hour closer to India
    assert (s["client_offset"], s["difference_hours"], s["overlap_hours"], s["rating"]) == (
        "+01:00",
        -4.5,
        4.5,
        "good",
    )
    assert s["windows"][0]["home_start"] == "13:30"


def test_us_east_has_no_overlap_and_explains_their_day():
    w = ov("America/New_York", date(2026, 1, 15))
    assert w["overlap_hours"] == 0 and w["rating"] == "none" and w["windows"] == []
    assert w["client_day_in_home_time"] == "19:30-04:30 (next day)" and "19:30-04:30" in w["note"]
    assert ov("America/New_York", date(2026, 7, 15))["difference_hours"] == -9.5  # EDT
    assert ov("America/New_York", date(2026, 1, 15))["difference_hours"] == -10.5  # EST


def test_sydney_is_ahead_and_overlaps_in_the_indian_morning():
    w = ov("Australia/Sydney", date(2026, 1, 15))
    assert w["difference_hours"] == 5.5 and w["windows"] == [
        {"home_start": "09:00", "home_end": "12:30", "client_start": "14:30", "client_end": "18:00"}
    ]
    assert w["client_day_in_home_time"] == "03:30-12:30"


def test_same_zone_and_custom_working_hours():
    s = ov(IST, date(2026, 1, 15))
    assert s["overlap_hours"] == 9 and s["rating"] == "good" and s["difference_hours"] == 0
    d = ov("Asia/Dubai", date(2026, 1, 15), start_hour=10, end_hour=16)
    assert (
        d["overlap_hours"] == 4.5
        and d["windows"][0]["home_start"] == "11:30"
        and d["hours"] == "10:00-16:00"
    )


@pytest.mark.parametrize(
    "end_hour,hours,rating",
    [
        (10, 1.0, "limited"),
        (11, 2.0, "workable"),
        (12, 3.0, "workable"),
        (13, 4.0, "good"),
        (18, 9.0, "good"),
    ],
)
def test_rating_thresholds(end_hour, hours, rating):
    # same zone on both sides, so the overlap is exactly the length of the working window
    got = overlap(IST, IST, start_hour=9, end_hour=end_hour, on=date(2026, 1, 15))
    assert (got["overlap_hours"], got["rating"]) == (hours, rating)


def test_unknown_zone_raises_and_country_suggestions():
    with pytest.raises(ZoneInfoNotFoundError):
        overlap(IST, "Mars/Olympus")
    assert (
        suggest_timezone(" Germany ") == "Europe/Berlin"
        and suggest_timezone("UK") == "Europe/London"
    )
    assert suggest_timezone("Atlantis") == ""


# ---------------------------------------------------------------- API
async def test_overlap_endpoint_uses_your_settings(auth_client):
    r = (
        await auth_client.get(f"{P}/foreign/tz-overlap?timezone=Europe/London&on=2026-01-15")
    ).json()
    assert r["overlap_hours"] == 3.5 and r["home_tz"] == IST
    await auth_client.put(f"{P}/settings", json={"work_start_hour": 12, "work_end_hour": 20})
    r = (
        await auth_client.get(f"{P}/foreign/tz-overlap?timezone=Europe/London&on=2026-01-15")
    ).json()
    assert r["hours"] == "12:00-20:00" and r["overlap_hours"] != 3.5
    assert (await auth_client.get(f"{P}/foreign/tz-overlap?timezone=Nope/Zone")).status_code == 422
    assert (await auth_client.get(f"{P}/foreign/tz-overlap")).status_code == 422
    assert (await auth_client.get(f"{P}/foreign/tz-suggest?country=Germany")).json() == {
        "timezone": "Europe/Berlin"
    }


async def test_lead_carries_overlap_indicator(auth_client):
    a = (
        await auth_client.post(
            f"{P}/leads",
            json={
                "business_name": "Berlin GmbH",
                "timezone": "Europe/Berlin",
                "country": "Germany",
                "currency": "eur",
            },
        )
    ).json()
    b = (await auth_client.post(f"{P}/leads", json={"business_name": "No zone"})).json()
    assert (
        a["currency"] == "EUR"
        and a["tz_overlap"]["client_tz"] == "Europe/Berlin"
        and a["tz_overlap"]["rating"] in {"good", "workable", "limited", "none"}
    )
    assert b["tz_overlap"] is None
    listed = {x["id"]: x for x in (await auth_client.get(f"{P}/leads")).json()}
    assert listed[a["id"]]["tz_overlap"] and listed[b["id"]]["tz_overlap"] is None
    patched = (
        await auth_client.patch(f"{P}/leads/{b['id']}", json={"timezone": "Asia/Dubai"})
    ).json()
    assert patched["tz_overlap"]["rating"] == "good"
    assert (await auth_client.get(f"{P}/leads/{a['id']}")).json()["tz_overlap"][
        "client_tz"
    ] == "Europe/Berlin"


async def won_lead(c, **kw):
    return (
        await c.post(
            f"{P}/leads",
            json={
                "business_name": "Acme Inc",
                "status": "won",
                "country": "United States",
                "currency": "USD",
                **kw,
            },
        )
    ).json()


async def test_info_has_disclaimer(auth_client):
    i = (await auth_client.get(f"{P}/foreign/info")).json()
    assert "not tax" in i["disclaimer"].lower() and i["payment_methods"] == [
        "wise",
        "payoneer",
        "paypal",
        "swift",
        "other",
    ]


async def test_invoice_crud_and_firc_filter(auth_client):
    lead = await won_lead(auth_client)
    r = await auth_client.post(
        f"{P}/invoices",
        json={
            "lead_id": lead["id"],
            "amount": 1200,
            "reference": "INV-1",
            "payment_method": "wise",
            "lut_note": "LUT ARN pending",
        },
    )
    assert r.status_code == 201
    inv = r.json()
    assert (
        inv["currency"] == "USD"
        and inv["invoice_date"] == str(datetime.now(UTC).date())
        and inv["firc_received"] is False
        and inv["lead_name"] == "Acme Inc"
    )
    other = (
        await auth_client.post(
            f"{P}/invoices",
            json={
                "lead_id": lead["id"],
                "amount": 300,
                "currency": "eur",
                "payment_method": "swift",
                "firc_received": True,
                "invoice_date": str(date(2026, 1, 2)),
            },
        )
    ).json()
    assert other["currency"] == "EUR"
    assert [i["id"] for i in (await auth_client.get(f"{P}/invoices?firc=pending")).json()] == [
        inv["id"]
    ]
    assert [i["id"] for i in (await auth_client.get(f"{P}/invoices?firc=received")).json()] == [
        other["id"]
    ]
    assert [i["id"] for i in (await auth_client.get(f"{P}/invoices?lead_id={lead['id']}")).json()][
        0
    ] == inv["id"]  # newest first
    r = (
        await auth_client.patch(
            f"{P}/invoices/{inv['id']}", json={"firc_received": True, "payment_method": "payoneer"}
        )
    ).json()
    assert (
        r["firc_received"] is True
        and r["payment_method"] == "payoneer"
        and r["lut_note"] == "LUT ARN pending"
    )
    assert (await auth_client.get(f"{P}/invoices?firc=pending")).json() == []
    assert (await auth_client.delete(f"{P}/invoices/{other['id']}")).status_code == 200
    assert len((await auth_client.get(f"{P}/invoices")).json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"amount": 0},
        {"amount": -3},
        {"payment_method": "cheque"},
        {"currency": "DOLLARS"},
        {"lut_note": "x" * 2001},
    ],
)
async def test_invoice_validation(auth_client, body):
    lead = await won_lead(auth_client)
    assert (
        await auth_client.post(f"{P}/invoices", json={"lead_id": lead["id"], "amount": 10, **body})
    ).status_code == 422


async def test_invoices_cascade_and_are_per_user(auth_client, client):
    lead = await won_lead(auth_client)
    inv = (
        await auth_client.post(f"{P}/invoices", json={"lead_id": lead["id"], "amount": 50})
    ).json()
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"{P}/invoices", headers=other)).json() == []
    assert (
        await client.post(f"{P}/invoices", json={"lead_id": lead["id"], "amount": 5}, headers=other)
    ).status_code == 404
    assert (
        await client.patch(f"{P}/invoices/{inv['id']}", json={"amount": 1}, headers=other)
    ).status_code == 404
    assert (await client.delete(f"{P}/invoices/{inv['id']}", headers=other)).status_code == 404
    await auth_client.delete(f"{P}/leads/{lead['id']}")  # an invoice belongs to its lead
    assert (await auth_client.get(f"{P}/invoices")).json() == []


async def test_stats_summarise_foreign_work(auth_client):
    lead = await won_lead(auth_client)
    await auth_client.post(f"{P}/leads", json={"business_name": "Berlin", "country": "Germany"})
    await auth_client.post(f"{P}/invoices", json={"lead_id": lead["id"], "amount": 1000})
    await auth_client.post(
        f"{P}/invoices", json={"lead_id": lead["id"], "amount": 250.5, "firc_received": True}
    )
    f = (await auth_client.get(f"{P}/stats")).json()["foreign"]
    assert f == {
        "invoices": 2,
        "firc_pending": 1,
        "invoiced": {"USD": 1250.5},
        "countries": ["Germany", "United States"],
    }
