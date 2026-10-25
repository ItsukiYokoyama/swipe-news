import asyncio
import json
from pathlib import Path

import pytest

from conftest import rss
from swipe_news import db, feeds, net

CATALOG_FILE = Path(__file__).resolve().parent.parent / "catalog" / "feeds.json"


def test_repository_catalog_is_valid():
    """The list published on ditsuki.com matches this app's format and genres."""
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    parsed = feeds.parse_catalog(data)
    assert len(parsed["feeds"]) == len(data["feeds"]) > 0
    assert len({f["catalog_id"] for f in parsed["feeds"]}) == len(parsed["feeds"])


def test_parse_catalog_skips_bad_items():
    data = {"format": "swipe-news-catalog", "version": 1, "feeds": [
        {"id": "ok", "name": "OK", "url": "https://ok.example/feed", "genre": "AI"},
        {"id": "bad-genre", "name": "X", "url": "https://x.example/feed", "genre": "存在しない"},
        {"id": "bad-url", "name": "Y", "url": "ftp://y.example/feed", "genre": "AI"},
        {"name": "no id", "url": "https://z.example/feed", "genre": "AI"},
    ]}
    assert [f["catalog_id"] for f in feeds.parse_catalog(data)["feeds"]] == ["ok"]


@pytest.mark.parametrize("data", [{}, {"format": "other", "version": 1}, {"format": "swipe-news-catalog", "version": 2}])
def test_parse_catalog_rejects_other_formats(data):
    with pytest.raises(feeds.FeedError):
        feeds.parse_catalog(data)


def test_inspect_finds_feed_from_page(web):
    web["https://news.example/robots.txt"] = (404, "text/plain", "")
    web["https://news.example/"] = (200, "text/html", '<link rel="alternate" type="application/rss+xml" href="/rss">')
    web["https://news.example/rss"] = (200, "application/rss+xml", rss("一つ目", "二つ目"))
    found = asyncio.run(feeds.inspect("https://news.example/"))
    assert found["url"] == "https://news.example/rss"
    assert found["title"] == "テストのニュース"
    assert found["entries"] == 2


def test_inspect_respects_robots(web):
    web["https://news.example/robots.txt"] = (200, "text/plain", f"User-agent: {net.UA_TOKEN}\nDisallow: /")
    with pytest.raises(feeds.FeedError, match="robots.txt"):
        asyncio.run(feeds.inspect("https://news.example/rss"))


def test_inspect_rejects_non_feed(web):
    web["https://news.example/robots.txt"] = (404, "text/plain", "")
    web["https://news.example/page"] = (200, "text/html", "<html><body>hello</body></html>")
    with pytest.raises(feeds.FeedError, match="見つかりません"):
        asyncio.run(feeds.inspect("https://news.example/page"))


def test_add_rejects_duplicates(web):
    web["https://news.example/robots.txt"] = (404, "text/plain", "")
    web["https://news.example/rss"] = (200, "application/rss+xml", rss("a"))
    asyncio.run(feeds.add(url="https://news.example/rss", name="ニュース", genre="AI"))
    with pytest.raises(feeds.FeedError, match="もう追加"):
        asyncio.run(feeds.add(url="https://news.example/rss", name="別の名前", genre="AI"))


def test_starts_with_no_sources_even_with_old_feeds_yaml(data_dir, monkeypatch):
    # Sources are only ever added by the user; a feeds.yaml left by an old version is ignored
    (data_dir / "feeds.yaml").write_text("feeds:\n  - name: A\n    url: https://a.example/feed\n    genre: AI\n", encoding="utf-8")
    from fastapi.testclient import TestClient

    from swipe_news import crawler, server

    async def idle(*args, **kwargs):
        return {"status": "ok"}

    monkeypatch.setattr(crawler, "loop", idle)
    with TestClient(server.app) as c:
        assert c.get("/api/feeds").json() == []
    assert db.list_feeds() == []
