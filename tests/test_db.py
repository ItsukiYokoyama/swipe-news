import sqlite3
from datetime import UTC, datetime, timedelta

from swipe_news import db, paths


def add_article(n: int, genre: str = "AI", category: str = "テクノロジー", hours_ago: float = 1, media: str = "M"):
    db.insert_article(url=f"https://x.example/{n}", title=f"記事{n}", description=None, image_url=None,
                      media_name=media, published_at=(datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(),
                      category=category, genre=genre)
    with db.connect() as conn:
        return conn.execute("SELECT id FROM articles WHERE url = ?", (f"https://x.example/{n}",)).fetchone()["id"]


def test_init_sets_schema_version():
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_feed_orders_by_age_and_hides_genres():
    old = add_article(1, hours_ago=20)
    new = add_article(2, hours_ago=1)
    sports = add_article(3, genre="スポーツ", category="エンタメ", hours_ago=0.5)
    assert [c["id"] for c in db.feed()] == [sports, new, old]
    db.set_setting("hidden_genres", ["スポーツ"])
    assert sports not in [c["id"] for c in db.feed()]


def test_mute_and_like_words():
    a = add_article(1, hours_ago=1)
    b = add_article(2, hours_ago=10)
    db.set_setting("like_words", ["記事2"])
    assert [c["id"] for c in db.feed()][0] == b  # A favorite word moves the article 24 hours forward
    db.set_setting("mute_words", ["記事1"])
    assert a not in [c["id"] for c in db.feed()]


def test_act_and_undo_update_weights_and_revision():
    ids = [add_article(i, genre="AI" if i < 4 else "科学") for i in range(8)]
    for i in ids[:4]:
        db.act(i, "open")
    for i in ids[4:]:
        db.act(i, "skip")
    with db.connect() as conn:
        weights = {r["genre"]: r["weight"] for r in conn.execute("SELECT * FROM genre_weights")}
    assert weights["AI"] > 0 > weights["科学"]
    before = db.preferences(())["version"]
    assert db.undo(ids[0])
    assert db.preferences(())["version"] > before
    assert ids[0] in [c["id"] for c in db.feed(limit=50)]


def test_enough_is_neutral():
    a = add_article(1)
    db.act(a, "enough")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM genre_weights").fetchone()[0] == 0
    assert db.training_vectors() == []


def test_feeds_crud_and_delete_drops_unread():
    feed = db.add_feed(name="M", url="https://m.example/feed", genre="AI", source="manual")
    assert feed["enabled"] and not feed["og_image"]
    unread = add_article(1, media="M")
    opened = add_article(2, media="M")
    db.act(opened, "open")
    assert db.update_feed(feed["id"], og_image=True)["og_image"]
    assert db.delete_feed(feed["id"])
    ids = {c["id"] for c in db.opened()}
    assert opened in ids
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM articles WHERE id = ?", (unread,)).fetchone() is None


def test_migrates_0_3_database(tmp_path):
    """A 0.3 database (with AI summary columns and per-category weights) migrates, keeping articles and actions."""
    paths.DB_PATH.unlink()
    conn = sqlite3.connect(paths.DB_PATH)
    conn.executescript("""
        CREATE TABLE articles (id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, description TEXT,
            image_url TEXT, media_name TEXT NOT NULL, mode TEXT NOT NULL, license TEXT, license_url TEXT,
            published_at TEXT NOT NULL, source_text TEXT, catchphrase TEXT, summary_json TEXT, visual_json TEXT,
            category TEXT NOT NULL, genre TEXT, feed_genre TEXT, genre_by TEXT, genre_ver TEXT, vec BLOB, vec_ver TEXT,
            affinity REAL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, user_state TEXT, acted_at TEXT,
            created_at TEXT NOT NULL);
        CREATE INDEX idx_articles_status ON articles(status, published_at);
        CREATE TABLE category_weights (category TEXT PRIMARY KEY, weight REAL NOT NULL DEFAULT 0);
        CREATE TABLE actions (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, action TEXT NOT NULL,
            category TEXT NOT NULL, media_name TEXT, article_id TEXT, genre TEXT, vec BLOB);
        INSERT INTO articles (id, url, title, media_name, mode, published_at, category, genre, status, created_at,
                              user_state)
            VALUES ('a1', 'https://x/1', 'old', 'M', 'reader', '2026-10-20T00:00:00+00:00', '社会', '国内', 'done',
                    '2026-10-20', 'keep');
        INSERT INTO actions (at, action, category, media_name, article_id, genre)
            VALUES ('2026-10-20', 'keep', '社会', 'M', 'a1', '国内');
    """)
    conn.commit()
    conn.close()
    db.init()
    with db.connect() as conn:
        cols = db._columns(conn, "articles")
        assert not {"mode", "status", "summary_json"} & cols
        assert conn.execute("SELECT title FROM articles").fetchone()["title"] == "old"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'category_weights'").fetchone() is None
    assert db.preferences([{"category": "社会", "genres": []}])["total"]["open"] == 1  # keep is counted as open
