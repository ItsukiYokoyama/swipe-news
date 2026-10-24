"""Preference learning: likes and dislikes finer than genres (e.g. "this game series, but not that one"), learned from article vectors.

For each unread article, "how close it is to opened articles" − "how close it is to skipped articles" is stored
as its affinity and used in the ordering (db.HOURS_PER_AFFINITY). Vectors come from the bundled ruri-v3-30m (genre_ai).
"""
import re
from collections import Counter

import numpy as np

from . import db, genre_ai

TOP_K = 5          # Average of the k nearest (a single neighbour is too easily swayed by a chance match)
MIN_TRAIN = 4      # Don't learn until there are at least this many actions
CLIP = 0.3


def _top_mean(sim: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    if sim.shape[1] == 0:
        return fallback
    k = min(TOP_K, sim.shape[1])
    return np.sort(sim, axis=1)[:, -k:].mean(1)


def recompute() -> int:
    """Recompute the affinity of unread articles. Called after every action and crawl (tens of ms for hundreds × thousands)."""
    unread = db.unread_with_vectors()
    if not unread:
        return 0
    train = db.training_vectors()
    ids = [i for i, _ in unread]
    if len(train) < MIN_TRAIN:
        db.set_affinities([(i, 0.0) for i in ids])
        return len(ids)
    u = np.vstack([genre_ai.from_blob(v) for _, v in unread])
    t = np.vstack([genre_ai.from_blob(v) for _, v in train])
    y = np.array([label for label, _ in train])
    sim = u @ t.T
    base = sim.mean(1)  # How "similar to everything" the article is; subtract it to keep only the like/dislike difference
    pos = _top_mean(sim[:, y > 0], base) - base
    neg = _top_mean(sim[:, y < 0], base) - base
    aff = np.clip(pos - neg, -CLIP, CLIP)
    db.set_affinities(list(zip(ids, aff.round(4).tolist(), strict=False)))
    return len(ids)


# ---- "Words you reacted to": words that often appear in the titles of articles you acted on
_PATTERNS = [
    re.compile(r"「([^」]{2,16})」"),                 # Inside Japanese quotes (titles of works, etc.)
    re.compile(r"[ァ-ヴー]{2,}(?:[娘機版型号王姫団族](?![一-龥]))?"),  # Katakana words (plus one trailing kanji, e.g. ウマ娘)
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]{2,}"),       # Latin words (iPhone, Steam, ...)
]
_STOP = {
    "ニュース", "サービス", "ポイント", "モデル", "アプリ", "ユーザー", "イベント", "キャンペーン", "セール", "シリーズ",
    "コラボ", "ランキング", "チーム", "プロ", "スタート", "オープン", "コメント", "ファン", "メンバー", "グループ",
    "スマホ", "レビュー", "まとめ", "ショップ", "プラン", "システム", "データ", "ネット", "ゲーム", "アニメ", "マンガ",
    "モード", "ログイン", "コード",
    "the", "and", "for", "with", "from", "com", "www", "http", "https",
}


def _terms(title: str) -> set[str]:
    out = set()
    for pat in _PATTERNS:
        for m in pat.finditer(title):
            w = (m.group(1) if pat.groups else m.group(0)).strip()
            if len(w) >= 2 and w not in _STOP and w.lower() not in _STOP:
                out.add(w)
    return out


def reacted_words(limit: int = 8) -> dict:
    """{"like": [[word, positive count, negative count]], "dislike": [...]}. Only words seen at least twice."""
    pos, neg = Counter(), Counter()
    for title, state in db.acted_titles():
        bag = neg if state == "skip" else pos
        bag.update(_terms(title))

    def leaning(a: Counter, b: Counter) -> list[list]:
        words = sorted((w for w in a if a[w] >= 2 and a[w] > b[w]), key=lambda w: (a[w] - b[w], a[w]), reverse=True)
        return [[w, pos[w], neg[w]] for w in words[:limit]]

    return {"like": leaning(pos, neg), "dislike": leaning(neg, pos)}
