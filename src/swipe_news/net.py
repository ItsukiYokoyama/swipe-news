"""Polite access to publishers: honour robots.txt, space out requests to the same site, and identify ourselves."""
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from . import __version__

UA_TOKEN = "swipe-news"
HEADERS = {"User-Agent": f"Mozilla/5.0 (compatible; {UA_TOKEN}/{__version__}; personal RSS reader)"}
HOST_INTERVAL_SEC = 2  # Gap between requests to the same site. Different sites are fetched in parallel
RETRIES = 3            # Retry only on transport errors (dropped connections, ...), never on HTTP responses like 403
_SECOND_LEVEL = ("co", "ne", "or", "go", "ac", "ed", "gr", "lg")


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS)


def site_of(host: str) -> str:
    """pc.watch.impress.co.jp → impress.co.jp. Subdomains usually share a server, so requests are grouped per site."""
    labels = host.split(":")[0].split(".")
    n = 3 if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-n:])


class HostGate:
    """Let requests to the same site through one at a time, at least `interval` seconds apart."""

    def __init__(self, interval: float = HOST_INTERVAL_SEC):
        self.interval = interval
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last: dict[str, float] = {}

    @asynccontextmanager
    async def __call__(self, url: str):
        site = site_of(urlsplit(url).netloc)
        loop = asyncio.get_running_loop()
        async with self.locks[site]:
            wait = self.last.get(site, -self.interval) + self.interval - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                yield
            finally:
                self.last[site] = loop.time()


class Fetcher:
    """robots.txt checks, per-site spacing and retries on transport errors. One instance per crawl."""

    def __init__(self, http: httpx.AsyncClient, gate: HostGate | None = None):
        self.http = http
        self.gate = gate or HostGate()
        self._robots: dict[str, RobotFileParser] = {}
        self._robot_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def get(self, url: str, **kw) -> httpx.Response:
        for attempt in range(RETRIES):
            try:
                async with self.gate(url):
                    return await self.http.get(url, follow_redirects=True, **kw)
            except httpx.TransportError:
                if attempt == RETRIES - 1:
                    raise
                await asyncio.sleep(1 + attempt)
        raise AssertionError("unreachable")

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robot_locks[origin]:  # Don't fetch the same robots.txt concurrently
            if origin not in self._robots:
                self._robots[origin] = await self._load_robots(origin)
        return self._robots[origin].can_fetch(UA_TOKEN, url)

    async def _load_robots(self, origin: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            r = await self.get(f"{origin}/robots.txt", timeout=10)
            if r.status_code in (401, 403):
                rp.disallow_all = True       # Not allowed to read it → treat everything as disallowed
            elif r.status_code >= 400:
                rp.allow_all = True          # No robots.txt → no restrictions
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp.disallow_all = True           # Can't check → don't fetch
        return rp
