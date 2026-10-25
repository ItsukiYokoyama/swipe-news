"""Uninstall the Windows zip build from the app itself (About → アンインストール), for users who'd rather not delete folders by hand.

The Start menu entry is removed right away. The app folder (and, if asked, the files this app created in the data folder)
can't be deleted while the app runs from it, so a small hidden PowerShell process waits for the app to exit and deletes them.
Only things this app created are deleted: the app folder is checked for the zip build's files first, and in the data folder
only known file names are removed (SWIPE_NEWS_DATA may point to a folder that holds other things too).
"""
import base64
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
DATA_FILES = ("news.db", "news.db-wal", "news.db-shm", "settings.json", "models")
DATA_PATTERNS = ("news.db.*", "swipe-news.log*", "feeds.yaml*")


class UninstallError(ValueError):
    """An error whose message is shown to the user."""


def app_folder() -> Path:
    """The extracted zip folder, after checking it really is one (so nothing else is ever deleted)."""
    if sys.platform != "win32" or not paths.PORTABLE:
        raise UninstallError("アプリの中からのアンインストールは、Windows 版 (zip) だけでできます")
    root = paths.app_dir()
    if not ((root / "Swipe News.cmd").is_file() and (root / "python" / "swipe-news-portable").is_file()):
        raise UninstallError("アプリのフォルダを確かめられませんでした。フォルダを手で削除してください")
    return root


def data_files() -> list[Path]:
    d = paths.DATA_DIR
    found = [d / name for name in DATA_FILES if (d / name).exists()]
    for pattern in DATA_PATTERNS:
        found += sorted(d.glob(pattern))
    return found


def _ps(s) -> str:  # Quote as a PowerShell string
    return "'" + str(s).replace("'", "''") + "'"


def cleanup_script(pid: int, targets: list[Path], data_dir: Path | None) -> str:
    items = ", ".join(_ps(t) for t in targets)
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"Wait-Process -Id {pid} -Timeout 60\n"
        f"$targets = @({items})\n"
        "foreach ($i in 1..20) {\n"
        "  foreach ($t in $targets) { if (Test-Path -LiteralPath $t) { Remove-Item -LiteralPath $t -Recurse -Force } }\n"
        "  if (-not ($targets | Where-Object { Test-Path -LiteralPath $_ })) { break }\n"
        "  Start-Sleep -Seconds 1\n"
        "}\n"
    )
    if data_dir:  # Remove the data folder only if nothing else is left in it
        script += f"try {{ [IO.Directory]::Delete({_ps(data_dir)}, $false) }} catch {{}}\n"
    return script


def start(delete_data: bool) -> dict:
    """Remove the Start menu entry and start the cleaner. The caller then quits the app."""
    root = app_folder()
    lnk = paths.start_menu_shortcut()
    if lnk and lnk.exists():
        lnk.unlink()
    targets = [root] + (data_files() if delete_data else [])
    script = cleanup_script(os.getpid(), targets, paths.DATA_DIR if delete_data else None)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.Popen(  # noqa: S603
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
        cwd=tempfile.gettempdir(),  # Not inside the folder being deleted
        # A hidden console of its own (PowerShell does nothing under DETACHED_PROCESS); it outlives the app
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True)
    log.info("uninstalling: %s (data: %s)", root, delete_data)
    return {"app_dir": str(root), "data_deleted": delete_data}
