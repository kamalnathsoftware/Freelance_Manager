# mypy: ignore-errors
"""Realistic demo data so every screen is populated.

    python -m app.seed                      # needs a migrated database (alembic upgrade head)
    python -m app.seed --email me@x.com --password 'Secret123!'

Idempotent per email: re-running resets that demo user's data.
"""

import argparse
import asyncio
import random
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    AccountStatus,
    AutomationRule,
    CalendarEvent,
    CannedResponse,
    ChatWidget,
    Expense,
    Form,
    FormField,
    FormSubmission,
    Gig,
    GigPackage,
    GigPlatformListing,
    IntegrationMode,
    Invoice,
    Job,
    MasterProfile,
    Milestone,
    Order,
    PlatformAccount,
    PlatformProfile,
    PortfolioItem,
    Project,
    Proposal,
    ProposalTemplate,
    SavedSearch,
    Stage,
    Task,
    TimeEntry,
    User,
)
from app.services import finance, inbox, notifications, orders, profiles
from app.services import forms as forms_svc
from app.services import ingest as ingest_svc
from app.services import proposals as prop_svc

SKILLS = [
    "Python",
    "FastAPI",
    "PostgreSQL",
    "React",
    "TypeScript",
    "Docker",
    "AWS",
    "Next.js",
    "REST APIs",
    "Celery",
]


def ago(days: float = 0, hours: float = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days, hours=hours)


async def seed(
    db: AsyncSession, email: str = "demo@freelancemanager.dev", password: str = "demo1234!"
) -> User:
    rnd = random.Random(42)  # deterministic demo data
    old = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if old is not None:
        await db.delete(old)
        await db.flush()
    user = User(email=email, password_hash=hash_password(password), full_name="Alex Demo", timezone="Europe/Berlin", email_verified=True,
                settings={"base_currency": "USD", "fx": {"EUR": 1.08, "GBP": 1.27}, "tax_rate_pct": 25, "goals": {"monthly_income": 6000, "yearly_income": 72000, "weekly_hours": 35},
                          "notif": {"quiet_start": "22:00", "quiet_end": "07:00"}})  # fmt: skip
    db.add(user)
    await db.flush()
    uid = user.id

    # ---- profile, portfolio ----
    master = MasterProfile(
        user_id=uid, name="Alex Demo", headline="Senior Python & FastAPI engineer - APIs, data pipelines and SaaS backends",
        bio="I design and ship reliable backends for startups. 8 years of Python, FastAPI and PostgreSQL; I care about clean APIs, tests and boring, observable infrastructure. " * 3,
        skills=SKILLS, languages=["English", "German"], hourly_rate=65, currency="USD", location="Berlin, Germany", timezone="Europe/Berlin", availability="30 hrs/week",
        experience=[{"title": "Lead backend engineer", "company": "Acme SaaS", "years": 4}], education=[{"school": "TU Berlin", "degree": "BSc Computer Science"}],
    )  # fmt: skip
    db.add(master)
    for t, k in (
        ("Fintech dashboard API", "case_study"),
        ("Realtime inventory sync", "case_study"),
        ("Open-source FastAPI toolkit", "link"),
    ):
        db.add(
            PortfolioItem(
                user_id=uid,
                title=t,
                kind=k,
                url=f"https://example.com/{t.lower().replace(' ', '-')}",
                description="Demo portfolio item",
                tags=["python"],
            )
        )

    # ---- platform accounts ----
    accs: dict[str, PlatformAccount] = {}
    for plat, mode, username, stats in (
        ("upwork", IntegrationMode.manual, "alexdemo", {"pending_bids": 3, "credits": 42}), ("fiverr", IntegrationMode.email, "alex_codes", {"unread": 2, "active_orders": 2}),
        ("freelancer", IntegrationMode.manual, "alexd", {}), ("direct", IntegrationMode.manual, "", {}),
    ):  # fmt: skip
        a = PlatformAccount(
            user_id=uid,
            platform=plat,
            label=plat.title(),
            username=username,
            mode=mode,
            status=AccountStatus.connected,
            stats=stats,
            last_synced_at=ago(hours=2),
        )
        db.add(a)
        accs[plat] = a
    await db.flush()
    for a in accs.values():
        if a.platform in ("upwork", "fiverr"):
            pp = PlatformProfile(account_id=a.id)
            db.add(pp)
            profiles.apply_derived(pp, profiles.derive_for_platform(master, a.platform), master)

    # ---- gigs ----
    for title, cat, price in (
        (
            "I will build a production-ready FastAPI backend for your startup",
            "Programming & Tech",
            250,
        ),
        ("I will design and optimise your PostgreSQL database", "Programming & Tech", 120),
    ):
        g = Gig(
            user_id=uid,
            title=title,
            category=cat,
            tags=["python", "fastapi", "api", "postgresql", "backend"],
            description=("Detailed gig description. " * 25),
            gallery=["https://example.com/g1.png"],
            faq=[{"q": "Do you sign NDAs?", "a": "Yes."}],
            status="live",
        )  # type: ignore[arg-type]
        db.add(g)
        await db.flush()
        for tier, mult in (("basic", 1), ("standard", 2), ("premium", 4)):
            db.add(
                GigPackage(
                    gig_id=g.id,
                    tier=tier,
                    name=tier.title(),
                    price=price * mult,
                    delivery_days=3 * mult,
                    revisions=mult,
                )
            )
        db.add(
            GigPlatformListing(
                gig_id=g.id,
                account_id=accs["fiverr"].id,
                status="live",
                metrics={
                    "impressions": rnd.randint(2000, 6000),
                    "clicks": rnd.randint(100, 400),
                    "orders": rnd.randint(4, 15),
                },
                overrides={"title": title[:80]},
            )
        )

    # ---- jobs / proposals / pipeline ----
    db.add(
        SavedSearch(
            user_id=uid, name="Python backend", keywords=["fastapi", "python"], alert_min_score=60
        )
    )
    tpl = ProposalTemplate(
        user_id=uid,
        name="Backend intro",
        body="Hi {client_name}, I've built similar systems with {skill_match}. Here's how I'd approach {job_title}: ...",
    )
    db.add(tpl)
    await db.flush()
    titles = ["FastAPI microservice for payments", "Data pipeline in Python + Airflow", "Next.js dashboard with API", "Fix slow PostgreSQL queries", "Build Slack bot", "REST API for mobile app",
              "Celery task refactor", "Docker + CI setup", "Scraper (no thanks)", "WordPress plugin", "AWS Lambda ETL", "React admin panel"]  # fmt: skip
    jobs: list[Job] = []
    for i, t in enumerate(titles):
        plat = ["upwork", "freelancer", "fiverr", "upwork"][i % 4]
        j, _ = await ingest_svc.upsert_job(
            db, uid, {"platform": plat, "title": t, "external_id": f"demo-{i}", "description": f"{t}. Looking for an experienced developer. Stack: {', '.join(rnd.sample(SKILLS, 3))}.",
                      "skills": rnd.sample(SKILLS, 3), "budget_min": rnd.choice([300, 500, 1000]), "budget_max": rnd.choice([800, 1500, 3000, 5000]), "client": {"name": f"Client {i}", "verified": i % 2 == 0},
                      "url": f"https://example.com/jobs/{i}", "posted_at": ago(days=rnd.random() * 4)}, "email" if i % 3 == 0 else "extension" if i % 3 == 1 else "manual")  # fmt: skip
        jobs.append(j)
    stages = [
        Stage.found,
        Stage.shortlisted,
        Stage.drafted,
        Stage.submitted,
        Stage.submitted,
        Stage.viewed,
        Stage.interview,
        Stage.won,
        Stage.won,
        Stage.lost,
        Stage.lost,
        Stage.lost,
    ]
    props: list[Proposal] = []
    for j, st in zip(jobs, stages, strict=True):
        p = Proposal(
            user_id=uid,
            job_id=j.id,
            account_id=accs.get(j.platform, accs["upwork"]).id,
            template_id=tpl.id if st != Stage.found else None,
            body="Tailored proposal text." if st != Stage.found else "",
            bid_amount=rnd.choice([450, 900, 1400, 2200]),
            stage=Stage.found,
        )
        db.add(p)
        await db.flush()
        await prop_svc.move(db, p, st, "Budget too low" if st == Stage.lost else "")
        if st in (Stage.submitted, Stage.viewed, Stage.interview, Stage.won, Stage.lost):
            p.approved_at = ago(days=rnd.randint(6, 20))
            p.submitted_at = p.approved_at + timedelta(hours=rnd.randint(1, 20))
            p.submitted_via = "manual"
            p.follow_up_at = (
                ago(days=1) if st == Stage.submitted else p.submitted_at + timedelta(days=3)
            )
        props.append(p)

    # ---- clients, conversations ----
    names = [
        ("Sam Jones", "fiverr", True),
        ("Priya Natarajan", "upwork", False),
        ("Lena Fischer", "direct", False),
        ("Marco Rossi", "freelancer", False),
        ("Dana Whitfield", "upwork", True),
        ("Omar Haddad", "fiverr", False),
    ]
    clients = {}
    for n, plat, vip in names:
        c = await inbox.resolve_client(
            db, uid, plat, n.lower(), name=n, email=f"{n.split()[0].lower()}@example.com"
        )
        c.vip, c.company = vip, f"{n.split()[1]} & Co"
        c.total_earned, c.completed_orders = (rnd.choice([450, 1200, 3100]), rnd.randint(1, 3))
        clients[n] = (c, plat)
        conv, _ = await inbox.get_or_create_conversation(
            db, uid, plat, f"demo:{n}", subject=f"Project with {n}", client=c
        )
        await inbox.add_inbound(
            db,
            conv,
            "Hi Alex, quick question about the timeline for our project - could we move delivery up a few days?",
            sender=n,
            source="email",
            external_key=f"demo-in-{n}-1",
        )
        if n != "Sam Jones":
            await inbox.add_outbound(
                db, conv, "Sure, I can do that. I'll send an update tomorrow.", delivery="sent"
            )
            conv.unread_count = 0
    db.add_all(
        [
            CannedResponse(
                user_id=uid,
                shortcut="/thanks",
                body="Thanks for your message! I'll get back to you within a few hours.",
            ),
            CannedResponse(
                user_id=uid,
                shortcut="/quote",
                body="Happy to quote - could you share scope, deadline and budget range?",
            ),
        ]
    )
    db.add(ChatWidget(user_id=uid, public_key="cw_" + secrets.token_urlsafe(12)))

    # ---- orders, payments (6 months), projects, time ----
    for i, (title, plat, amt, status, due) in enumerate(
        [
            ("API for fintech app", "upwork", 2400, "active", 6),
            ("Logo-to-API integration", "fiverr", 350, "revision", 2),
            ("DB optimisation", "direct", 900, "delivered", -1),
            ("Data pipeline", "freelancer", 1800, "completed", -10),
        ]
    ):
        c = list(clients.values())[i][0]
        o = Order(
            user_id=uid,
            client_id=c.id,
            platform=plat,
            account_id=accs[plat].id,
            title=title,
            amount=amt,
            status="active",
            due_at=datetime.now(UTC) + timedelta(days=due),
            source="manual",
            revisions_allowed=2,
            checklist=[
                {"item": "Requirements confirmed", "done": True},
                {"item": "Work completed", "done": i == 3},
            ],
        )
        db.add(o)
        await db.flush()
        if i == 0:
            for k, (mt, ma) in enumerate([("Design", 800), ("Build", 1000), ("Launch", 600)]):
                m = Milestone(order_id=o.id, title=mt, amount=ma, due_at=ago(days=-(3 + 4 * k)))
                db.add(m)
                if k == 0:
                    await db.flush()
                    await orders.pay_milestone(db, o, m)
        if status != "active":
            await orders.set_status(db, o, status)
    for months_back in range(6, 0, -1):
        for _ in range(rnd.randint(2, 4)):
            plat = rnd.choice(["upwork", "fiverr", "direct", "freelancer"])
            gross = float(rnd.choice([250, 480, 900, 1500, 2100]))
            p, _c = await orders.record_payment(
                db,
                user,
                source="manual",
                source_id=uuid.uuid4().hex,
                platform=plat,
                gross=gross,
                currency=rnd.choice(["USD", "USD", "EUR"]),
                note="Seeded payment",
            )
            p.received_on = (ago(days=months_back * 30 - rnd.randint(0, 25))).date()
    for plat in ("upwork", "fiverr"):
        for _ in range(3):
            p, _c = await orders.record_payment(
                db,
                user,
                source="manual",
                source_id=uuid.uuid4().hex,
                platform=plat,
                gross=float(rnd.choice([300, 700, 1100])),
                currency="USD",
                note="This month",
            )
            p.received_on = date.today() - timedelta(days=rnd.randint(0, 8))

    web = Project(
        user_id=uid,
        client_id=list(clients.values())[0][0].id,
        name="Fintech API build",
        hourly_rate=65,
        description="Seeded project",
    )
    db.add(web)
    await db.flush()
    for i, (t, st) in enumerate(
        [
            ("Design schema", "done"),
            ("Auth endpoints", "done"),
            ("Payment webhooks", "doing"),
            ("Load tests", "todo"),
            ("Docs", "todo"),
        ]
    ):
        db.add(
            Task(
                user_id=uid,
                project_id=web.id,
                title=t,
                status=st,
                position=i,
                due_at=ago(days=-(i + 1)),
            )
        )
    for d in range(21):
        if (date.today() - timedelta(days=d)).weekday() < 5:
            start = ago(days=d, hours=rnd.randint(1, 3)).replace(minute=0)
            db.add(
                TimeEntry(
                    user_id=uid,
                    project_id=web.id,
                    started_at=start,
                    ended_at=start + timedelta(hours=rnd.randint(2, 6)),
                    note="Deep work",
                    billable=rnd.random() > 0.15,
                )
            )

    # ---- invoices, expenses ----
    for i, (status, due_in, amt) in enumerate(
        [("paid", -20, 1500), ("sent", 7, 2400), ("sent", -5, 900), ("draft", 14, 600)]
    ):
        inv = Invoice(user_id=uid, client_id=list(clients.values())[i][0].id, number=await finance.next_invoice_number(db, uid), currency="USD", status=status, issue_date=date.today() - timedelta(days=20), due_date=date.today() + timedelta(days=due_in),
                      items=[{"description": "Development services", "quantity": amt / 100, "unit_price": 100}], tax_pct=0)  # fmt: skip
        inv.subtotal, inv.tax_amount, inv.total = finance.compute_totals(inv.items, inv.tax_pct)
        if status == "paid":
            inv.paid_at = ago(days=18)
        db.add(inv)
    for cat, amt, desc in (
        ("software", 29, "Figma"),
        ("software", 49, "GitHub Copilot"),
        ("hosting", 35, "Fly.io"),
        ("fees", 18, "Payment processing"),
        ("coworking", 180, "Desk"),
    ):
        db.add(
            Expense(
                user_id=uid,
                amount=amt,
                category=cat,
                description=desc,
                spent_on=date.today() - timedelta(days=rnd.randint(1, 25)),
            )
        )

    # ---- forms, automations, calendar ----
    for key in ("project_brief", "review_request"):
        t = forms_svc.TEMPLATES[key]
        f = Form(
            user_id=uid,
            public_key="f_" + secrets.token_urlsafe(10),
            title=t["title"],
            description=t["description"],
            kind=t["kind"],
            settings=dict(t["settings"]),
            published=True,
        )
        db.add(f)
        await db.flush()
        for i, fd in enumerate(t["fields"]):
            db.add(FormField(form_id=f.id, position=i, **fd))
        if key == "review_request":
            db.add(
                FormSubmission(
                    form_id=f.id,
                    user_id=uid,
                    submitter_name="Dana Whitfield",
                    submitter_email="dana@example.com",
                    answers={
                        "name": "Dana Whitfield",
                        "rating": 5,
                        "comment": "Fast, communicative and the code was spotless.",
                    },
                )
            )
    from app.api.v1.automations import PRESETS

    for pr in PRESETS[:3]:
        db.add(
            AutomationRule(
                user_id=uid,
                name=pr["name"],
                trigger=pr["trigger"],
                conditions=pr["conditions"],
                actions=[a for a in pr["actions"] if a["type"] != "send_form"] or pr["actions"],
                enabled=True,
            )
        )
    db.add_all(
        [
            CalendarEvent(
                user_id=uid,
                title="Interview: Next.js dashboard",
                kind="interview",
                starts_at=datetime.now(UTC) + timedelta(days=2, hours=3),
            ),
            CalendarEvent(
                user_id=uid,
                title="Weekly planning",
                kind="meeting",
                starts_at=datetime.now(UTC) + timedelta(days=1),
            ),
        ]
    )

    await db.flush()
    await notifications.notify(
        db,
        user,
        "job_match",
        "Great match: FastAPI microservice for payments",
        body="Upwork - 82% match",
        url="/jobs",
        dedupe_key="seed-1",
    )
    await notifications.notify(
        db,
        user,
        "deadline",
        "Order due in 2 days: Logo-to-API integration",
        url="/orders",
        dedupe_key="seed-2",
    )
    return user


async def _main(email: str, password: str) -> None:
    from app.core.db import SessionLocal

    async with SessionLocal() as db:
        u = await seed(db, email, password)
        await db.commit()
        print(f"Seeded demo workspace for {u.email} (password: {password})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--email", default="demo@freelancemanager.dev")
    ap.add_argument("--password", default="demo1234!")
    a = ap.parse_args()
    asyncio.run(_main(a.email, a.password))


if __name__ == "__main__":
    main()
