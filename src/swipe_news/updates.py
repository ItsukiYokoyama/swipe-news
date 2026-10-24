"""New-version check: reads a public file with the latest version number on ditsuki.com, at most once a day.

The request carries only what any page load carries (IP address, User-Agent); nothing about articles or settings.
It can be turned off in the settings (update_check). The site builds latest.json from the GitHub Releases.
"""
import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from . import __version__, db, net, settings

log = logging.getLogger(__name__)

INTERVAL_SEC = 24 * 60 * 60  # Check at most once a day
RETRY_SEC = 60 * 60          # After a failure, wait an hour before trying again
RELEASES_URL = "https://github.com/ItsukiYokoyama/swipe-news/releases"
_VERSION = re.compile(r"^\d+(\.\d+)*$")


def is_newer(a: str, b: str) -> bool:
    """True if version a is newer than b (compared numerically, so 1.2.10 > 1.2.9)."""
    pa, pb = ([int(n) for n in str(v).split(".")] for v in (a, b))
    width = max(len(pa), len(pb))
    return pa + [0] * (width - len(pa)) > pb + [0] * (width - len(pb))


def enabled() -> bool:
    return bool(db.get_setting("update_check", True))


def _https(url) -> str | None:
    return url if isinstance(url, str) and urlsplit(url).scheme == "https" else None


async def _fetch() -> dict:
    async with net.client() as http:
        r = await http.get(settings.UPDATE_URL, timeout=5, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    version = str(data.get("version", ""))
    if not _VERSION.match(version):
        raise ValueError(f"bad version: {version!r}")
    return {"version": version, "url": _https(data.get("url")), "download_url": _https(data.get("download_url"))}


async def latest() -> dict | None:
    """The latest release ({"version", "url", "download_url"}), cached for a day. None if unknown or turned off."""
    if not enabled():
        return None
    saved = db.get_setting("update_cache") or {}
    if time.time() - saved.get("checked_at", 0) < INTERVAL_SEC:
        return saved.get("release")
    try:
        release = await _fetch()
        db.set_setting("update_cache", {"checked_at": time.time(), "release": release})
        return release
    except (httpx.HTTPError, ValueError) as e:
        log.info("could not check for a new version: %s", e)
        db.set_setting("update_cache", {"checked_at": time.time() - INTERVAL_SEC + RETRY_SEC,
                                        "release": saved.get("release")})
        return saved.get("release")


async def check() -> dict:
    """For the UI: the current version, and the newer release if there is one."""
    release = await latest()
    newer = bool(release) and is_newer(release["version"], __version__)
    return {
        "enabled": enabled(),
        "current": __version__,
        "latest": release["version"] if release else None,
        "newer": newer,
        "url": (release.get("url") or RELEASES_URL) if newer else None,
    }
