"""Fetch and normalise jobs from sources that publish a public RSS/Atom feed or API.

Only sources that offer one are fetched (We Work Remotely, RemoteOK, Remotive, Hacker News "Who is
hiring", Reddit r/forhire). Every unauthenticated request passes the robots.txt gate, uses a
descriptive User-Agent, caps the response size and is rate-limited per source (`min_interval_hours`).
Other sources (Freelancer.com, Contra, ...) are manual links - nothing is scraped.

Parsers are pure functions (bytes/JSON in, RawJob out) so they are testable without a network."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree as DET

from app.core.config import get_settings
from app.services.project_finder import robots
from app.services.project_finder.errors import FeedError

MAX_BYTES = 8_000_000
MAX_DESC = 8000
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


@dataclass
class RawJob:
    external_id: str
    title: str
    url: str = ""
    company: str = ""
    description: str = ""
    budget: str = ""
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str = "USD"
    posted_at: datetime | None = None
    remote: bool = True
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- text helpers
class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str | None, limit: int = MAX_DESC) -> str:
    """HTML (or plain text) -> plain text. The UI only ever renders text, never feed HTML."""
    if not html:
        return ""
    p = _Text()
    try:
        p.feed(html)
        p.close()
        text = "".join(p.out)
    except Exception:  # malformed markup: fall back to a crude strip
        text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


def safe_url(url: str | None) -> str:
    """Feed-supplied links are rendered as <a href>, so only http(s) survives."""
    u = (url or "").strip()
    p = urlparse(u)
    return u[:1000] if p.scheme in ("http", "https") and p.netloc else ""


def parse_date(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, int | float):
            return datetime.fromtimestamp(float(v), UTC)
        s = str(v).strip()
        try:
            d = parsedate_to_datetime(s)  # RFC 822 (RSS)
        except (TypeError, ValueError):
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


_MONEY = re.compile(
    r"(?P<cur>[$€£])\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s?(?P<ak>[kK])?"
    r"(?:\s?(?:-|–|—|to)\s?[$€£]?\s?(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?P<bk>[kK])?)?"
)
_CUR = {"$": "USD", "€": "EUR", "£": "GBP"}


def _num(v: str, k: str | None) -> float:
    return float(v.replace(",", "")) * (1000 if k else 1)


def extract_budget(text: str) -> tuple[str, float | None, float | None, str]:
    """Best-effort first money amount/range in free text ("$80k-$120k", "€50/hr"). Ignores $5M-style
    company sizes. Returns (as written, min, max, currency)."""
    for m in _MONEY.finditer(text):
        tail = text[m.end() : m.end() + 2]
        if tail[:1] in ("m", "M", "b", "B") and not tail[1:2].isalnum():
            continue  # "$20M funding"
        lo = _num(m["a"], m["ak"])
        hi = _num(m["b"], m["bk"]) if m["b"] else lo
        if m["b"] and not m["bk"] and m["ak"] and hi < lo:  # "$80k-120" -> 120k
            hi *= 1000
        if lo < 5:
            continue
        return m.group(0).strip(), min(lo, hi), max(lo, hi), _CUR[m["cur"]]
    return "", None, None, "USD"


def _xml(body: bytes) -> Any:
    try:
        return DET.fromstring(body)
    except Exception:
        raise FeedError("feed was not valid XML") from None


# ---------------------------------------------------------------- parsers
def parse_wwr(body: bytes) -> list[RawJob]:
    """We Work Remotely RSS. Titles look like "Company: Job title"."""
    out: list[RawJob] = []
    for it in _xml(body).iter("item"):
        raw_title = (it.findtext("title") or "").strip()
        link = safe_url(it.findtext("link"))
        if not raw_title:
            continue
        company, sep, title = raw_title.partition(": ")
        if not sep:
            company, title = "", raw_title
        desc = it.findtext(f"{CONTENT}encoded") or it.findtext("description")
        out.append(
            RawJob(
                external_id=(it.findtext("guid") or link or raw_title).strip()[:300],
                title=title.strip(), company=company.strip(), url=link,
                description=html_to_text(desc), posted_at=parse_date(it.findtext("pubDate")),
                tags=[c.text.strip() for c in it.findall("category") if c.text],
            )
        )  # fmt: skip
    return out


def parse_remoteok(data: Any) -> list[RawJob]:
    """RemoteOK JSON API: first element is a legal notice; the rest are jobs.
    Their terms require linking back to RemoteOK - `url` is their page, never the apply URL."""
    if not isinstance(data, list):
        raise FeedError("unexpected RemoteOK response")
    out: list[RawJob] = []
    for j in data:
        if not isinstance(j, dict) or not j.get("id") or not j.get("position"):
            continue
        lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
        budget = f"${int(lo):,}-${int(hi):,}/yr" if lo and hi else ""
        out.append(
            RawJob(
                external_id=str(j["id"]), title=str(j["position"]), company=str(j.get("company") or ""),
                url=safe_url(j.get("url")), description=html_to_text(j.get("description")),
                budget=budget, budget_min=float(lo) or None, budget_max=float(hi) or None,
                posted_at=parse_date(j.get("epoch") or j.get("date")),
                tags=[str(t) for t in j.get("tags") or []],
            )
        )  # fmt: skip
    return out


def parse_remotive(data: Any) -> list[RawJob]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FeedError("unexpected Remotive response")
    out: list[RawJob] = []
    for j in data["jobs"]:
        if not isinstance(j, dict) or not j.get("id") or not j.get("title"):
            continue
        loc = j.get("candidate_required_location")
        desc = html_to_text(j.get("description"))
        budget = str(j.get("salary") or "")
        _, lo, hi, cur = extract_budget(budget) if budget else ("", None, None, "USD")
        out.append(
            RawJob(
                external_id=str(j["id"]), title=str(j["title"]), company=str(j.get("company_name") or ""),
                url=safe_url(j.get("url")), description=(f"Location: {loc}\n\n{desc}" if loc else desc)[:MAX_DESC],
                budget=budget[:120], budget_min=lo, budget_max=hi, currency=cur,
                posted_at=parse_date(j.get("publication_date")),
                tags=[str(t) for t in (j.get("tags") or []) + [j.get("category") or ""] if t],
            )
        )  # fmt: skip
    return out


def parse_hn_thread(thread: Any) -> list[RawJob]:
    """Top-level comments of an Algolia HN item (one "Who is hiring?" / "Seeking freelancer?" thread)."""
    if not isinstance(thread, dict):
        raise FeedError("unexpected Hacker News response")
    out: list[RawJob] = []
    for c in thread.get("children") or []:
        text = html_to_text(c.get("text")) if isinstance(c, dict) else ""
        if not text or not c.get("id"):
            continue
        first = text.split("\n", 1)[0].strip()
        company = first.split("|", 1)[0].strip()[:200] if "|" in first else ""
        lower = text.lower()
        budget, lo, hi, cur = extract_budget(text)
        out.append(
            RawJob(
                external_id=str(c["id"]), title=first[:300] or "Hacker News post", company=company,
                url=f"https://news.ycombinator.com/item?id={c['id']}", description=text,
                budget=budget, budget_min=lo, budget_max=hi, currency=cur,
                posted_at=parse_date(c.get("created_at")),
                remote="remote" in lower and "no remote" not in lower and "onsite only" not in lower,
            )
        )  # fmt: skip
    return out


def _is_hiring_post(title: str) -> bool:
    t = title.lower()
    return "hiring" in t and "for hire" not in t


def parse_reddit_atom(body: bytes) -> list[RawJob]:
    out: list[RawJob] = []
    for e in _xml(body).iter(f"{ATOM}entry"):
        title = (e.findtext(f"{ATOM}title") or "").strip()
        if not title or not _is_hiring_post(title):
            continue
        link = e.find(f"{ATOM}link")
        text = html_to_text(e.findtext(f"{ATOM}content"))
        budget, lo, hi, cur = extract_budget(f"{title}\n{text}")
        out.append(
            RawJob(
                external_id=(e.findtext(f"{ATOM}id") or title).strip()[:300], title=title[:300],
                company=(e.findtext(f"{ATOM}author/{ATOM}name") or "").strip(),
                url=safe_url(link.get("href") if link is not None else ""), description=text,
                budget=budget, budget_min=lo, budget_max=hi, currency=cur,
                posted_at=parse_date(e.findtext(f"{ATOM}updated")),
            )
        )  # fmt: skip
    return out


def parse_reddit_json(data: Any) -> list[RawJob]:
    try:
        posts = [c["data"] for c in data["data"]["children"]]
    except (KeyError, TypeError):
        raise FeedError("unexpected Reddit response") from None
    out: list[RawJob] = []
    for p in posts:
        title = str(p.get("title") or "").strip()
        if not title or not p.get("id") or not _is_hiring_post(title):
            continue
        text = html_to_text(p.get("selftext"))
        budget, lo, hi, cur = extract_budget(f"{title}\n{text}")
        out.append(
            RawJob(
                external_id=f"t3_{p['id']}", title=title[:300], company=f"u/{p.get('author') or ''}".rstrip("/"),
                url=safe_url(f"https://www.reddit.com{p.get('permalink') or ''}"), description=text,
                budget=budget, budget_min=lo, budget_max=hi, currency=cur,
                posted_at=parse_date(p.get("created_utc")),
            )
        )  # fmt: skip
    return out


# ---------------------------------------------------------------- fetching
def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        headers={"User-Agent": get_settings().pf_user_agent},
        follow_redirects=True,
        max_redirects=3,
    )


async def polite_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    check_robots: bool = True,
    headers: dict[str, str] | None = None,
) -> bytes:
    if check_robots and not await robots.allowed(client, url):
        raise FeedError("blocked by the site's robots.txt - not fetched")
    try:
        async with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 429:
                raise FeedError("the site asked us to slow down (HTTP 429) - will retry later")
            if r.status_code >= 400:
                raise FeedError(f"the site returned HTTP {r.status_code}")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise FeedError("response too large - skipped")
            return bytes(buf)
    except httpx.HTTPError as e:
        raise FeedError(f"network error ({type(e).__name__})") from None


def _json(body: bytes) -> Any:
    import json

    try:
        return json.loads(body)
    except ValueError:
        raise FeedError("response was not valid JSON") from None


Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[RawJob]]]


async def fetch_wwr(c: httpx.AsyncClient) -> list[RawJob]:
    return parse_wwr(await polite_get(c, "https://weworkremotely.com/remote-jobs.rss"))


async def fetch_remoteok(c: httpx.AsyncClient) -> list[RawJob]:
    return parse_remoteok(_json(await polite_get(c, "https://remoteok.com/api")))


async def fetch_remotive(c: httpx.AsyncClient) -> list[RawJob]:
    return parse_remotive(
        _json(await polite_get(c, "https://remotive.com/api/remote-jobs?limit=200"))
    )


async def fetch_hn(c: httpx.AsyncClient) -> list[RawJob]:
    """Latest "Who is hiring?" and "Freelancer? Seeking freelancer?" threads by `whoishiring`,
    through the public Algolia HN API."""
    found = _json(
        await polite_get(
            c,
            "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=6",
        )
    )
    ids: list[str] = []
    for h in found.get("hits", []) if isinstance(found, dict) else []:
        t = str(h.get("title") or "").lower()
        if ("who is hiring" in t or "seeking freelancer" in t) and h.get("objectID"):
            ids.append(str(h["objectID"]))
    jobs: list[RawJob] = []
    for oid in ids[:2]:  # the newest of each kind
        if not oid.isdigit():
            continue
        jobs += parse_hn_thread(
            _json(await polite_get(c, f"https://hn.algolia.com/api/v1/items/{oid}"))
        )
    return jobs


async def fetch_reddit(c: httpx.AsyncClient) -> list[RawJob]:
    """Official OAuth API when REDDIT_CLIENT_ID/SECRET are set; otherwise the public RSS feed,
    which is only used if robots.txt allows it."""
    s = get_settings()
    if s.reddit_client_id and s.reddit_client_secret:
        try:
            r = await c.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(s.reddit_client_id, s.reddit_client_secret),
                data={"grant_type": "client_credentials"},
            )
            token = r.json().get("access_token") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            token = None
        if not token:
            raise FeedError("Reddit rejected the API credentials")
        body = await polite_get(
            c, "https://oauth.reddit.com/r/forhire/new?limit=100&raw_json=1",
            check_robots=False, headers={"Authorization": f"bearer {token}"},
        )  # fmt: skip
        return parse_reddit_json(_json(body))
    return parse_reddit_atom(
        await polite_get(c, "https://www.reddit.com/r/forhire/new/.rss?limit=100")
    )


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    url: str  # human-facing page
    min_interval_hours: float = 0  # 0 = manual source (no fetcher)
    fetch: Fetcher | None = None
    hint: str = ""


SPECS: list[SourceSpec] = [
    SourceSpec("weworkremotely", "We Work Remotely", "https://weworkremotely.com/", 3, fetch_wwr),
    SourceSpec("remoteok", "RemoteOK", "https://remoteok.com/", 3, fetch_remoteok, "Jobs link back to RemoteOK, as their terms require."),
    SourceSpec("remotive", "Remotive", "https://remotive.com/", 6, fetch_remotive, "Remotive asks for at most 4 requests a day, so this refreshes every 6 hours."),
    SourceSpec("hackernews", 'Hacker News "Who is hiring"', "https://news.ycombinator.com/submitted?id=whoishiring", 6, fetch_hn, 'Also reads the monthly "Freelancer? Seeking freelancer?" thread.'),
    SourceSpec("reddit", "Reddit r/forhire", "https://www.reddit.com/r/forhire/", 3, fetch_reddit, "Reads [Hiring] posts. Uses the official API if REDDIT_CLIENT_ID/SECRET are set, else RSS when robots.txt allows."),
    SourceSpec("freelancer", "Freelancer.com", "https://www.freelancer.com/jobs/", hint="Manual: no free public job feed. Open the site and filter by your skills."),
    SourceSpec("contra", "Contra", "https://contra.com/opportunities", hint="Manual: open the link. Contra charges freelancers no commission."),
    SourceSpec("peopleperhour", "PeoplePerHour", "https://www.peopleperhour.com/freelance-jobs", hint="Manual: open the link and filter by category."),
    SourceSpec("wellfound", "Wellfound", "https://wellfound.com/jobs", hint="Manual: open the link and filter by contract / remote."),
    SourceSpec("linkedin", "LinkedIn contract jobs", "https://www.linkedin.com/jobs/search/?f_JT=C&f_WT=2&keywords=QA%20automation", hint="Manual: this link is pre-filtered to Contract + Remote. Edit the keywords in the URL."),
]  # fmt: skip
SPEC_BY_KEY = {s.key: s for s in SPECS}
