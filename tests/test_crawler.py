import asyncio

from conftest import rss
from swipe_news import crawler, db, net


def test_site_of_groups_subdomains():
    assert net.site_of("pc.watch.impress.co.jp") == "impress.co.jp"
    assert net.site_of("news.yahoo.co.jp") == "yahoo.co.jp"
    assert net.site_of("gigazine.net") == "gigazine.net"


def test_run_once_ingests_enabled_feeds(web):
    web["https://news.example/robots.txt"] = (404, "text/plain", "")
    web["https://news.example/rss"] = (200, "application/rss+xml", rss("<b>見出し</b>", "二つ目"))
    web["https://off.example/robots.txt"] = (404, "text/plain", "")
    web["https://off.example/rss"] = (200, "application/rss+xml", rss("止めたメディア", base="https://off.example/a/"))
    db.add_feed(name="ニュース", url="https://news.example/rss", genre="国内", source="manual")
    off = db.add_feed(name="止めた", url="https://off.example/rss", genre="国内", source="manual")
    db.update_feed(off["id"], enabled=False)
    crawler._conditional.clear()

    result = asyncio.run(crawler.run_once())

    assert result["added"] == 2
    cards = db.feed(limit=10)
    assert {c["title"] for c in cards} == {"見出し", "二つ目"}  # Only HTML tags are stripped
    assert all(c["category"] == "社会" and c["media_name"] == "ニュース" for c in cards)


def test_run_once_requested_while_running_crawls_again(monkeypatch):
    calls = []

    async def crawl():
        calls.append(1)
        if len(calls) == 1:
            assert (await crawler.run_once())["status"] == "already_running"  # e.g. a source added meanwhile
        return {"status": "ok"}

    monkeypatch.setattr(crawler, "_crawl", crawl)
    assert asyncio.run(crawler.run_once())["status"] == "ok"
    assert len(calls) == 2


def test_run_once_skips_feed_blocked_by_robots(web):
    web["https://news.example/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /rss")
    web["https://news.example/rss"] = (200, "application/rss+xml", rss("a"))
    db.add_feed(name="ニュース", url="https://news.example/rss", genre="国内", source="manual")
    crawler._conditional.clear()
    assert asyncio.run(crawler.run_once())["added"] == 0
