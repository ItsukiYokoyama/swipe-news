"""Genre definitions (genres.yaml): four categories, each with sub-genres."""
from functools import cache

import yaml

from .paths import GENRES_FILE

CATEGORIES = ["テクノロジー", "経済", "エンタメ", "社会"]


@cache
def load() -> tuple[dict, ...]:
    """({"category": category, "genres": [{"name", "short", "hints"}]}, ...) in CATEGORIES order."""
    with open(GENRES_FILE, encoding="utf-8") as f:
        conf = (yaml.safe_load(f) or {}).get("genres") or {}
    unknown = set(conf) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"genres categories must be one of {CATEGORIES}: {sorted(unknown)}")
    out, seen = [], set()
    for cat in CATEGORIES:
        genres = []
        for g in conf.get(cat) or []:
            g = {"name": g} if isinstance(g, str) else g
            if g["name"] in seen:
                raise ValueError(f"duplicate sub-genre name: {g['name']}")
            seen.add(g["name"])
            genres.append({"name": g["name"], "short": g.get("short", g["name"]), "hints": list(g.get("hints") or [])})
        out.append({"category": cat, "genres": genres})
    return tuple(out)


def genre_names() -> list[str]:
    return [g["name"] for t in load() for g in t["genres"]]


def category_of(genre: str) -> str | None:
    """Sub-genre → category, or None for an unknown sub-genre."""
    return next((t["category"] for t in load() for g in t["genres"] if g["name"] == genre), None)


def public() -> list[dict]:
    """The shape sent to the UI (without the hint texts)."""
    return [{"category": t["category"], "genres": [{"name": g["name"], "short": g["short"]} for g in t["genres"]]}
            for t in load()]
