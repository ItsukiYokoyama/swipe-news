"""Crawl RSS feeds → store articles → classify sub-genres and compute preferences with the on-device model.

Rules for not burdening publishers and respecting their rights:
- Check robots.txt for every request and skip anything disallowed (net.Fetcher)
- One request at a time per site with a gap; feeds are downloaded only when ETag / Last-Modified changed
- RSS titles and summaries are stored unmodified (HTML tags are stripped). Article bodies are never fetched
- Images: only those in the RSS, or the og:image URL for sources with og_image enabled. Images themselves are never stored
- Articles older than RETENTION_DAYS (since publication) are deleted
"""
import asyncio
import calendar
import logging
from datetime import UTC, datetime, timedelta

import feedparser
from bs4 import BeautifulSoup

from . import db, genre_ai, net, settings, taste, taxonomy

log = logging.getLogger(__name__)

FEED_CONCURRENCY = 8  # Feeds processed concurrently (net.HostGate still serializes requests to the same site)

# ETag / Last-Modified per feed. If unchanged, the server answers 304 and no body is downloaded
_conditional: dict[str, dict] = {}


def html_to_text(s: str | None) -> str:
    return BeautifulSoup(s or "", "html.parser").get_text(" ", strip=True)


def published_at(entry) -> str:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    dt = datetime.fromtimestamp(calendar.timegm(t), UTC) if t else datetime.now(UTC)
    return dt.isoformat()


def feed_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key, []):
            if m.get("url"):
                return m["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image/") and enc.get("href"):
            return enc["href"]
    return None


async def og_image(fetcher: net.Fetcher, url: str) -> str | None:
    """Read only <meta property="og:image"> from the article page (the link-preview image provided by the publisher)."""
    if not await fetcher.allowed(url):
        return None
    try:
        r = await fetcher.get(url, timeout=15)
        r.raise_for_status()
    except Exception:
        return None
    if "html" not in r.headers.get("content-type", ""):
        return None
    tag = BeautifulSoup(r.content, "html.parser").find("meta", attrs={"property": "og:image"})
    img = (tag.get("content") or "").strip() if tag else ""
    # An image shared with other articles is a site-wide image (logo, ...), so skip it
    if not img.startswith("http") or db.image_in_use(img):
        return None
    return img


async def ingest_feed(fetcher: net.Fetcher, feed: dict) -> int:
    if not await fetcher.allowed(feed["url"]):
        log.warning("feed disallowed by robots.txt: %s", feed["name"])
        return 0
    cond = _conditional.get(feed["url"], {})
    headers = {k: v for k, v in (("If-None-Match", cond.get("etag")),
                                 ("If-Modified-Since", cond.get("last_modified"))) if v}
    try:
        r = await fetcher.get(feed["url"], headers=headers, timeout=15)
        if r.status_code == 304:
            return 0
        r.raise_for_status()
    except Exception as e:
        log.warning("could not fetch feed %s: %s", feed["name"], e)
        return 0
    _conditional[feed["url"]] = {"etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified")}
    entries = [e for e in feedparser.parse(r.content).entries if e.get("link")][:settings.MAX_NEW_PER_FEED]
    known = db.known_urls([e.link for e in entries])
    cutoff = datetime.now(UTC) - timedelta(days=settings.RETENTION_DAYS)
    category = taxonomy.category_of(feed["genre"])
    added = 0
    for e in entries:
        # Skip entries past the retention period (otherwise they would be deleted and re-fetched on every crawl)
        if e.link in known or datetime.fromisoformat(published_at(e)) < cutoff:
            continue
        title = html_to_text(e.get("title"))
        if not title:
            continue
        image = feed_image(e)
        if not image and feed["og_image"]:
            image = await og_image(fetcher, e.link)
        db.insert_article(url=e.link, title=title, description=html_to_text(e.get("summary")) or None,
                          image_url=image, media_name=feed["name"], published_at=published_at(e),
                          category=category, genre=feed["genre"])
        added += 1
    return added


async def ingest(feeds: list[dict]) -> int:
    sem = asyncio.Semaphore(FEED_CONCURRENCY)
    async with net.client() as http:
        fetcher = net.Fetcher(http)

        async def one(feed):
            async with sem:
                try:
                    return await ingest_feed(fetcher, feed)
                except Exception:
                    log.exception("error while processing feed: %s", feed["name"])
                    return 0

        return sum(await asyncio.gather(*(one(f) for f in feeds)))


def apply_feed_genres(feeds: list[dict]):
    """Apply each source's genre setting to existing articles, the action history and the weights."""
    db.apply_feed_genres({f["name"]: (taxonomy.category_of(f["genre"]), f["genre"]) for f in feeds},
                         taxonomy.genre_names())
    db.recompute_genre_weights()


async def update_vectors() -> int:
    """Embed articles that have no vector yet, then recompute affinities."""
    if not settings.AI_GENRE:
        return 0
    try:
        clf = await asyncio.to_thread(genre_ai.get, taxonomy.load())
    except Exception:
        log.exception("could not load the model; skipping preference learning")
        return 0
    rows = db.missing_vectors(genre_ai.EMBED_VERSION)
    if rows:
        x = await asyncio.to_thread(clf.embed_articles, rows)
        db.set_vectors([(r["id"], genre_ai.to_blob(v)) for r, v in zip(rows, x, strict=True)], genre_ai.EMBED_VERSION)
    await asyncio.to_thread(taste.recompute)
    return len(rows)


async def classify_genres(feeds: list[dict]) -> int:
    """Classify the sub-genre of unread articles. If the model is unavailable (e.g. download failed), keep the source genre."""
    if not settings.AI_GENRE:
        return 0
    try:
        clf = await asyncio.to_thread(genre_ai.get, taxonomy.load())
    except Exception:
        log.exception("could not load the genre model; showing source genres")
        return 0
    rows = db.unclassified(clf.version)
    if not rows:
        return 0
    mixed = {f["name"] for f in feeds if f["mixed"]}
    items = [{**r, "mixed": r["media_name"] in mixed} for r in rows]
    genres = await asyncio.to_thread(clf.classify, items)
    db.set_genres([(r["id"], g, taxonomy.category_of(g), clf.version) for r, g in zip(rows, genres, strict=True)])
    return sum(1 for r, g in zip(rows, genres, strict=True) if g != r["feed_genre"])


_lock = asyncio.Lock()
_again = False


async def run_once() -> dict:
    """Crawl every source. If asked again while running (a source was just added), crawl once more afterwards."""
    global _again
    if _lock.locked():
        _again = True
        return {"status": "already_running"}
    async with _lock:
        while True:
            _again = False
            result = await _crawl()
            if not _again:
                return result


async def _crawl() -> dict:
    feeds = []
    for f in db.list_feeds(enabled_only=True):
        if taxonomy.category_of(f["genre"]):
            feeds.append(f)
        else:  # Sub-genre removed from genres.yaml: skip until the user picks another one
            log.warning("%s: sub-genre %s is not in genres.yaml; skipping", f["name"], f["genre"])
    apply_feed_genres(feeds)
    purged = db.drop_unread_except([f["name"] for f in feeds]) + db.purge_older_than(settings.RETENTION_DAYS)
    added = await ingest(feeds)
    await update_vectors()
    moved = await classify_genres(feeds)
    log.info("crawl done: %d sources / %d new / %d re-classified / %d deleted",
             len(feeds), added, moved, purged)
    return {"status": "ok", "added": added, "genre_changed": moved, "purged": purged}


async def loop(interval_min: int):
    while True:
        try:
            await run_once()
        except Exception:
            log.exception("error during crawl")
        await asyncio.sleep(interval_min * 60)
