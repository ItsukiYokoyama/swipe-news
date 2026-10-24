"""SQLite storage and the card ordering."""
import json
import math
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    description  TEXT,                   -- RSS summary (shown unmodified)
    image_url    TEXT,                   -- URL of the RSS image or og:image (images are never stored)
    media_name   TEXT NOT NULL,          -- feeds.name
    published_at TEXT NOT NULL,          -- ISO 8601 (UTC)
    category     TEXT NOT NULL,          -- Category
    genre        TEXT,                   -- Sub-genre (from the model, or the source setting)
    feed_genre   TEXT,                   -- Sub-genre set on the source
    genre_by     TEXT,                   -- What decided genre: feed / ai
    genre_ver    TEXT,                   -- Version of the model and hints used (unread articles are re-classified when it changes)
    vec          BLOB,                   -- Embedding of title + summary (float16 × 256), for preference learning
    vec_ver      TEXT,
    affinity     REAL,                   -- Preference affinity (+ when close to opened articles, − when close to skipped ones)
    user_state   TEXT,                   -- NULL=unread / skip / enough / open (keep / seen from 0.3 may remain)
    acted_at     TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_unread ON articles(user_state, published_at);

-- Sub-genre weights, computed from the action history (recompute_genre_weights)
CREATE TABLE IF NOT EXISTS genre_weights (
    genre  TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 0
);

-- UI settings. value is JSON
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Action history (for learning and the charts). Holds no article text, so it is kept when articles are deleted
CREATE TABLE IF NOT EXISTS actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    action     TEXT NOT NULL,
    category   TEXT NOT NULL,
    genre      TEXT,
    media_name TEXT,
    article_id TEXT,
    vec        BLOB                      -- Vector of the article (so learning still works after the article is deleted)
);

-- News sources (RSS / Atom feeds), added by the user from the recommended list or by URL
CREATE TABLE IF NOT EXISTS feeds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,     -- Becomes the articles' media_name
    url        TEXT NOT NULL UNIQUE,
    site_url   TEXT,
    genre      TEXT NOT NULL,            -- Sub-genre
    mixed      INTEGER NOT NULL DEFAULT 0,  -- 1: general-interest source (the model assigns genres freely)
    og_image   INTEGER NOT NULL DEFAULT 0,  -- 1: show the article page's og:image
    terms_url  TEXT,                     -- Terms of use / RSS terms page
    source     TEXT NOT NULL,            -- catalog (recommended list) / manual (entered URL) / imported (feeds.yaml from 0.3)
    catalog_id TEXT,
    enabled    INTEGER NOT NULL DEFAULT 1,
    added_at   TEXT NOT NULL
);
"""
SCHEMA_VERSION = 1

# Hours of recency gained per weight point
HOURS_PER_WEIGHT = 6
# Hours of recency gained per affinity point (affinities are roughly −0.07 to +0.07 in practice)
HOURS_PER_AFFINITY = 200
# Hours of recency gained by articles containing a favorite word
HOURS_FOR_LIKE_WORD = 24
# Mix in one "something different" card (ignoring preferences, under 2 days old) every N cards
EXPLORE_EVERY = 6
EXPLORE_MIN_AFFINITY = -0.03  # Don't mix in articles the topic learning clearly dislikes

# Actions. open (and keep / seen from 0.3) are positive, skip is negative.
# enough (headline is enough) and unkeep say nothing about taste, so they are not learned
ACTIONS = ("skip", "enough", "open")
POSITIVE = ("open", "keep", "seen")
NEUTRAL = ("enough", "unkeep")

# A sub-genre's weight reflects how much more often its articles are opened compared with the overall rate.
# A simple sum pinned every genre to the lower limit for users who skip most articles
WEIGHT_LIMIT = 3
WEIGHT_SCALE = 1.5   # Twice the overall rate → +1.5, half → −1.5
PRIOR_ACTIONS = 5    # Genres with few actions are pulled toward the overall rate by this many pseudo-actions
OPEN_VOTES = 2       # An opened article was actually read, so it counts as two votes


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(paths.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def init():
    paths.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        legacy = version == 0 and "mode" in _columns(conn, "articles")
        if legacy:
            _migrate_from_0_3(conn)
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _migrate_from_0_3(conn):
    """Drop what 0.4 no longer uses from a 0.3 database (AI summary columns, per-category weights). Keeps articles and actions."""
    conn.execute("DROP INDEX IF EXISTS idx_articles_status")
    for col in ("mode", "license", "license_url", "source_text", "catchphrase", "summary_json", "visual_json",
                "status", "attempts"):
        if col in _columns(conn, "articles"):
            conn.execute(f"ALTER TABLE articles DROP COLUMN {col}")
    conn.execute("DROP TABLE IF EXISTS category_weights")


# ---- Settings


def get_setting(key: str, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value):
    with connect() as conn:
        conn.execute("""INSERT INTO app_settings (key, value) VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                     (key, json.dumps(value, ensure_ascii=False)))


# ---- News sources

FEED_FIELDS = ("name", "url", "site_url", "genre", "mixed", "og_image", "terms_url", "source", "catalog_id", "enabled")


def _feed(r: sqlite3.Row) -> dict:
    return {**dict(r), "mixed": bool(r["mixed"]), "og_image": bool(r["og_image"]), "enabled": bool(r["enabled"])}


def list_feeds(enabled_only: bool = False) -> list[dict]:
    where = "WHERE enabled = 1" if enabled_only else ""
    with connect() as conn:
        return [_feed(r) for r in conn.execute(f"SELECT * FROM feeds {where} ORDER BY id")]


def get_feed(feed_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)).fetchone()
    return _feed(r) if r else None


def add_feed(**feed) -> dict:
    """Raises sqlite3.IntegrityError if a source with the same name or URL exists."""
    values = {k: feed.get(k) for k in FEED_FIELDS}
    values["enabled"] = 1 if values["enabled"] is None else int(values["enabled"])
    values["mixed"], values["og_image"] = int(bool(values["mixed"])), int(bool(values["og_image"]))
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO feeds ({', '.join(values)}, added_at) VALUES ({', '.join('?' * len(values))}, ?)",
            [*values.values(), _now()])
        feed_id = cur.lastrowid
    return get_feed(feed_id)


def update_feed(feed_id: int, **changes) -> dict | None:
    allowed = {k: (int(v) if isinstance(v, bool) else v) for k, v in changes.items()
               if k in ("genre", "mixed", "og_image", "enabled", "terms_url") and v is not None}
    if allowed:
        with connect() as conn:
            conn.execute(f"UPDATE feeds SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
                         [*allowed.values(), feed_id])
    return get_feed(feed_id)


def delete_feed(feed_id: int) -> bool:
    """Remove a source and its unread articles (articles acted on and the action history are kept)."""
    with connect() as conn:
        row = conn.execute("SELECT name FROM feeds WHERE id = ?", (feed_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        conn.execute("DELETE FROM articles WHERE media_name = ? AND user_state IS NULL", (row["name"],))
    return True


def drop_unread_except(media_names: list[str]) -> int:
    """Delete unread articles of sources no longer fetched (removed or disabled). Articles acted on are kept."""
    marks = ",".join("?" * len(media_names)) or "''"
    with connect() as conn:
        return conn.execute(f"DELETE FROM articles WHERE user_state IS NULL AND media_name NOT IN ({marks})",
                            media_names).rowcount


# ---- Storing articles


def known_urls(urls: list[str]) -> set[str]:
    if not urls:
        return set()
    with connect() as conn:
        q = f"SELECT url FROM articles WHERE url IN ({','.join('?' * len(urls))})"
        return {r["url"] for r in conn.execute(q, urls)}


def image_in_use(image_url: str) -> bool:
    """An image already used by another article is treated as a site-wide image (logo, ...)."""
    with connect() as conn:
        return conn.execute("SELECT 1 FROM articles WHERE image_url = ? LIMIT 1", (image_url,)).fetchone() is not None


def insert_article(*, url, title, description, image_url, media_name, published_at, category, genre):
    """genre is the source's sub-genre; the model's classification overwrites it later via set_genres."""
    with connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO articles
               (id, url, title, description, image_url, media_name, published_at, category, genre, feed_genre,
                genre_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'feed', ?)""",
            (str(uuid.uuid4()), url, title, description, image_url, media_name, published_at, category, genre, genre,
             _now()))


def purge_older_than(days: int) -> int:
    """Delete articles a fixed number of days after publication, so other publishers' content doesn't pile up."""
    with connect() as conn:
        return conn.execute("DELETE FROM articles WHERE julianday('now') - julianday(published_at) > ?",
                            (days,)).rowcount


def apply_feed_genres(feed_genres: dict[str, tuple[str, str]], valid_genres: list[str]):
    """Apply source settings (name → (category, sub-genre)) to existing articles and actions. Idempotent.
    Articles classified by the model are left alone unless their sub-genre no longer exists."""
    marks = ",".join("?" * len(valid_genres)) or "''"
    with connect() as conn:
        for media, (category, genre) in feed_genres.items():
            conn.execute("UPDATE articles SET feed_genre = ? WHERE media_name = ? AND feed_genre IS NOT ?",
                         (genre, media, genre))
            conn.execute(f"""UPDATE articles SET category = ?, genre = ?, genre_by = 'feed', genre_ver = NULL
                             WHERE media_name = ?
                               AND (genre_by IS NOT 'ai' OR genre NOT IN ({marks}))
                               AND (genre IS NOT ? OR category IS NOT ?)""",
                         (category, genre, media, *valid_genres, genre, category))
            # Actions keep the genre they had when taken; only missing or removed genres fall back to the source genre
            conn.execute(f"""UPDATE actions SET category = ?, genre = ?
                             WHERE media_name = ? AND (genre IS NULL OR genre NOT IN ({marks}))""",
                         (category, genre, media, *valid_genres))


# ---- Genre classification and preference learning


def unclassified(version: str, limit: int = 2000) -> list[dict]:
    """Unread articles not yet classified (or classified by an older version). Acted-on articles keep their genre."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, description, feed_genre, media_name FROM articles
               WHERE user_state IS NULL AND feed_genre IS NOT NULL AND genre_ver IS NOT ?
               ORDER BY published_at DESC LIMIT ?""", (version, limit)).fetchall()
    return [dict(r) for r in rows]


def set_genres(results: list[tuple[str, str, str, str]]):
    """[(article id, sub-genre, category, version)]. genre_by stays "feed" when it matches the source genre."""
    with connect() as conn:
        conn.executemany(
            """UPDATE articles SET genre = ?, category = ?, genre_ver = ?,
                      genre_by = CASE WHEN feed_genre = ? THEN 'feed' ELSE 'ai' END
               WHERE id = ? AND user_state IS NULL""",
            [(g, c, v, g, i) for i, g, c, v in results])


def missing_vectors(version: str, limit: int = 3000) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, description FROM articles WHERE vec IS NULL OR vec_ver IS NOT ?
               ORDER BY published_at DESC LIMIT ?""", (version, limit)).fetchall()
    return [dict(r) for r in rows]


def set_vectors(results: list[tuple[str, bytes]], version: str):
    with connect() as conn:
        conn.executemany("UPDATE articles SET vec = ?, vec_ver = ? WHERE id = ?",
                         [(v, version, i) for i, v in results])
        # Copy vectors into the action history too (for actions taken before the article had a vector)
        conn.execute("""UPDATE actions SET vec = (SELECT a.vec FROM articles a WHERE a.id = actions.article_id)
                        WHERE vec IS NULL AND article_id IN (SELECT id FROM articles WHERE vec IS NOT NULL)""")


def unread_with_vectors() -> list[tuple[str, bytes]]:
    with connect() as conn:
        return [(r["id"], r["vec"]) for r in conn.execute(
            "SELECT id, vec FROM articles WHERE user_state IS NULL AND vec IS NOT NULL")]


def _last_actions(conn, column: str) -> dict[str, tuple]:
    """Last learnable action per article: {article id: (action, value of column)}."""
    last = {}
    for r in conn.execute(f"""SELECT article_id, action, {column} FROM actions
                              WHERE {column} IS NOT NULL AND action NOT IN ({",".join("?" * len(NEUTRAL))})
                              ORDER BY id""", NEUTRAL):
        last[r["article_id"]] = (r["action"], r[column])
    return last


def training_vectors() -> list[tuple[int, bytes]]:
    """For preference learning: [(+1 positive / -1 negative, vector)]."""
    with connect() as conn:
        last = _last_actions(conn, "vec")
    return [(1 if action in POSITIVE else -1, vec) for action, vec in last.values()]


def set_affinities(results: list[tuple[str, float]]):
    with connect() as conn:
        conn.executemany("UPDATE articles SET affinity = ? WHERE id = ?", [(a, i) for i, a in results])


def acted_titles() -> list[tuple[str, str]]:
    """Titles and actions of acted-on articles still stored. Actions that are not learned are excluded."""
    marks = ",".join("?" * len(NEUTRAL))
    with connect() as conn:
        return [(r["title"], r["user_state"]) for r in conn.execute(
            f"SELECT title, user_state FROM articles WHERE user_state IS NOT NULL AND user_state NOT IN ({marks})",
            NEUTRAL)]


def _recompute_genre_weights(conn):
    last = _last_actions(conn, "genre")
    votes = [(genre, action in POSITIVE, OPEN_VOTES if action == "open" else 1) for action, genre in last.values()]
    total = sum(v for _, _, v in votes)
    pos = sum(v for _, p, v in votes if p)
    conn.execute("DELETE FROM genre_weights")
    if not total or not pos:
        return
    base = pos / total
    per: dict[str, list[int]] = {}
    for genre, p, v in votes:
        c = per.setdefault(genre, [0, 0])
        c[0] += v if p else 0
        c[1] += v
    rows = []
    for genre, (gp, gn) in per.items():
        rate = (gp + PRIOR_ACTIONS * base) / (gn + PRIOR_ACTIONS)
        rows.append((genre, round(max(-WEIGHT_LIMIT, min(WEIGHT_LIMIT, WEIGHT_SCALE * math.log2(rate / base))), 2)))
    conn.executemany("INSERT INTO genre_weights (genre, weight) VALUES (?, ?)", rows)


def recompute_genre_weights():
    with connect() as conn:
        _recompute_genre_weights(conn)


# ---- Cards


def feed(category: str | None = None, genre: str | None = None, limit: int = 10) -> list[dict]:
    """Unread articles ordered by age in hours minus bonuses for sub-genre weight, affinity and favorite words."""
    where = "a.user_state IS NULL"
    params: list = []
    if category:
        where += " AND a.category = ?"
        params.append(category)
    if genre:
        where += " AND a.genre = ?"
        params.append(genre)
    hidden = get_setting("hidden_genres", [])
    if hidden:
        where += f" AND (a.genre IS NULL OR a.genre NOT IN ({','.join('?' * len(hidden))}))"
        params.extend(hidden)
    # Hide articles whose title or summary contains a muted word (case-insensitive)
    text = "lower(a.title || ' ' || COALESCE(a.description, ''))"
    for w in get_setting("mute_words", []):
        where += f" AND instr({text}, lower(?)) = 0"
        params.append(w)
    likes = get_setting("like_words", [])
    like_hit = " OR ".join(f"instr({text}, lower(?)) > 0" for _ in likes) or "0"
    q = f"""
        SELECT a.* FROM articles a
        LEFT JOIN genre_weights w ON w.genre = a.genre
        WHERE {where}
        ORDER BY (julianday('now') - julianday(a.published_at)) * 24
                 - COALESCE(w.weight, 0) * {HOURS_PER_WEIGHT}
                 - COALESCE(a.affinity, 0) * {HOURS_PER_AFFINITY}
                 - (CASE WHEN {like_hit} THEN {HOURS_FOR_LIKE_WORD} ELSE 0 END)
        LIMIT ?
    """
    with connect() as conn:
        rows = conn.execute(q, [*params, *likes, limit]).fetchall()
        out = [_card(r) for r in rows]
        if category or genre:
            return out
        # Occasionally mix in new articles from genres that usually sink (otherwise a genre could never recover).
        # Never mix in clearly disliked topics, hidden genres or muted words
        shown = [r["id"] for r in rows]
        marks = ",".join("?" * len(shown)) or "''"
        explore = conn.execute(f"""
            SELECT a.* FROM articles a WHERE {where} AND a.id NOT IN ({marks})
              AND COALESCE(a.affinity, 0) >= {EXPLORE_MIN_AFFINITY}
              AND julianday('now') - julianday(a.published_at) < 2
            ORDER BY RANDOM() LIMIT ?""", [*params, *shown, max(1, limit // EXPLORE_EVERY)]).fetchall()
    for i, r in enumerate(explore):
        out.insert(min(len(out), (i + 1) * EXPLORE_EVERY - 1), {**_card(r), "explore": True})
    return out[:limit]


def _card(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in ("id", "title", "url", "description", "image_url", "media_name", "published_at",
                              "category", "genre", "genre_by", "feed_genre")}


def opened(limit: int = 50) -> list[dict]:
    """Recently opened articles (most recent first)."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM articles WHERE user_state = 'open' ORDER BY acted_at DESC LIMIT ?",
                            (limit,)).fetchall()
    return [_card(r) for r in rows]


def act(article_id: str, action: str) -> bool:
    """Record a swipe. Returns False if the article doesn't exist."""
    with connect() as conn:
        row = conn.execute("SELECT category, genre, media_name, user_state, vec FROM articles WHERE id = ?",
                           (article_id,)).fetchone()
        if not row:
            return False
        if row["user_state"] == action:  # Count the same action on the same card only once
            return True
        now = _now()
        conn.execute(
            "INSERT INTO actions (at, action, category, genre, media_name, article_id, vec) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, action, row["category"], row["genre"], row["media_name"], article_id, row["vec"]))
        conn.execute("UPDATE articles SET user_state = ?, acted_at = ? WHERE id = ?", (action, now, article_id))
        if action not in NEUTRAL:
            _recompute_genre_weights(conn)
        _bump_revision(conn)
    return True


def undo(article_id: str) -> bool:
    """Undo: mark the article unread and remove its last action from the history (and learning)."""
    with connect() as conn:
        row = conn.execute("SELECT user_state FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row or row["user_state"] is None:
            return False
        last = conn.execute("SELECT MAX(id) FROM actions WHERE article_id = ?", (article_id,)).fetchone()[0]
        if last is not None:
            conn.execute("DELETE FROM actions WHERE id = ?", (last,))
        conn.execute("UPDATE articles SET user_state = NULL, acted_at = NULL WHERE id = ?", (article_id,))
        _recompute_genre_weights(conn)
        _bump_revision(conn)
    return True


def _bump_revision(conn):
    """Revision number for the charts. Only ever increases, even when an undo removes an action (the UI redraws on change)."""
    conn.execute("""INSERT INTO app_settings (key, value)
                    VALUES ('prefs_rev', (SELECT COALESCE(MAX(id), 0) + 1 FROM actions))
                    ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1""")


# ---- Charts


def preferences(taxonomy, recent: int = 30) -> dict:
    """Data for the charts. taxonomy is taxonomy.load(); version is a monotonically increasing revision."""
    merged = {"keep": "open", "seen": "open"}  # keep / seen from 0.3 are counted as open

    def tally(rows, key):
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            a = merged.get(r["action"], r["action"])
            bucket = out.setdefault(r[key], {})
            bucket[a] = bucket.get(a, 0) + r["n"]
        return out

    with connect() as conn:
        last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM actions").fetchone()[0]
        rev = conn.execute("SELECT value FROM app_settings WHERE key = 'prefs_rev'").fetchone()
        weights = {r["genre"]: r["weight"] for r in conn.execute("SELECT * FROM genre_weights")}
        by_cat = tally(conn.execute("SELECT category, action, COUNT(*) n FROM actions GROUP BY category, action"),
                       "category")
        by_genre = tally(conn.execute(
            "SELECT genre, action, COUNT(*) n FROM actions WHERE genre IS NOT NULL GROUP BY genre, action"), "genre")
        rows = conn.execute(
            """SELECT id, at, action, category, genre, media_name, article_id FROM actions
               WHERE action != 'unkeep' ORDER BY id DESC LIMIT ?""", (recent,)).fetchall()
    groups = [{
        "category": t["category"],
        **{a: by_cat.get(t["category"], {}).get(a, 0) for a in ACTIONS},
        "genres": [{"genre": g["name"], "short": g["short"], "weight": weights.get(g["name"], 0),
                    **{a: by_genre.get(g["name"], {}).get(a, 0) for a in ACTIONS}} for g in t["genres"]],
    } for t in taxonomy]
    return {
        "version": int(rev["value"]) if rev else last_id,
        "last_id": last_id,      # id of the newest action (used to highlight new dots)
        "groups": groups,
        "total": {a: sum(g[a] for g in groups) for a in ACTIONS},
        "recent": [{**dict(r), "action": merged.get(r["action"], r["action"])} for r in reversed(rows)],
        "weight_limit": WEIGHT_LIMIT,
    }
