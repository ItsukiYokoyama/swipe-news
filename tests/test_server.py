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


def test_bulk_add_from_catalog_needs_no_fetch(client, web):
    # Catalog sources are added without fetching the feed (web has no pages registered)
    items = [{"url": f"https://news{i}.example/rss", "name": f"ニュース{i}", "genre": "AI",
              "source": "catalog", "catalog_id": f"n{i}"} for i in range(3)]
    assert client.post("/api/feeds/bulk", json={"feeds": items}).status_code == 400
    items.append({**items[0], "catalog_id": "dup"})  # Same name and URL: reported, the rest still added
    r = client.post("/api/feeds/bulk", json={"feeds": items, "agreed": True}).json()
    assert [f["name"] for f in r["added"]] == ["ニュース0", "ニュース1", "ニュース2"]
    assert len(r["errors"]) == 1 and r["errors"][0]["name"] == "ニュース0"
    assert all(f["og_image"] is False for f in client.get("/api/feeds").json())


def test_extension_folder(client, monkeypatch):
    from swipe_news import desktop
    opened = []
    monkeypatch.setattr(desktop, "reveal", opened.append)
    folder = client.get("/api/extension").json()["folder"]  # The source checkout has extension/
    assert folder and folder.endswith("extension")
    assert client.post("/api/extension/open").status_code == 403  # Other pages can't set the header
    assert client.post("/api/extension/open", headers={"X-Swipe-News": "1"}).status_code == 204
    assert [str(p) for p in opened] == [folder]


def test_install_info_and_open(client, monkeypatch, data_dir):
    from swipe_news import desktop
    opened = []
    monkeypatch.setattr(desktop, "open_folder", opened.append)
    info = client.get("/api/install").json()
    assert info["portable"] is False and info["start_menu"] is None  # A source checkout isn't the zip build
    assert info["data_dir"] == str(data_dir) and info["app_dir"].endswith("swipe_news")
    assert client.post("/api/install/open/data").status_code == 403
    assert client.post("/api/install/open/data", headers={"X-Swipe-News": "1"}).status_code == 204
    assert client.post("/api/install/open/start_menu", headers={"X-Swipe-News": "1"}).status_code == 404
    assert client.post("/api/install/open/other", headers={"X-Swipe-News": "1"}).status_code == 422
    assert opened == [data_dir]


def test_uninstall_endpoint(client):
    assert client.post("/api/uninstall", json={}).status_code == 403  # Other pages can't set the header
    r = client.post("/api/uninstall", json={}, headers={"X-Swipe-News": "1"})
    assert r.status_code == 400 and "zip" in r.json()["detail"]  # A source checkout can't uninstall itself


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
