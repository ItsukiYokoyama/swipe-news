"""Where files live: user data in a per-user folder, the UI and other bundled files inside this package."""
import os
import sys
from pathlib import Path

APP_NAME = "SwipeNews"
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
GENRES_FILE = PACKAGE_DIR / "genres.yaml"
# The Windows zip bundles the model here (otherwise it is downloaded into MODELS_DIR on first use)
BUNDLED_MODELS_DIR = PACKAGE_DIR / "models"
# The Windows zip (packaging/build-portable.ps1) puts a marker file next to python.exe
PORTABLE = (Path(sys.executable).resolve().parent / "swipe-news-portable").exists()


def extension_dir() -> Path | None:
    """The bundled Chrome extension: next to the python folder in the Windows zip, or at the top of a source checkout.
    A pip install doesn't include it."""
    for d in (Path(sys.executable).resolve().parent.parent / "extension", PACKAGE_DIR.parent.parent / "extension"):
        if (d / "manifest.json").exists():
            return d
    return None


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "swipe-news"


# SWIPE_NEWS_DATA points to another folder (for tests, or to try things with separate data)
DATA_DIR = Path(os.environ.get("SWIPE_NEWS_DATA") or _default_data_dir())
DB_PATH = DATA_DIR / "news.db"
MODELS_DIR = DATA_DIR / "models"
LOG_PATH = DATA_DIR / "swipe-news.log"
SETTINGS_PATH = DATA_DIR / "settings.json"
