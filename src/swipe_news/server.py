"""FastAPI app serving the UI (static/) and the API. Listens only on this PC (127.0.0.1; see desktop.py).

HTTPException messages are shown in the UI, so they are in Japanese like the rest of the UI.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, crawler, db, feeds, genre_ai, settings, taste, taxonomy
from .paths import STATIC_DIR

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    feeds.import_legacy_yaml()
    task = asyncio.create_task(crawler.loop(settings.CRAWL_INTERVAL_MIN))
    yield
    task.cancel()


app = FastAPI(title="Swipe News", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/config")
def config():
    return {"app": "swipe-news", "version": __version__, "catalog_url": settings.CATALOG_URL,
            "ai_genre": {"enabled": settings.AI_GENRE, "model": genre_ai.MODEL_NAME}}


@app.get("/api/genres")
def genres():
    """Categories and their sub-genres, for the filter chips."""
    return taxonomy.public()


# ---- Cards and actions


@app.get("/api/news/feed")
def news_feed(category: str | None = None, genre: str | None = None, limit: int = Query(10, ge=1, le=50)):
    if category and category not in taxonomy.CATEGORIES:
        raise HTTPException(400, f"category は {taxonomy.CATEGORIES} のいずれか")
    if genre and not taxonomy.category_of(genre):
        raise HTTPException(400, "genre は genres.yaml の小ジャンルのいずれか")
    return db.feed(category, genre, limit)


class Action(BaseModel):
    action: Literal["skip", "enough", "open"]  # ← not interested / ↑ headline is enough (not learned) / → open


def _prefs() -> dict:
    return {**db.preferences(taxonomy.load()), "words": taste.reacted_words()}


@app.post("/api/news/{article_id}/action")
def news_action(article_id: str, body: Action, background: BackgroundTasks):
    if not db.act(article_id, body.action):
        raise HTTPException(404, "記事がありません")
    background.add_task(taste.recompute)  # Reflect the new preference in the next cards right away
    return {"ok": True, "prefs": _prefs()}  # So the UI can redraw the charts immediately


@app.post("/api/news/{article_id}/undo")
def news_undo(article_id: str, background: BackgroundTasks):
    """Undo one card: mark the article unread again and drop that action from learning."""
    if not db.undo(article_id):
        raise HTTPException(404, "戻せる操作がありません")
    background.add_task(taste.recompute)
    return {"ok": True, "prefs": _prefs()}


@app.get("/api/news/opened")
def news_opened():
    return db.opened()


@app.get("/api/prefs")
def prefs():
    return _prefs()


@app.post("/api/crawl")
async def crawl_now():
    """Crawl now. Waits until done and returns the counts."""
    return await crawler.run_once()


# ---- UI settings


class Settings(BaseModel):
    hidden_genres: list[str] | None = None  # Sub-genres to hide
    mute_words: list[str] | None = None     # Hide articles containing these words
    like_words: list[str] | None = None     # Move articles containing these words forward


def _clean_words(words: list[str]) -> list[str]:
    seen, out = set(), []
    for w in (w.strip() for w in words):
        if w and w.lower() not in seen and len(w) <= 40:
            seen.add(w.lower())
            out.append(w)
    return out[:100]


@app.get("/api/settings")
def get_settings():
    return {k: db.get_setting(k, []) for k in ("hidden_genres", "mute_words", "like_words")}


@app.put("/api/settings")
def put_settings(body: Settings):
    """Only the fields that are sent are updated."""
    if body.hidden_genres is not None:
        unknown = set(body.hidden_genres) - set(taxonomy.genre_names())
        if unknown:
            raise HTTPException(400, f"知らない小ジャンル: {sorted(unknown)}")
        db.set_setting("hidden_genres", list(dict.fromkeys(body.hidden_genres)))
    for key in ("mute_words", "like_words"):
        if getattr(body, key) is not None:
            db.set_setting(key, _clean_words(getattr(body, key)))
    return get_settings()


# ---- News sources


@app.get("/api/feeds")
def list_feeds():
    return db.list_feeds()


@app.get("/api/feeds/catalog")
async def feed_catalog(refresh: bool = False):
    """The recommended list (ditsuki.com), with `added` set on sources already added."""
    try:
        catalog = await feeds.load_catalog(force=refresh)
    except feeds.FeedError as e:
        raise HTTPException(502, str(e)) from e
    added = {f["catalog_id"] for f in db.list_feeds() if f["catalog_id"]} | {f["url"] for f in db.list_feeds()}
    return {**catalog, "feeds": [{**f, "added": f["catalog_id"] in added or f["url"] in added}
                                 for f in catalog["feeds"]]}


class Inspect(BaseModel):
    url: str


@app.post("/api/feeds/inspect")
async def inspect_feed(body: Inspect):
    """Check a URL entered by hand (is it a feed, is it allowed by robots.txt)."""
    try:
        return await feeds.inspect(body.url)
    except feeds.FeedError as e:
        raise HTTPException(400, str(e)) from e


class NewFeed(BaseModel):
    url: str
    name: str
    genre: str
    mixed: bool = False
    og_image: bool = False
    terms_url: str | None = None
    site_url: str | None = None
    source: Literal["catalog", "manual"] = "manual"
    catalog_id: str | None = None
    # The user confirmed personal use and that they read this publisher's terms
    agreed: bool = False


@app.post("/api/feeds", status_code=201)
async def add_feed(body: NewFeed, background: BackgroundTasks):
    if not body.agreed:
        raise HTTPException(400, "個人で使うこと・利用規約を読んだことを確かめてから追加してください")
    try:
        feed = await feeds.add(**body.model_dump(exclude={"agreed"}))
    except feeds.FeedError as e:
        raise HTTPException(400, str(e)) from e
    background.add_task(crawler.run_once)  # Fetch the new source's articles right away
    return feed


class FeedChange(BaseModel):
    genre: str | None = None
    mixed: bool | None = None
    og_image: bool | None = None
    enabled: bool | None = None
    terms_url: str | None = None


@app.patch("/api/feeds/{feed_id}")
def update_feed(feed_id: int, body: FeedChange):
    if body.genre is not None and not taxonomy.category_of(body.genre):
        raise HTTPException(400, f"小ジャンルが正しくありません: {body.genre}")
    feed = db.update_feed(feed_id, **body.model_dump())
    if not feed:
        raise HTTPException(404, "メディアがありません")
    return feed


@app.delete("/api/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int):
    if not db.delete_feed(feed_id):
        raise HTTPException(404, "メディアがありません")
