"""Runtime settings. Each can be changed with an environment variable (the defaults are fine for normal use)."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


CRAWL_INTERVAL_MIN = _int("SWIPE_NEWS_CRAWL_INTERVAL_MIN", 30)  # Minutes between crawls
MAX_NEW_PER_FEED = _int("SWIPE_NEWS_MAX_NEW_PER_FEED", 10)      # Max new articles per feed per crawl (0 fetches none)
RETENTION_DAYS = _int("SWIPE_NEWS_RETENTION_DAYS", 7)           # Delete articles this many days after publication
AI_GENRE = _bool("SWIPE_NEWS_AI_GENRE", True)                    # Classify sub-genres with the bundled on-device model
# Curated list of recommended feeds. Format: catalog/README.md
CATALOG_URL = os.environ.get("SWIPE_NEWS_CATALOG_URL", "https://ditsuki.com/swipe-news/feeds.json")
# Public file with the latest version number (see updates.py). Turn the check off in the UI settings
UPDATE_URL = os.environ.get("SWIPE_NEWS_UPDATE_URL", "https://ditsuki.com/swipe-news/latest.json")
