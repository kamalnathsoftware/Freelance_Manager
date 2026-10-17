"""robots.txt gate for unauthenticated feed fetches (RFC 9309 semantics).

- robots.txt missing / any 4xx  -> everything is allowed
- 5xx or network error          -> treated as "do not fetch right now" (not cached, retried next run)
- otherwise                     -> the parsed rules for our user agent"""

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.services.project_finder.errors import FeedError

AGENT = "FreelanceManager-ProjectFinder"
TTL_SECONDS = 12 * 3600
_cache: dict[str, tuple[float, RobotFileParser | None]] = {}  # None = allow all


def clear_cache() -> None:
    _cache.clear()


async def allowed(client: httpx.AsyncClient, url: str) -> bool:
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    hit = _cache.get(origin)
    if hit is None or time.monotonic() - hit[0] > TTL_SECONDS:
        try:
            r = await client.get(f"{origin}/robots.txt", timeout=10)
        except httpx.HTTPError:
            raise FeedError("could not read robots.txt - skipped to be safe") from None
        if r.status_code >= 500:
            raise FeedError(f"robots.txt unavailable (HTTP {r.status_code}) - skipped to be safe")
        parser: RobotFileParser | None = None
        if r.status_code < 400:
            parser = RobotFileParser()
            parser.parse(r.text.splitlines()[:5000])
        hit = (time.monotonic(), parser)
        _cache[origin] = hit
    parser = hit[1]
    return True if parser is None else parser.can_fetch(AGENT, url)
