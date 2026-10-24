import asyncio
import json

from swipe_news import __version__, db, settings, updates


def latest_json(version: str, url: str = "https://ditsuki.com/swipe-news/releases") -> tuple[int, str, str]:
    return 200, "application/json", json.dumps({"version": version, "url": url})


def test_is_newer_compares_numerically():
    assert updates.is_newer("1.2.10", "1.2.9")
    assert updates.is_newer("1.1", "1.0.9")
    assert not updates.is_newer("1.0.0", "1.0")
    assert not updates.is_newer("0.9.9", "1.0.0")


def test_reports_newer_version_and_caches_for_a_day(web):
    web[settings.UPDATE_URL] = latest_json("99.0.0")
    result = asyncio.run(updates.check())
    assert result["newer"] and result["latest"] == "99.0.0" and result["current"] == __version__
    assert result["url"] == "https://ditsuki.com/swipe-news/releases"
    web[settings.UPDATE_URL] = latest_json("100.0.0")
    assert asyncio.run(updates.check())["latest"] == "99.0.0"  # Not asked again within a day


def test_same_version_is_not_newer(web):
    web[settings.UPDATE_URL] = latest_json(__version__)
    assert asyncio.run(updates.check())["newer"] is False


def test_failure_keeps_previous_and_retries_later(web):
    web[settings.UPDATE_URL] = (500, "text/plain", "error")
    assert asyncio.run(updates.check())["latest"] is None
    cache = db.get_setting("update_cache")
    assert cache["checked_at"] < __import__("time").time() - updates.INTERVAL_SEC + updates.RETRY_SEC + 5


def test_bad_data_is_ignored(web):
    web[settings.UPDATE_URL] = (200, "application/json", json.dumps({"version": "<script>", "url": "javascript:x"}))
    assert asyncio.run(updates.check())["newer"] is False
    db.set_setting("update_cache", None)
    web[settings.UPDATE_URL] = latest_json("99.0.0", url="javascript:alert(1)")
    assert asyncio.run(updates.check())["url"] == updates.RELEASES_URL  # Only https links are used


def test_turned_off_makes_no_request(web):
    db.set_setting("update_check", False)
    web[settings.UPDATE_URL] = latest_json("99.0.0")
    result = asyncio.run(updates.check())
    assert result == {"enabled": False, "current": __version__, "latest": None, "newer": False, "url": None}
    assert db.get_setting("update_cache") is None
