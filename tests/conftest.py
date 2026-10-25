import os

# Before importing the package: tests don't use the model (CI has none) and keep data in a temporary folder
os.environ["SWIPE_NEWS_AI_GENRE"] = "false"
os.environ.setdefault("SWIPE_NEWS_DATA", os.path.join(os.path.dirname(__file__), ".data-unused"))

import httpx  # noqa: E402
import pytest  # noqa: E402

from swipe_news import db, net, paths  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """An empty data folder and database for each test."""
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "news.db")
    db.init()
    return tmp_path


@pytest.fixture
def web(monkeypatch):
    """Make net.client() a fake server returning registered pages: web["https://..."] = (status, content_type, body)."""
    pages: dict[str, tuple[int, str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        status, ctype, body = pages.get(str(request.url), (404, "text/plain", "not found"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    monkeypatch.setattr(net, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(net, "HOST_INTERVAL_SEC", 0)
    monkeypatch.setattr(net.HostGate.__init__, "__defaults__", (0,))
    return pages


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>テストのニュース</title><link>https://news.example/</link>
{items}
</channel></rss>"""


def rss(*titles: str, base: str = "https://news.example/a/") -> str:
    items = "".join(
        f"<item><title>{t}</title><link>{base}{i}</link><description>{t} の概要</description>"
        f"<pubDate>Fri, 23 Oct 2026 0{i % 10}:00:00 +0000</pubDate></item>" for i, t in enumerate(titles))
    return RSS.format(items=items)
