"""Project Finder: feed parsers, robots.txt gate, scoring, refresh service, sources and jobs API.

No network: sources are served by httpx.MockTransport using fixtures in each site's documented format."""

import dataclasses
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import select

from app.core.db import get_db
from app.main import app
from app.models import NotificationEvent, PFJob, PFSettings, PFSource, User
from app.services.project_finder import feeds, robots
from app.services.project_finder.errors import FeedError
from app.services.project_finder.refresh import refresh_user, rescore_user
from app.services.project_finder.scoring import score_job

P = "/api/v1/project-finder"
NOW = datetime.now(UTC)


def iso(days=0):
    return (NOW - timedelta(days=days)).isoformat()


# ------------------------------------------------------------------ fixtures
def wwr_xml():
    return f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Acme Corp: Senior QA Automation Engineer (Playwright)</title><link>https://weworkremotely.com/remote-jobs/acme-qa</link>
<guid>https://weworkremotely.com/remote-jobs/acme-qa</guid><pubDate>{format_datetime(NOW)}</pubDate><category>Programming</category>
<description><![CDATA[<p>We need <b>Playwright</b> and Python test automation.</p><script>alert(1)</script>]]></description></item>
<item><title>BigCo: Marketing Manager</title><link>https://weworkremotely.com/remote-jobs/bigco-mkt</link><pubDate>{format_datetime(NOW)}</pubDate>
<description>Run campaigns</description></item>
<item><title>Foo: WordPress Developer (Python optional)</title><link>https://weworkremotely.com/remote-jobs/foo-wp</link><pubDate>{format_datetime(NOW)}</pubDate>
<description>WordPress plugin work</description></item></channel></rss>""".encode()


def remoteok_json():
    return [
        {"legal": "https://remoteok.com terms: link back required"},
        {"id": 1, "position": "FastAPI Backend Developer", "company": "Beta", "tags": ["python", "fastapi"], "description": "<p>Build APIs</p>",
         "url": "https://remoteok.com/remote-jobs/1", "apply_url": "https://elsewhere.example/apply", "salary_min": 80000, "salary_max": 120000,
         "epoch": int((NOW - timedelta(days=2)).timestamp())},
        {"id": 2, "position": "Sales rep", "company": "Zed", "tags": ["sales"], "description": "sell", "url": "https://remoteok.com/remote-jobs/2"},
    ]  # fmt: skip


def remotive_json():
    return {"jobs": [
        {"id": 10, "title": "AI Document Processing Engineer", "company_name": "Gamma", "category": "Software Development", "tags": ["ai", "ocr"],
         "url": "https://remotive.com/remote-jobs/10", "publication_date": (NOW - timedelta(days=10)).replace(tzinfo=None).isoformat(),
         "candidate_required_location": "Worldwide", "salary": "", "description": "<p>OCR pipelines in python</p>"},
        {"id": 11, "title": "Barista", "company_name": "Coffee", "tags": [], "url": "https://remotive.com/remote-jobs/11", "description": "espresso"},
    ]}  # fmt: skip


HN_HITS = {"hits": [
    {"objectID": "900", "title": "Ask HN: Who is hiring? (October 2026)"},
    {"objectID": "901", "title": "Ask HN: Freelancer? Seeking freelancer? (October 2026)"},
    {"objectID": "902", "title": "Ask HN: Who wants to be hired? (October 2026)"},
]}  # fmt: skip


def hn_items():
    return {
        "900": {"children": [
            {"id": 111, "created_at": iso(), "text": "Gamma | Remote | QA Automation Engineer | $90k-$120k<p>We use Cypress and Playwright</p>"},
            {"id": 112, "created_at": iso(), "text": "Delta | Onsite only | Sales"},
            {"id": 113, "created_at": iso(), "text": None},
        ]},
        "901": {"children": [{"id": 121, "created_at": iso(), "text": "Epsilon | Remote | n8n automation freelancer"}]},
    }  # fmt: skip


def reddit_atom():
    return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>t3_abc</id><title>[HIRING] Python automation developer for n8n workflows - $50/hr</title><author><name>/u/boss</name></author>
<link href="https://www.reddit.com/r/forhire/comments/abc/x/"/><updated>{iso()}</updated><content type="html">&lt;p&gt;Need help&lt;/p&gt;</content></entry>
<entry><id>t3_def</id><title>[FOR HIRE] Designer available</title><link href="https://www.reddit.com/r/forhire/comments/def/y/"/><updated>{iso()}</updated></entry>
</feed>""".encode()


class Site:
    """MockTransport handler serving every feed; `robots` maps host -> (status, text)."""

    def __init__(self):
        self.robots: dict[str, tuple[int, str]] = {}
        self.fail: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append(url)
        host, path = req.url.host, req.url.path
        if path == "/robots.txt":
            status, text = self.robots.get(host, (404, ""))
            return httpx.Response(status, text=text)
        if host in self.fail:
            return httpx.Response(503)
        if host == "weworkremotely.com":
            return httpx.Response(200, content=wwr_xml())
        if host == "remoteok.com":
            return httpx.Response(200, json=remoteok_json())
        if host == "remotive.com":
            return httpx.Response(200, json=remotive_json())
        if host == "hn.algolia.com" and path.endswith("search_by_date"):
            return httpx.Response(200, json=HN_HITS)
        if host == "hn.algolia.com" and "/items/" in path:
            return httpx.Response(200, json=hn_items()[path.rsplit("/", 1)[1]])
        if host == "www.reddit.com":
            return httpx.Response(200, content=reddit_atom())
        return httpx.Response(404)


@pytest.fixture
def site(monkeypatch):
    robots.clear_cache()
    s = Site()
    monkeypatch.setattr(
        feeds,
        "make_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(s), follow_redirects=True),
    )
    yield s
    robots.clear_cache()


async def with_db():
    async for db in app.dependency_overrides[get_db]():
        return db


async def me(db):
    return (await db.execute(select(User))).scalars().one()


# ------------------------------------------------------------------ parsers
def test_wwr_parser_strips_html_and_splits_company():
    jobs = feeds.parse_wwr(wwr_xml())
    j = jobs[0]
    assert (j.company, j.title) == ("Acme Corp", "Senior QA Automation Engineer (Playwright)")
    assert (
        "alert(1)" not in j.description
        and "<" not in j.description
        and "Playwright and Python" in j.description
    )
    assert (
        j.url.startswith("https://weworkremotely.com/")
        and j.remote
        and j.tags == ["Programming"]
        and j.posted_at
    )


def test_remoteok_parser_skips_legal_notice_and_links_back():
    jobs = feeds.parse_remoteok(remoteok_json())
    assert [j.external_id for j in jobs] == ["1", "2"]
    j = jobs[0]
    assert j.url == "https://remoteok.com/remote-jobs/1"  # their page, not the apply URL
    assert (j.budget, j.budget_min, j.budget_max) == ("$80,000-$120,000/yr", 80000, 120000)
    with pytest.raises(FeedError):
        feeds.parse_remoteok({"not": "a list"})


def test_remotive_parser_handles_naive_dates_and_location():
    j = feeds.parse_remotive(remotive_json())[0]
    assert (
        j.posted_at
        and j.posted_at.tzinfo
        and "Location: Worldwide" in j.description
        and "ocr" in j.tags
    )
    with pytest.raises(FeedError):
        feeds.parse_remotive([])


def test_hn_parser_extracts_company_budget_remote():
    jobs = feeds.parse_hn_thread(hn_items()["900"])
    assert [j.external_id for j in jobs] == ["111", "112"]  # empty comment dropped
    a, b = jobs
    assert (
        a.company == "Gamma"
        and a.budget == "$90k-$120k"
        and (a.budget_min, a.budget_max) == (90000, 120000)
        and a.remote
    )
    assert a.url == "https://news.ycombinator.com/item?id=111" and b.remote is False


def test_reddit_parsers_keep_only_hiring_posts():
    atom = feeds.parse_reddit_atom(reddit_atom())
    assert (
        [j.external_id for j in atom] == ["t3_abc"]
        and atom[0].budget == "$50"
        and atom[0].company == "/u/boss"
    )
    api = feeds.parse_reddit_json({"data": {"children": [
        {"data": {"id": "x1", "title": "[Hiring] QA tester", "selftext": "pay $200", "permalink": "/r/forhire/comments/x1/", "author": "bob", "created_utc": 1_700_000_000}},
        {"data": {"id": "x2", "title": "[For Hire] me", "selftext": "", "permalink": "/r/forhire/comments/x2/"}},
    ]}})  # fmt: skip
    assert [j.external_id for j in api] == ["t3_x1"] and api[
        0
    ].url == "https://www.reddit.com/r/forhire/comments/x1/"


def test_malicious_or_broken_input():
    with pytest.raises(FeedError):
        feeds.parse_wwr(b"not xml at all")
    bomb = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(FeedError):  # defusedxml refuses entity declarations
        feeds.parse_wwr(bomb)
    assert feeds.safe_url("javascript:alert(1)") == "" and feeds.safe_url("data:text/html,x") == ""
    assert feeds.safe_url("https://ok.example/a") == "https://ok.example/a"
    assert feeds.html_to_text("<p>a&amp;b</p><style>x{}</style><li>one<li>two") == "a&b\n\none\ntwo"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Pay $80k-$120k per year", ("$80k-$120k", 80000, 120000, "USD")),
        ("€50 to €70 per hour", ("€50 to €70", 50, 70, "EUR")),
        ("£400/day", ("£400", 400, 400, "GBP")),
        ("We raised $20M in Series A", ("", None, None, "USD")),
        ("budget $1 coffee", ("", None, None, "USD")),
        ("no money here", ("", None, None, "USD")),
    ],
)
def test_extract_budget(text, expected):
    assert feeds.extract_budget(text) == expected


# ------------------------------------------------------------------ scoring
def cfg(**kw):
    c = PFSettings(
        skills=["python", "fastapi", "qa", "playwright", "n8n", "automation", "next.js"],
        include_keywords=[],
        exclude_keywords=[],
        min_store_score=15,
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def sc(c=None, **kw):
    base = dict(title="", description="", tags=[], remote=False, budget="", posted_at=None, now=NOW)
    return score_job(c or cfg(), **{**base, **kw})


def test_score_title_beats_body_and_components_add_up():
    title_hit, _, _ = sc(title="FastAPI developer")
    body_hit, _, _ = sc(title="Developer", description="we use FastAPI")
    assert title_hit == 20 and body_hit == 8
    s, reasons, matched = sc(
        title="QA Automation (Playwright)",
        description="python fastapi",
        remote=True,
        budget="$5k",
        posted_at=NOW,
    )
    assert matched == [
        "python",
        "fastapi",
        "qa",
        "playwright",
        "automation",
    ]  # order of your skills list
    assert (
        s == 70 + 8 + 8 + 4
    )  # skills (60 title + 16 body) capped at 70, + remote + fresh + budget
    assert (
        "Remote (+8)" in reasons
        and "Skills: python, fastapi, qa, playwright, automation (+70)" in reasons
    )


def test_score_word_boundaries_and_dotted_terms():
    assert (
        sc(title="Painting job")[0] == 0 and sc(title="Rain QAnon")[0] == 0
    )  # "ai"/"qa" inside other words
    assert sc(title="Next.js engineer")[0] == 20
    assert sc(title="Python3 dev")[0] == 0  # not the same token


def test_score_exclude_keyword_zeroes_and_irrelevant_is_capped():
    s, reasons, matched = sc(
        cfg(exclude_keywords=["wordpress"]), title="Python dev", description="WordPress site"
    )
    assert s == 0 and matched == [] and "Excluded keyword: wordpress" in reasons[0]
    s, _, matched = sc(title="Marketing manager", remote=True, budget="$9", posted_at=NOW)
    assert matched == [] and s <= 10  # remote + fresh + budget alone never make a job look good


def test_score_include_keywords_and_freshness():
    s, reasons, matched = sc(
        cfg(skills=[], include_keywords=["tester"]),
        title="Software tester",
        posted_at=NOW - timedelta(days=5),
    )
    assert s == 4 + 3 and matched == ["tester"] and any("this week" in r for r in reasons)
    assert sc(title="python", posted_at=NOW - timedelta(days=30))[0] == 20
    assert (
        sc(title="python", posted_at=NOW.replace(tzinfo=None))[0] == 28
    )  # naive datetimes (SQLite) are read as UTC


# ------------------------------------------------------------------ robots.txt
async def test_robots_rules(site):
    async with feeds.make_client() as c:
        site.robots["a.example"] = (200, "User-agent: *\nDisallow: /private\n")
        assert await robots.allowed(c, "https://a.example/public/x") is True
        assert await robots.allowed(c, "https://a.example/private/x") is False
        site.robots["b.example"] = (200, f"User-agent: {robots.AGENT}\nDisallow: /\n")
        assert await robots.allowed(c, "https://b.example/anything") is False
        assert await robots.allowed(c, "https://missing.example/x") is True  # 404 -> allowed
        site.robots["gone.example"] = (403, "")
        assert (
            await robots.allowed(c, "https://gone.example/x") is True
        )  # 4xx -> allowed (RFC 9309)
        site.robots["down.example"] = (503, "")
        with pytest.raises(FeedError, match="robots.txt"):
            await robots.allowed(c, "https://down.example/x")  # 5xx -> skip, and not cached
        site.robots["down.example"] = (404, "")
        assert await robots.allowed(c, "https://down.example/x") is True


async def test_polite_get_limits(site):
    async with feeds.make_client() as c:
        site.robots["weworkremotely.com"] = (200, "User-agent: *\nDisallow: /\n")
        with pytest.raises(FeedError, match="robots.txt"):
            await feeds.polite_get(c, "https://weworkremotely.com/remote-jobs.rss")
        assert not [u for u in site.calls if u.endswith(".rss")]  # never requested the feed itself
    big = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * (feeds.MAX_BYTES + 10))
        )
    )
    with pytest.raises(FeedError, match="too large"):
        await feeds.polite_get(big, "https://x.example/feed", check_robots=False)
    limited = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(FeedError, match="429"):
        await feeds.polite_get(limited, "https://x.example/feed", check_robots=False)


# ------------------------------------------------------------------ refresh service
async def test_refresh_stores_only_relevant_jobs_and_is_idempotent(auth_client, site):
    db = await with_db()
    user = await me(db)
    res = {r.key: r for r in await refresh_user(db, user, now=NOW)}
    assert {k: r.status for k, r in res.items()} == {
        k: "ok" for k in ("weworkremotely", "remoteok", "remotive", "hackernews", "reddit")
    }
    # relevant only: WWR 2 (QA role + "WordPress Developer (Python optional)"; Marketing is dropped), RemoteOK 1, Remotive 1, HN 2, Reddit 1
    assert (
        res["weworkremotely"].fetched == 3 and res["remoteok"].new == 1 and res["remotive"].new == 1
    )
    assert res["hackernews"].new == 2 and res["reddit"].new == 1
    assert not [
        u for u in site.calls if "/items/902" in u
    ]  # "Who wants to be hired?" is not fetched
    titles = {j.title for j in (await db.execute(select(PFJob))).scalars()}
    assert "Marketing Manager" not in titles and "Sales rep" not in titles

    wwr = (
        await db.execute(
            select(PFJob).where(PFJob.source_key == "weworkremotely", PFJob.company == "Acme Corp")
        )
    ).scalar_one()
    assert (
        wwr.fit_score == 86
        and wwr.remote
        and "Remote (+8)" in wwr.score_reasons
        and "<" not in wwr.description
    )

    # second run inside the interval: nothing is fetched at all
    calls = len(site.calls)
    again = {r.key: r for r in await refresh_user(db, user, now=NOW + timedelta(minutes=5))}
    assert {r.status for r in again.values()} == {"skipped"} and len(site.calls) == calls

    # later: fetched again, but nothing new; the user's decision survives
    wwr.status = "dismissed"
    await db.commit()
    later = {r.key: r for r in await refresh_user(db, user, now=NOW + timedelta(hours=7))}
    assert sum(r.new for r in later.values()) == 0
    assert (
        await db.execute(select(PFJob).where(PFJob.id == wwr.id))
    ).scalar_one().status == "dismissed"
    n_jobs = len((await db.execute(select(PFJob))).scalars().all())
    assert n_jobs == 7


async def test_refresh_respects_robots_pause_and_isolates_failures(auth_client, site, monkeypatch):
    db = await with_db()
    user = await me(db)
    site.robots["remoteok.com"] = (200, "User-agent: *\nDisallow: /api\n")
    site.fail.add("remotive.com")  # 503 on the feed itself
    monkeypatch.setitem(
        feeds.SPEC_BY_KEY,
        "hackernews",
        dataclasses.replace(feeds.SPEC_BY_KEY["hackernews"], fetch=_boom),
    )
    await refresh_user(db, user, now=NOW)  # create default rows
    rows = {s.key: s for s in (await db.execute(select(PFSource))).scalars()}
    rows["reddit"].status = "paused"
    for r in rows.values():
        r.last_checked_at = None
    await db.commit()
    res = {r.key: r for r in await refresh_user(db, user, now=NOW + timedelta(days=1))}
    assert res["remoteok"].status == "error" and "robots.txt" in res["remoteok"].message
    assert res["remotive"].status == "error" and "503" in res["remotive"].message
    assert res["hackernews"].status == "error" and res["hackernews"].message == "unexpected failure"
    assert res["reddit"].status == "paused"
    assert (
        res["weworkremotely"].status == "ok" and res["weworkremotely"].new == 0
    )  # already stored; others still ran
    assert rows["remoteok"].last_result.startswith("error: blocked by the site's robots.txt")
    assert rows["remoteok"].last_checked_at is not None  # failures are rate limited too


async def _boom(_client):
    raise RuntimeError("kaboom")


async def test_strong_matches_notify_once_per_hour(auth_client, site):
    db = await with_db()
    user = await me(db)
    await refresh_user(db, user, now=NOW)
    await db.commit()
    evs = (
        (await db.execute(select(NotificationEvent).where(NotificationEvent.type == "job_match")))
        .scalars()
        .all()
    )
    assert (
        len(evs) == 1
        and "strong project match" in evs[0].title
        and evs[0].url == "/project-finder/jobs"
    )


async def test_rescore_follows_settings(auth_client, site):
    db = await with_db()
    user = await me(db)
    await refresh_user(db, user, now=NOW)
    await db.commit()
    before = (await db.execute(select(PFJob).where(PFJob.company == "Beta"))).scalar_one().fit_score
    cfg_row = (await db.execute(select(PFSettings))).scalar_one()
    cfg_row.skills = ["cobol"]
    n = await rescore_user(db, user.id, now=NOW)
    after = (await db.execute(select(PFJob).where(PFJob.company == "Beta"))).scalar_one().fit_score
    assert n == 7 and before > after and after <= 10


# ------------------------------------------------------------------ API
async def test_sources_defaults_and_rules(auth_client):
    src = (await auth_client.get(f"{P}/sources")).json()
    assert len(src) == 10 and {s["kind"] for s in src} == {"feed", "manual"}
    names = [s["name"] for s in src]
    for want in [
        "Freelancer.com",
        "Contra",
        "PeoplePerHour",
        "We Work Remotely",
        "RemoteOK",
        "Remotive",
        "Wellfound",
        "LinkedIn contract jobs",
        "Reddit r/forhire",
        'Hacker News "Who is hiring"',
    ]:
        assert want in names
    assert (await auth_client.get(f"{P}/sources")).json() == src  # idempotent
    assert all(s["status"] == "active" and s["last_checked_at"] is None for s in src)
    manual = next(s for s in src if s["key"] == "contra")
    assert (
        await auth_client.patch(f"{P}/sources/{manual['id']}", json={"name": "x"})
    ).status_code == 400
    assert (await auth_client.delete(f"{P}/sources/{manual['id']}")).status_code == 400
    r = await auth_client.patch(
        f"{P}/sources/{manual['id']}", json={"status": "paused", "notes": "no leads"}
    )
    assert r.json()["status"] == "paused" and r.json()["notes"] == "no leads"
    r = await auth_client.post(f"{P}/sources/{manual['id']}/mark-checked")
    assert r.json()["last_checked_at"] and r.json()["last_result"] == "checked manually"


async def test_custom_sources(auth_client):
    r = await auth_client.post(
        f"{P}/sources", json={"name": "Local board", "url": "board.example.com/jobs"}
    )
    assert (
        r.status_code == 201
        and r.json()["url"] == "https://board.example.com/jobs"
        and r.json()["builtin"] is False
    )
    assert (
        await auth_client.post(f"{P}/sources", json={"name": "Bad", "url": "javascript:alert(1)"})
    ).status_code == 422
    assert (
        await auth_client.post(f"{P}/sources", json={"name": "", "url": "https://x.example"})
    ).status_code == 422
    assert (await auth_client.delete(f"{P}/sources/{r.json()['id']}")).status_code == 200
    assert len((await auth_client.get(f"{P}/sources")).json()) == 10


async def test_refresh_and_job_filters_through_api(auth_client, site):
    r = (await auth_client.post(f"{P}/jobs/refresh", json={})).json()
    assert {x["key"]: x["status"] for x in r}["remoteok"] == "ok" and sum(x["new"] for x in r) == 7
    src = {s["key"]: s for s in (await auth_client.get(f"{P}/sources")).json()}
    assert (
        src["remoteok"]["last_result"] == "ok: 2 fetched, 1 new"
        and src["remoteok"]["last_checked_at"]
    )
    # immediately again: rate-limited, harmless
    assert {x["status"] for x in (await auth_client.post(f"{P}/jobs/refresh", json={})).json()} == {
        "skipped"
    }

    jobs = (await auth_client.get(f"{P}/jobs")).json()
    assert len(jobs) == 7 and jobs == sorted(jobs, key=lambda j: -j["fit_score"])
    assert jobs[0]["source_name"] and jobs[0]["fit_score"] >= jobs[-1]["fit_score"]
    ok = next(j for j in jobs if j["source_key"] == "remoteok")
    assert (
        ok["url"] == "https://remoteok.com/remote-jobs/1" and ok["budget"] == "$80,000-$120,000/yr"
    )

    assert {
        j["source_key"] for j in (await auth_client.get(f"{P}/jobs?source=hackernews")).json()
    } == {"hackernews"}
    assert all(
        j["fit_score"] >= 70 for j in (await auth_client.get(f"{P}/jobs?min_score=70")).json()
    )
    kw = (await auth_client.get(f"{P}/jobs?keywords=n8n,cobol")).json()
    assert kw and all("n8n" in (j["title"] + j["description"]).lower() for j in kw)
    assert len((await auth_client.get(f"{P}/jobs?q=fastapi")).json()) == 1
    assert (
        await auth_client.get(f"{P}/jobs?remote=false")
    ).json() == []  # every stored fixture job is remote
    assert len((await auth_client.get(f"{P}/jobs?remote=true")).json()) == 7
    assert len((await auth_client.get(f"{P}/jobs?sort=date")).json()) == 7
    assert (await auth_client.get(f"{P}/jobs?min_score=101")).status_code == 422
    assert (
        await auth_client.post(f"{P}/jobs/refresh", json={"source": "contra"})
    ).status_code == 404

    # status workflow: dismissed jobs leave the default view but are still reachable
    r = await auth_client.patch(f"{P}/jobs/{ok['id']}", json={"status": "dismissed"})
    assert r.json()["status"] == "dismissed"
    assert len((await auth_client.get(f"{P}/jobs")).json()) == 6
    assert [j["id"] for j in (await auth_client.get(f"{P}/jobs?status=dismissed")).json()] == [
        ok["id"]
    ]
    assert (
        await auth_client.patch(f"{P}/jobs/{ok['id']}", json={"status": "weird"})
    ).status_code == 422


async def test_changing_skills_rescores_stored_jobs(auth_client, site):
    await auth_client.post(f"{P}/jobs/refresh", json={})
    top = (await auth_client.get(f"{P}/jobs?q=fastapi")).json()[0]["fit_score"]
    await auth_client.put(f"{P}/settings", json={"skills": ["cobol"]})
    assert (await auth_client.get(f"{P}/jobs?q=fastapi")).json()[0]["fit_score"] < top
    assert (await auth_client.post(f"{P}/jobs/rescore")).json()["rescored"] == 7


async def test_job_to_lead_is_idempotent_and_scoped(auth_client, client, site):
    await auth_client.post(f"{P}/jobs/refresh", json={})
    job = (await auth_client.get(f"{P}/jobs?q=fastapi")).json()[0]
    a = (await auth_client.post(f"{P}/jobs/{job['id']}/to-lead")).json()
    b = (await auth_client.post(f"{P}/jobs/{job['id']}/to-lead")).json()
    assert (
        a["id"] == b["id"]
        and a["business_name"] == "Beta"
        and a["source"] == "RemoteOK"
        and a["job_id"] == job["id"]
    )
    assert job["url"] in a["notes"]
    assert (await auth_client.get(f"{P}/jobs?q=fastapi")).json()[0]["status"] == "saved"
    assert len((await auth_client.get(f"{P}/leads")).json()) == 1

    r = await client.post(
        "/api/v1/auth/signup", json={"email": "b@example.com", "password": "password123"}
    )
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"{P}/jobs", headers=other)).json() == []
    assert (await client.post(f"{P}/jobs/{job['id']}/to-lead", headers=other)).status_code == 404
    assert (
        await client.patch(f"{P}/jobs/{job['id']}", json={"status": "saved"}, headers=other)
    ).status_code == 404
    # a lead may only link to a job the user owns
    bad = await client.post(
        f"{P}/leads", json={"business_name": "x", "job_id": job["id"]}, headers=other
    )
    assert bad.status_code == 404


async def test_reddit_uses_official_api_when_configured(auth_client, site, monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "reddit_client_id", "id")
    monkeypatch.setattr(s, "reddit_client_secret", "secret")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/access_token":
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok"})
        assert req.url.host == "oauth.reddit.com" and req.headers["authorization"] == "bearer tok"
        data = {
            "children": [
                {
                    "data": {
                        "id": "q1",
                        "title": "[Hiring] Python QA",
                        "selftext": "$300",
                        "permalink": "/r/forhire/comments/q1/",
                    }
                }
            ]
        }
        return httpx.Response(200, json={"data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        jobs = await feeds.fetch_reddit(c)
    assert [j.external_id for j in jobs] == ["t3_q1"]
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with pytest.raises(FeedError, match="credentials"):
        await feeds.fetch_reddit(bad)


async def test_exclude_keywords_keep_jobs_out_of_the_feed(auth_client, site):
    await auth_client.put(f"{P}/settings", json={"exclude_keywords": ["wordpress"]})
    await auth_client.post(f"{P}/jobs/refresh", json={})
    jobs = (await auth_client.get(f"{P}/jobs")).json()
    assert len(jobs) == 6 and not any("WordPress" in j["title"] for j in jobs)
