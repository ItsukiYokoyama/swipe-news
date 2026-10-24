import asyncio
import json
from pathlib import Path

import pytest

from conftest import rss
from swipe_news import db, feeds, net, paths

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


def test_import_legacy_yaml():
    paths.LEGACY_FEEDS_FILE.write_text("""
feeds:
  - name: A
    url: https://a.example/feed
    genre: AI
    og_image: true
  - name: 要約
    url: https://gov.example/feed
    genre: 国内
    mode: ai_summary
  - name: 知らないジャンル
    url: https://b.example/feed
    genre: 消えたジャンル
""", encoding="utf-8")
    assert feeds.import_legacy_yaml() == 1
    [feed] = db.list_feeds()
    assert feed["name"] == "A" and feed["og_image"] and feed["source"] == "imported"
    assert not paths.LEGACY_FEEDS_FILE.exists()
    assert feeds.import_legacy_yaml() == 0
