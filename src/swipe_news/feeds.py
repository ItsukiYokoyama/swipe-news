"""News sources: the recommended list (ditsuki.com) and checking URLs entered by hand. The app starts with no sources;
the user adds every one of them.

Every source is added only after the user confirms personal use and that they have read the publisher's terms (UI and API).
Messages in FeedError are shown to the user, so they are in Japanese like the rest of the UI.
"""
import logging
import sqlite3
import time
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from . import db, net, settings, taxonomy

log = logging.getLogger(__name__)

CATALOG_FORMAT = "swipe-news-catalog"
CATALOG_VERSION = 1
CATALOG_MAX_BYTES = 1_000_000
CATALOG_CACHE_SEC = 600
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/xml", "text/xml")


class FeedError(ValueError):
    """An error whose message is shown to the user."""


def check_url(url: str) -> str:
    url = (url or "").strip()
    if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
        raise FeedError("http:// か https:// で始まる URL を入れてください")
    return url


def check_genre(genre: str) -> str:
    if not taxonomy.category_of(genre):
        raise FeedError(f"小ジャンルが正しくありません: {genre}")
    return genre


# ---- Recommended list

_catalog_cache: tuple[float, dict] | None = None


def parse_catalog(data: dict) -> dict:
    """Validate the recommended-list JSON. Malformed items and unknown sub-genres are dropped (catalog/README.md)."""
    if not isinstance(data, dict) or data.get("format") != CATALOG_FORMAT:
        raise FeedError("おすすめの一覧の形式が違います")
    if data.get("version") != CATALOG_VERSION:
        raise FeedError("おすすめの一覧の版がこのアプリと合いません。アプリを新しくしてください")
    feeds, seen = [], set()
    for item in data.get("feeds") or []:
        try:
            feed = {
                "catalog_id": str(item["id"]),
                "name": str(item["name"]).strip(),
                "url": check_url(item["url"]),
                "site_url": item.get("site_url"),
                "genre": check_genre(item["genre"]),
                "mixed": bool(item.get("mixed")),
                "terms_url": item.get("terms_url"),
                "note": item.get("note"),
                "checked": item.get("checked"),
            }
        except (KeyError, TypeError, FeedError) as e:
            log.warning("skipping catalog item: %s (%s)", item, e)
            continue
        if feed["catalog_id"] in seen or not feed["name"]:
            continue
        seen.add(feed["catalog_id"])
        feeds.append(feed)
    return {"updated": data.get("updated"), "notice": data.get("notice"), "feeds": feeds}


async def load_catalog(force: bool = False) -> dict:
    global _catalog_cache
    if not force and _catalog_cache and time.monotonic() - _catalog_cache[0] < CATALOG_CACHE_SEC:
        return _catalog_cache[1]
    try:
        async with net.client() as http:
            r = await http.get(settings.CATALOG_URL, timeout=10, follow_redirects=True)
        r.raise_for_status()
        if len(r.content) > CATALOG_MAX_BYTES:
            raise FeedError("おすすめの一覧が大きすぎます")
        catalog = parse_catalog(r.json())
    except FeedError:
        raise
    except (httpx.HTTPError, ValueError) as e:
        raise FeedError(f"おすすめの一覧を読み込めませんでした ({settings.CATALOG_URL})") from e
    catalog["source"] = settings.CATALOG_URL
    _catalog_cache = (time.monotonic(), catalog)
    return catalog


# ---- URLs entered by hand


def _parse_feed(content: bytes):
    parsed = feedparser.parse(content)
    return parsed if parsed.get("version") and parsed.entries is not None else None


async def inspect(url: str) -> dict:
    """Check that the URL is an RSS / Atom feed. For a web page, look for the feed it links to.
    Anything disallowed by robots.txt cannot be added."""
    url = check_url(url)
    async with net.client() as http:
        fetcher = net.Fetcher(http)
        for _ in range(2):  # At most two steps: page → the feed it links to
            if not await fetcher.allowed(url):
                raise FeedError("このサイトの robots.txt で、取得が拒否されています")
            try:
                r = await fetcher.get(url, timeout=15)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise FeedError(f"URL を開けませんでした ({e.__class__.__name__})") from e
            url = str(r.url)
            parsed = _parse_feed(r.content)
            if parsed:
                return {
                    "url": url,
                    "title": (parsed.feed.get("title") or "").strip() or urlsplit(url).netloc,
                    "site_url": parsed.feed.get("link"),
                    "entries": len(parsed.entries),
                    "sample": [e.get("title", "") for e in parsed.entries[:3]],
                }
            link = BeautifulSoup(r.content, "html.parser").find(
                "link", rel="alternate", type=lambda t: (t or "").split(";")[0].strip() in FEED_TYPES)
            if not link or not link.get("href"):
                break
            url = urljoin(url, link["href"])
    raise FeedError("RSS / Atom フィードが見つかりませんでした。フィードの URL を入れてください")


async def add(*, url: str, name: str, genre: str, mixed: bool = False, og_image: bool = False,
              terms_url: str | None = None, site_url: str | None = None, source: str = "manual",
              catalog_id: str | None = None) -> dict:
    """Add the source. URLs entered by hand are checked first (is it a feed, robots.txt); sources from the
    recommended list are added as they are (the list was checked when it was made, and the crawler checks
    robots.txt before every fetch)."""
    check_genre(genre)
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise FeedError("名前は 1〜60 文字で入れてください")
    if source == "catalog":
        found = {"url": check_url(url), "site_url": None}
    else:
        found = await inspect(url)
    try:
        return db.add_feed(name=name, url=found["url"], site_url=site_url or found["site_url"], genre=genre,
                           mixed=mixed, og_image=og_image, terms_url=terms_url or None, source=source,
                           catalog_id=catalog_id)
    except sqlite3.IntegrityError as e:
        raise FeedError("同じ名前か URL のメディアが、もう追加されています") from e
