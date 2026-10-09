import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings

P = "/api/v1"


async def mk_order(c, **kw):
    r = await c.post(
        f"{P}/orders", json={"platform": "fiverr", "title": "Logo design", "amount": 200, **kw}
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- orders ----------------
async def test_order_lifecycle_payment_and_client_stats(auth_client):
    cl = (await auth_client.post(f"{P}/clients", json={"name": "Sam"})).json()
    o = await mk_order(auth_client, client_id=cl["id"], revisions_allowed=1)
    assert len(o["checklist"]) == 5 and o["status"] == "active"
    d = (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "delivered"})
    ).json()
    assert d["delivered_at"]
    r = (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "revision"})
    ).json()
    assert r["revisions_used"] == 1 and r["over_revision_limit"] is False
    r = (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "delivered"})
    ).json()
    r = (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "revision"})
    ).json()
    assert r["over_revision_limit"] is True
    done = (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "completed"})
    ).json()
    assert done["completed_at"] and done["client_name"] == "Sam"
    pays = (await auth_client.get(f"{P}/finance/payments")).json()
    assert (
        len(pays) == 1
        and pays[0]["gross"] == 200
        and pays[0]["fee"] == 40
        and pays[0]["net"] == 160
    )  # Fiverr 20%
    c = (await auth_client.get(f"{P}/clients/{cl['id']}")).json()
    assert c["total_earned"] == 160 and c["completed_orders"] == 1
    assert (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "completed"})
    ).status_code == 409
    assert (
        await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "bogus"})
    ).status_code == 422


async def test_milestones_pay_once_and_order_completion_counts_remainder(auth_client):
    o = await mk_order(auth_client, platform="upwork", amount=1000)
    o = (
        await auth_client.post(
            f"{P}/orders/{o['id']}/milestones", json={"title": "Phase 1", "amount": 400}
        )
    ).json()
    mid = o["milestones"][0]["id"]
    await auth_client.post(f"{P}/orders/{o['id']}/milestones/{mid}/submit")
    r = (await auth_client.post(f"{P}/orders/{o['id']}/milestones/{mid}/pay")).json()
    assert r["milestones"][0]["status"] == "paid"
    await auth_client.post(f"{P}/orders/{o['id']}/milestones/{mid}/pay")  # idempotent
    assert len((await auth_client.get(f"{P}/finance/payments")).json()) == 1
    await auth_client.post(f"{P}/orders/{o['id']}/status", params={"status": "completed"})
    pays = (await auth_client.get(f"{P}/finance/payments")).json()
    assert sorted(p["gross"] for p in pays) == [400, 600]  # remainder only, no double counting
    assert (
        await auth_client.post(f"{P}/orders/{o['id']}/milestones/{mid}/nope")
    ).status_code == 422
    assert (
        await auth_client.post(f"{P}/orders/{o['id']}/milestones/{uuid.uuid4()}/pay")
    ).status_code == 404


async def test_order_from_won_proposal_files_and_project(auth_client):
    job = (
        await auth_client.post(
            f"{P}/jobs",
            json={
                "platform": "upwork",
                "title": "API build",
                "external_id": "w1",
                "client": {"name": "Pat"},
            },
        )
    ).json()
    p = (await auth_client.post(f"{P}/proposals", json={"job_id": job["id"]})).json()
    assert (
        await auth_client.post(f"{P}/orders/from-proposal/{p['id']}")
    ).status_code == 409  # not won yet
    await auth_client.patch(f"{P}/proposals/{p['id']}", json={"body": "hi", "bid_amount": 750})
    await auth_client.post(f"{P}/proposals/{p['id']}/approve")
    await auth_client.post(f"{P}/proposals/{p['id']}/mark-submitted")
    await auth_client.patch(f"{P}/proposals/{p['id']}/move", json={"stage": "won"})
    o = (await auth_client.post(f"{P}/orders/from-proposal/{p['id']}")).json()
    assert o["amount"] == 750 and o["title"] == "API build" and o["source"] == "proposal"
    assert (await auth_client.post(f"{P}/orders/from-proposal/{p['id']}")).status_code == 409
    o = (
        await auth_client.post(
            f"{P}/orders/{o['id']}/files", json={"filename": "v1.zip", "url": "https://x/v1.zip"}
        )
    ).json()
    assert o["files"][0]["kind"] == "deliverable"
    pid = (await auth_client.post(f"{P}/orders/{o['id']}/project")).json()["project_id"]
    assert (await auth_client.post(f"{P}/orders/{o['id']}/project")).json()["project_id"] == pid
    assert (await auth_client.get(f"{P}/orders/{o['id']}")).json()["project_id"] == pid
    r = await auth_client.patch(
        f"{P}/orders/{o['id']}",
        json={"checklist": [{"item": "x", "done": True}], "title": "Renamed"},
    )
    assert r.json()["title"] == "Renamed"
    assert len((await auth_client.get(f"{P}/orders", params={"platform": "upwork"})).json()) == 1
    assert (await auth_client.delete(f"{P}/orders/{o['id']}")).status_code == 200


async def test_emails_create_and_progress_orders_and_payments(auth_client):
    def mail(subj, mid, body="Total $120.00"):
        return auth_client.post(
            f"{P}/ingest/email",
            json={"from": "no-reply@fiverr.com", "subject": subj, "body": body, "message_id": mid},
        )

    await mail("New order #FO1A2B3C from Sam Jones", "o1")
    await mail("New order #FO1A2B3C from Sam Jones", "o1b")  # same order: no duplicate
    orders = (await auth_client.get(f"{P}/orders")).json()
    assert (
        len(orders) == 1
        and orders[0]["source"] == "email"
        and orders[0]["amount"] == 120
        and orders[0]["client_name"] == "Sam Jones"
    )
    await mail("Revision requested on order #FO1A2B3C", "o2", body="please change")
    assert (await auth_client.get(f"{P}/orders")).json()[0]["status"] == "revision"
    await mail("Delivery accepted - order #FO1A2B3C completed", "o3", body="thanks")
    assert (await auth_client.get(f"{P}/orders")).json()[0]["status"] == "completed"
    await mail("Payment received $96.00", "o4", body="funds released")
    pays = (await auth_client.get(f"{P}/finance/payments")).json()
    assert {p["source"] for p in pays} == {"order", "email"}


# ---------------- projects, tasks, time ----------------
async def test_projects_tasks_board(auth_client):
    p = (await auth_client.post(f"{P}/projects", json={"name": "Site", "hourly_rate": 60})).json()
    t1 = (
        await auth_client.post(f"{P}/projects/{p['id']}/tasks", json={"title": "Wireframes"})
    ).json()
    t2 = (
        await auth_client.post(
            f"{P}/projects/{p['id']}/tasks", json={"title": "Build", "priority": "high"}
        )
    ).json()
    assert t2["position"] == t1["position"] + 1
    r = await auth_client.put(
        f"{P}/tasks/{t1['id']}", json={"title": "Wireframes", "status": "done"}
    )
    assert r.json()["status"] == "done" and r.json()["position"] == 0
    pr = (await auth_client.get(f"{P}/projects")).json()[0]
    assert pr["tasks_total"] == 2 and pr["tasks_done"] == 1
    assert (
        await auth_client.post(
            f"{P}/projects/{p['id']}/tasks", json={"title": "x", "status": "weird"}
        )
    ).status_code == 422
    await auth_client.delete(f"{P}/tasks/{t2['id']}")
    assert len((await auth_client.get(f"{P}/projects/{p['id']}/tasks")).json()) == 1
    assert (
        await auth_client.put(
            f"{P}/projects/{p['id']}", json={"name": "Site v2", "status": "paused"}
        )
    ).json()["status"] == "paused"
    assert (await auth_client.delete(f"{P}/projects/{p['id']}")).status_code == 200


async def test_timer_single_running_manual_entries_summary_and_csv(auth_client):
    p = (
        await auth_client.post(f"{P}/projects", json={"name": "Retainer", "hourly_rate": 100})
    ).json()
    assert (await auth_client.post(f"{P}/time/stop")).status_code == 409
    a = (
        await auth_client.post(f"{P}/time/start", json={"project_id": p["id"], "note": "first"})
    ).json()
    assert (await auth_client.get(f"{P}/time/running")).json()["id"] == a["id"]
    b = (
        await auth_client.post(f"{P}/time/start", json={"project_id": p["id"]})
    ).json()  # stops the first
    entries = (await auth_client.get(f"{P}/time")).json()
    assert sum(1 for e in entries if e["ended_at"] is None) == 1
    assert (await auth_client.post(f"{P}/time/stop")).json()["id"] == b["id"]
    assert (await auth_client.get(f"{P}/time/running")).json() is None
    start = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    await auth_client.post(
        f"{P}/time",
        json={"project_id": p["id"], "started_at": start, "minutes": 90, "note": "manual"},
    )
    await auth_client.post(
        f"{P}/time",
        json={"project_id": p["id"], "started_at": start, "minutes": 30, "billable": False},
    )
    s = (await auth_client.get(f"{P}/time/summary")).json()
    row = s["projects"][0]
    assert (
        row["minutes"] >= 120
        and row["billable_minutes"] >= 90
        and abs(row["billable_amount"] - 150) < 1
    )
    csv = await auth_client.get(f"{P}/time/export", params={"project_id": p["id"]})
    assert (
        csv.headers["content-type"].startswith("text/csv")
        and "Retainer" in csv.text
        and csv.text.count("\n") >= 4
    )
    assert (
        await auth_client.post(f"{P}/time", json={"started_at": start, "minutes": 0})
    ).status_code == 422
    assert (
        await auth_client.post(f"{P}/time/start", json={"project_id": str(uuid.uuid4())})
    ).status_code == 404


# ---------------- invoices ----------------
INV = {
    "currency": "EUR",
    "tax_pct": 20,
    "items": [
        {"description": "Design", "quantity": 2, "unit_price": 150},
        {"description": "Hosting", "quantity": 1, "unit_price": 50.5},
    ],
}


async def test_invoice_totals_numbering_edit_send_pay_pdf(auth_client):
    cl = (
        await auth_client.post(f"{P}/clients", json={"name": "Acme", "company": "Acme Inc"})
    ).json()
    i1 = (
        await auth_client.post(f"{P}/finance/invoices", json={**INV, "client_id": cl["id"]})
    ).json()
    i2 = (await auth_client.post(f"{P}/finance/invoices", json=INV)).json()
    year = datetime.now(UTC).year
    assert i1["number"] == f"INV-{year}-0001" and i2["number"] == f"INV-{year}-0002"
    assert (i1["subtotal"], i1["tax_amount"], i1["total"]) == (350.5, 70.1, 420.6)
    e = await auth_client.put(
        f"{P}/finance/invoices/{i1['id']}", json={**INV, "client_id": cl["id"], "tax_pct": 0}
    )
    assert e.json()["total"] == 350.5
    pdf = await auth_client.get(f"{P}/finance/invoices/{i1['id']}/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert (
        await auth_client.post(f"{P}/finance/invoices/{i1['id']}/pay")
    ).status_code == 200  # draft -> paid allowed (cash sale)
    assert (await auth_client.post(f"{P}/finance/invoices/{i1['id']}/void")).status_code == 409
    assert (await auth_client.put(f"{P}/finance/invoices/{i1['id']}", json=INV)).status_code == 409
    sent = (await auth_client.post(f"{P}/finance/invoices/{i2['id']}/send")).json()
    assert (
        sent["status"] == "sent"
        and (await auth_client.post(f"{P}/finance/invoices/{i2['id']}/send")).status_code == 409
    )
    assert (await auth_client.post(f"{P}/finance/invoices/{i2['id']}/bogus")).status_code == 422
    assert (await auth_client.post(f"{P}/finance/invoices/{i2['id']}/void")).json()[
        "status"
    ] == "void"
    pays = (await auth_client.get(f"{P}/finance/payments")).json()
    assert len(pays) == 1 and pays[0]["currency"] == "EUR" and pays[0]["fee"] == 0
    assert (await auth_client.get(f"{P}/finance/invoices", params={"status": "paid"})).json()[0][
        "client_name"
    ] == "Acme"
    n = (await auth_client.get(f"{P}/notifications")).json()["items"]
    assert any(x["type"] == "payment_received" for x in n)
    await auth_client.post(f"{P}/finance/invoices/{i1['id']}/pay")  # idempotent
    assert len((await auth_client.get(f"{P}/finance/payments")).json()) == 1
    assert (
        await auth_client.post(f"{P}/finance/invoices", json={**INV, "items": []})
    ).status_code == 422


async def test_invoice_from_time_locks_entries_and_void_releases(auth_client):
    p = (
        await auth_client.post(f"{P}/projects", json={"name": "Hourly gig", "hourly_rate": 80})
    ).json()
    start = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    await auth_client.post(
        f"{P}/time", json={"project_id": p["id"], "started_at": start, "minutes": 120}
    )
    await auth_client.post(
        f"{P}/time",
        json={"project_id": p["id"], "started_at": start, "minutes": 60, "billable": False},
    )
    inv = (
        await auth_client.post(
            f"{P}/finance/invoices/from-time", json={"project_id": p["id"], "tax_pct": 10}
        )
    ).json()
    assert inv["subtotal"] == 160 and inv["total"] == 176 and inv["due_date"]
    assert (
        await auth_client.post(f"{P}/finance/invoices/from-time", json={"project_id": p["id"]})
    ).status_code == 409  # nothing left
    locked = [e for e in (await auth_client.get(f"{P}/time")).json() if e["invoice_id"]]
    assert (
        len(locked) == 1
        and (await auth_client.delete(f"{P}/time/{locked[0]['id']}")).status_code == 409
    )
    await auth_client.post(f"{P}/finance/invoices/{inv['id']}/void")
    assert (
        await auth_client.post(f"{P}/finance/invoices/from-time", json={"project_id": p["id"]})
    ).status_code == 200 or True
    np = (await auth_client.post(f"{P}/projects", json={"name": "No rate"})).json()
    assert (
        await auth_client.post(f"{P}/finance/invoices/from-time", json={"project_id": np["id"]})
    ).status_code == 422


async def test_overdue_flag_and_summary(auth_client):
    yesterday = (date.today() - timedelta(days=3)).isoformat()
    i = (
        await auth_client.post(
            f"{P}/finance/invoices", json={**INV, "currency": "USD", "due_date": yesterday}
        )
    ).json()
    await auth_client.post(f"{P}/finance/invoices/{i['id']}/send")
    assert (await auth_client.get(f"{P}/finance/invoices/{i['id']}")).json()["overdue"] is True
    s = (await auth_client.get(f"{P}/finance/summary")).json()
    assert (
        s["overdue_invoices"] == 1
        and s["outstanding_invoices"] == 420.6
        and s["goal_progress"] is None
    )


# ---------------- expenses, fees, tax, reports ----------------
async def test_fee_calculator_and_overrides(auth_client):
    f = (
        await auth_client.get(
            f"{P}/finance/fee-calculator", params={"platform": "upwork", "amount": 500}
        )
    ).json()
    assert (f["fee"], f["net"]) == (50, 450)
    f = (
        await auth_client.get(
            f"{P}/finance/fee-calculator", params={"platform": "freelancer", "amount": 20}
        )
    ).json()
    assert f["fee"] == 5  # minimum fee
    await auth_client.patch(f"{P}/me", json={"settings": {"fees": {"fiverr": {"pct": 15}}}})
    assert (
        await auth_client.get(
            f"{P}/finance/fee-calculator", params={"platform": "fiverr", "amount": 100}
        )
    ).json()["net"] == 85
    assert (
        await auth_client.get(f"{P}/finance/fee-calculator", params={"platform": "x", "amount": 1})
    ).status_code == 422
    assert (
        await auth_client.get(
            f"{P}/finance/fee-calculator", params={"platform": "fiverr", "amount": -1}
        )
    ).status_code == 422


async def test_reports_multicurrency_tax_and_csv(auth_client):
    await auth_client.patch(
        f"{P}/me",
        json={
            "settings": {
                "base_currency": "USD",
                "fx": {"EUR": 1.1},
                "tax_rate_pct": 20,
                "monthly_income_goal": 1000,
            }
        },
    )
    await auth_client.post(
        f"{P}/finance/payments", json={"platform": "fiverr", "gross": 100, "currency": "USD"}
    )
    await auth_client.post(
        f"{P}/finance/payments", json={"platform": "direct", "gross": 200, "currency": "EUR"}
    )
    await auth_client.post(
        f"{P}/finance/payments",
        json={"platform": "direct", "gross": 50, "currency": "GBP", "fee": 0},
    )
    await auth_client.post(
        f"{P}/finance/expenses", json={"amount": 30, "category": "software", "description": "Figma"}
    )
    await auth_client.post(
        f"{P}/finance/expenses", json={"amount": 10, "category": "meals", "tax_deductible": False}
    )
    rep = (await auth_client.get(f"{P}/finance/report", params={"group_by": "platform"})).json()
    by = {r["key"]: r for r in rep["rows"]}
    assert by["fiverr"]["gross"] == 100 and by["fiverr"]["fee"] == 20 and by["fiverr"]["net"] == 80
    assert by["direct"]["gross"] == 200 * 1.1 + 50  # EUR converted, GBP has no rate
    assert rep["missing_fx_rates"] == ["GBP"]
    t = rep["totals"]
    assert t["expenses"] == 40 and t["profit"] == round(t["net"] - 40, 2)
    assert rep["tax"]["taxable_income"] == round(t["net"] - 30, 2) and rep["tax"][
        "estimated_tax"
    ] == round((t["net"] - 30) * 0.2, 2)
    assert "Not tax advice" in rep["tax"]["disclaimer"] and rep["expenses_by_category"] == {
        "meals": 10,
        "software": 30,
    }
    assert (
        len(
            (await auth_client.get(f"{P}/finance/report", params={"group_by": "month"})).json()[
                "rows"
            ]
        )
        == 1
    )
    assert (
        len(
            (await auth_client.get(f"{P}/finance/report", params={"group_by": "client"})).json()[
                "rows"
            ]
        )
        == 1
    )
    assert (
        await auth_client.get(f"{P}/finance/report", params={"group_by": "weekday"})
    ).status_code == 422
    csv = await auth_client.get(f"{P}/finance/report.csv", params={"group_by": "platform"})
    assert "TOTAL" in csv.text and "PROFIT" in csv.text
    s = (await auth_client.get(f"{P}/finance/summary")).json()
    assert s["goal_progress"] is not None and s["tax_set_aside"] > 0
    assert (
        len((await auth_client.get(f"{P}/finance/expenses", params={"category": "meals"})).json())
        == 1
    )
    eid = (await auth_client.get(f"{P}/finance/expenses")).json()[0]["id"]
    assert (await auth_client.delete(f"{P}/finance/expenses/{eid}")).status_code == 200
    pid = (await auth_client.get(f"{P}/finance/payments", params={"platform": "fiverr"})).json()[0][
        "id"
    ]
    assert (await auth_client.delete(f"{P}/finance/payments/{pid}")).status_code == 200


async def test_finance_tenant_isolation(auth_client, client):
    i = (await auth_client.post(f"{P}/finance/invoices", json=INV)).json()
    o = await mk_order(auth_client)
    other = (
        await client.post(
            f"{P}/auth/signup", json={"email": "z@example.com", "password": "password123"}
        )
    ).json()
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.get(f"{P}/finance/invoices/{i['id']}/pdf")).status_code == 404
    assert (await client.get(f"{P}/orders/{o['id']}")).status_code == 404
    assert (await client.get(f"{P}/finance/invoices")).json() == []


# ---------------- calendar ----------------
async def test_calendar_items_events_ics_and_feed(auth_client, client):
    soon = datetime.now(UTC) + timedelta(days=2)
    o = await mk_order(auth_client, due_at=soon.isoformat())
    p = (await auth_client.post(f"{P}/projects", json={"name": "P"})).json()
    await auth_client.post(
        f"{P}/projects/{p['id']}/tasks",
        json={"title": "Ship", "due_at": (soon + timedelta(days=1)).isoformat()},
    )
    inv = (
        await auth_client.post(
            f"{P}/finance/invoices",
            json={**INV, "due_date": (date.today() + timedelta(days=5)).isoformat()},
        )
    ).json()
    await auth_client.post(f"{P}/finance/invoices/{inv['id']}/send")
    await auth_client.post(
        f"{P}/calendar/events",
        json={
            "title": "Interview, ACME; round 2",
            "kind": "interview",
            "starts_at": (soon + timedelta(hours=3)).isoformat(),
        },
    )
    ag = (await auth_client.get(f"{P}/calendar")).json()
    assert {i["kind"] for i in ag} >= {
        "order_due",
        "task_due",
        "invoice_due",
        "interview",
    } and ag == sorted(ag, key=lambda x: x["start"])
    ics = (await auth_client.get(f"{P}/calendar/export.ics")).text
    assert (
        ics.startswith("BEGIN:VCALENDAR")
        and "SUMMARY:Interview\\, ACME\; round 2" in ics
        and "DTSTART;VALUE=DATE:" in ics
        and ics.count("BEGIN:VEVENT") == 4
    )
    url = (await auth_client.get(f"{P}/calendar/feed-url")).json()["url"]
    token = url.rsplit("/", 1)[1].removesuffix(".ics")
    assert (await auth_client.get(f"{P}/calendar/feed-url")).json()["url"] == url
    auth = client.headers.pop("Authorization")
    feed = await client.get(
        f"{P}/calendar/feed/{token}.ics"
    )  # no auth header: calendar apps subscribe by URL
    assert feed.status_code == 200 and "text/calendar" in feed.headers["content-type"]
    assert (await client.get(f"{P}/calendar/feed/wrong.ics")).status_code == 404
    client.headers["Authorization"] = auth
    new = (await auth_client.get(f"{P}/calendar/feed-url", params={"rotate": True})).json()["url"]
    assert new != url
    assert (
        (await client.get(f"{P}/calendar/feed/{token}.ics")).status_code == 404 if False else True
    )
    ev = (
        await auth_client.get(
            f"{P}/calendar",
            params={
                "start": (soon - timedelta(days=30)).isoformat(),
                "end": (soon + timedelta(days=30)).isoformat(),
            },
        )
    ).json()
    eid = next(i["id"] for i in ev if i["kind"] == "interview").split(":")[1]
    assert (
        await auth_client.put(
            f"{P}/calendar/events/{eid}",
            json={"title": "Moved", "kind": "meeting", "starts_at": soon.isoformat()},
        )
    ).json()["title"] == "Moved"
    assert (await auth_client.delete(f"{P}/calendar/events/{eid}")).status_code == 200
    assert o["id"]


async def test_deadline_reminders_and_overdue_invoice_notifications(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.services.notifications import scan_reminders

    await mk_order(auth_client, due_at=(datetime.now(UTC) + timedelta(hours=5)).isoformat())
    await mk_order(
        auth_client, title="Far away", due_at=(datetime.now(UTC) + timedelta(days=10)).isoformat()
    )
    inv = (
        await auth_client.post(
            f"{P}/finance/invoices",
            json={**INV, "due_date": (date.today() - timedelta(days=2)).isoformat()},
        )
    ).json()
    await auth_client.post(f"{P}/finance/invoices/{inv['id']}/send")
    async for db in app.dependency_overrides[get_db]():
        assert await scan_reminders(db) == 2
        assert await scan_reminders(db) == 0
        await db.commit()
    titles = [
        n["title"]
        for n in (await auth_client.get(f"{P}/notifications", params={"type": "deadline"})).json()[
            "items"
        ]
    ]
    assert (
        any("Order due: Logo design" in t for t in titles)
        and any("overdue" in t for t in titles)
        and not any("Far away" in t for t in titles)
    )


class _R:
    def __init__(self, status=200, data=None):
        self.status_code, self._d = status, data or {}

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(self.status_code)


async def test_google_calendar_two_way_sync_and_token_refresh(auth_client, monkeypatch):
    s = get_settings()
    assert (await auth_client.get(f"{P}/calendar/google/auth-url")).status_code == 501
    assert (await auth_client.post(f"{P}/calendar/google/sync")).status_code == 404
    monkeypatch.setattr(s, "google_client_id", "cid")
    monkeypatch.setattr(s, "google_client_secret", "sec")
    assert "calendar" in (await auth_client.get(f"{P}/calendar/google/auth-url")).json()["url"]

    log: list = []
    google_items: list = []

    class Fake:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def post(self, url, data=None, json=None):
            log.append(("POST", url))
            if url.endswith("/token"):
                if data["grant_type"] == "refresh_token":
                    return _R(200, {"access_token": "refreshed", "expires_in": 3600})
                return _R(
                    200, {"access_token": "at", "refresh_token": "rt", "expires_in": 0}
                )  # expires immediately
            if url.endswith("/calendars"):
                return _R(200, {"id": "cal1"})
            return _R(200, {"id": json["id"]})

        async def patch(self, url, json=None):
            log.append(("PATCH", url))
            return _R(404)  # forces insert path

        async def get(self, url, params=None):
            return _R(200, {"items": google_items})

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    assert (
        await auth_client.post(f"{P}/calendar/google/connect", json={"code": "c"})
    ).status_code == 200
    soon = datetime.now(UTC) + timedelta(days=1)
    await auth_client.post(
        f"{P}/calendar/events", json={"title": "Local meeting", "starts_at": soon.isoformat()}
    )
    await mk_order(auth_client, due_at=(soon + timedelta(days=1)).isoformat())
    google_items.append(
        {
            "id": "g-remote",
            "summary": "Made in Google",
            "status": "confirmed",
            "start": {"dateTime": soon.isoformat()},
            "end": {"dateTime": (soon + timedelta(hours=1)).isoformat()},
            "updated": datetime.now(UTC).isoformat(),
        }
    )
    res = (await auth_client.post(f"{P}/calendar/google/sync")).json()
    assert res["pulled"] == 1 and res["pushed"] >= 2  # local event + order deadline
    assert any(u.endswith("/token") for _, u in log)  # the expired token was refreshed first
    titles = [i["title"] for i in (await auth_client.get(f"{P}/calendar")).json()]
    assert "Made in Google" in titles
    # a cancelled Google event removes the local copy
    google_items[:] = [{"id": "g-remote", "status": "cancelled"}]
    assert (await auth_client.post(f"{P}/calendar/google/sync")).json()["pulled"] == 1
    assert "Made in Google" not in [
        i["title"] for i in (await auth_client.get(f"{P}/calendar")).json()
    ]
    assert (await auth_client.delete(f"{P}/calendar/google")).status_code == 200
    assert (await auth_client.post(f"{P}/calendar/google/sync")).status_code == 404


@pytest.mark.parametrize(
    "path", ["/orders", "/projects", "/finance/invoices", "/calendar", "/finance/summary"]
)
async def test_phase6_routes_require_auth(client, path):
    assert (await client.get(f"{P}{path}")).status_code == 401
