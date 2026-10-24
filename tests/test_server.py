import pytest
from fastapi.testclient import TestClient

from conftest import rss
from swipe_news import crawler, server


@pytest.fixture
def client(monkeypatch):
    async def idle(*args, **kwargs):
        return {"status": "ok"}

    monkeypatch.setattr(crawler, "loop", idle)      # No crawl on startup
    monkeypatch.setattr(crawler, "run_once", idle)  # No crawl after adding a source
    with TestClient(server.app) as c:
        yield c


def test_index_and_config(client):
    assert "Swipe News" in client.get("/").text
    assert client.get("/api/config").json()["app"] == "swipe-news"
    assert client.get("/static/tailwind.css").status_code == 200


def test_add_feed_requires_agreement(client, web):
    web["https://news.example/robots.txt"] = (404, "text/plain", "")
    web["https://news.example/rss"] = (200, "application/rss+xml", rss("a"))
    body = {"url": "https://news.example/rss", "name": "ニュース", "genre": "AI"}
    assert client.post("/api/feeds", json=body).status_code == 400
    r = client.post("/api/feeds", json={**body, "agreed": True})
    assert r.status_code == 201
    feed = r.json()
    assert client.get("/api/feeds").json()[0]["name"] == "ニュース"
    assert client.patch(f"/api/feeds/{feed['id']}", json={"genre": "存在しない"}).status_code == 400
    assert client.patch(f"/api/feeds/{feed['id']}", json={"og_image": True}).json()["og_image"] is True
    assert client.delete(f"/api/feeds/{feed['id']}").status_code == 204
    assert client.get("/api/feeds").json() == []


def test_inspect_error_message(client, web):
    r = client.post("/api/feeds/inspect", json={"url": "notaurl"})
    assert r.status_code == 400 and "URL" in r.json()["detail"]


def test_action_validation(client):
    assert client.post("/api/news/x/action", json={"action": "keep"}).status_code == 422  # Actions from 0.3 are no longer accepted
    assert client.post("/api/news/x/action", json={"action": "open"}).status_code == 404


def test_settings_roundtrip(client):
    r = client.put("/api/settings", json={"mute_words": [" a ", "A", "b"], "hidden_genres": ["AI"]})
    assert r.json() == {"hidden_genres": ["AI"], "mute_words": ["a", "b"], "like_words": [], "update_check": True}
    assert client.put("/api/settings", json={"update_check": False}).json()["update_check"] is False
    assert client.get("/api/update").json()["enabled"] is False
    assert client.put("/api/settings", json={"hidden_genres": ["存在しない"]}).status_code == 400
