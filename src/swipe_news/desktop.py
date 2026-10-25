"""Run as a desktop app: start the server, open it in the browser, and show a tray icon.

    python -m swipe_news [--port 7870] [--no-tray] [--no-browser]

Listens only on this PC (127.0.0.1). Data lives in paths.DATA_DIR (%LOCALAPPDATA%\\SwipeNews on Windows).
The tray menu is part of the UI, so it is in Japanese.
"""
import argparse
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__, paths

log = logging.getLogger(__name__)
HOST = "127.0.0.1"
DEFAULT_PORT = 7870
PORT_TRIES = 10


def load_settings() -> dict:
    try:
        return {"port": DEFAULT_PORT, **json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"port": DEFAULT_PORT}


def save_settings(settings: dict):
    paths.SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def free_port(start: int) -> int | None:
    """Find a free port starting at `start` (so the app still starts if another app uses the default port)."""
    for port in range(start, start + PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    return None


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/config", timeout=1) as r:
            return json.load(r).get("app") == "swipe-news"
    except (OSError, ValueError):
        return False


def setup_logging():
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # pythonw (no console) has no stdout/stderr; give it somewhere to write so logging doesn't crash
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    handler = logging.handlers.RotatingFileHandler(paths.LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])


class Server:
    """Run uvicorn in a background thread (the main thread runs the tray icon)."""

    def __init__(self, port: int):
        import uvicorn

        from .server import app
        self.server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None))
        self.server.install_signal_handlers = lambda: None
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout: float = 30) -> bool:
        self.thread.start()
        end = time.time() + timeout
        while not self.server.started and self.thread.is_alive() and time.time() < end:
            time.sleep(0.1)
        return self.server.started

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def open_folder(path: Path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 (only opens our own data folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def reveal(path: Path):
    """Open the folder that contains `path`, with `path` selected (so it's easy to pick in a file dialog later)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def register_start_menu(settings: dict):
    """In the Windows zip build, add "Swipe News" to the Start menu. Recreated if the folder moves."""
    if sys.platform != "win32" or not paths.PORTABLE:
        return
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    target = f"{pythonw} -m swipe_news"
    lnk = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Swipe News.lnk"
    if settings.get("start_menu") == target and lnk.exists():
        return
    lnk.parent.mkdir(parents=True, exist_ok=True)

    def q(s) -> str:  # Quote as a PowerShell string
        return "'" + str(s).replace("'", "''") + "'"

    script = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)}); "
              f"$l.TargetPath = {q(pythonw)}; $l.Arguments = '-m swipe_news'; "
              f"$l.IconLocation = {q(paths.STATIC_DIR / 'icon.ico')}; "
              f"$l.WorkingDirectory = {q(pythonw.parent.parent)}; $l.Description = 'Swipe News'; $l.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode == 0:
        settings["start_menu"] = target
        save_settings(settings)
        log.info("added to the Start menu: %s", lnk)
    else:
        log.warning("could not add to the Start menu: %s", r.stderr.decode("mbcs", "replace").strip())


def unblock_app_folder(settings: dict):
    """In the Windows zip build, remove the "downloaded from the internet" mark (the Zone.Identifier stream) from
    the app's own files. Without this, Windows asks "unknown publisher" every time Swipe News.cmd is started when
    the zip wasn't unblocked before extracting. Done once per folder."""
    if sys.platform != "win32" or not paths.PORTABLE:
        return
    root = Path(sys.executable).resolve().parent.parent
    if settings.get("unblocked") == str(root):
        return
    count = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                os.remove(os.path.join(dirpath, name) + ":Zone.Identifier")
                count += 1
            except OSError:
                pass  # No mark (the usual case)
    settings["unblocked"] = str(root)
    save_settings(settings)
    if count:
        log.info("removed the downloaded-file mark from %d files in %s", count, root)


def run_tray(server: Server, url: str):
    import pystray
    from PIL import Image

    def quit_app(icon, item):
        server.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Swipe News を開く", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem("データと設定のフォルダを開く", lambda icon, item: open_folder(paths.DATA_DIR)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", quit_app),
    )
    icon = pystray.Icon("SwipeNews", Image.open(paths.STATIC_DIR / "icon-192.png"), "Swipe News", menu)
    icon.run()


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="swipe-news", description="A personal news reader where you sort RSS headlines by swiping cards")
    p.add_argument("--port", type=int, help=f"port to listen on (default {DEFAULT_PORT}; saved in settings.json)")
    p.add_argument("--no-tray", action="store_true", help="don't show the tray icon (quit with Ctrl+C)")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser on start")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    setup_logging()
    settings = load_settings()
    settings.pop("lan", None)  # LAN access setting from 0.3 (removed)
    if args.port:
        settings["port"] = args.port
    save_settings(settings)
    port = settings["port"]

    if already_running(port):
        log.info("already running; just opening the browser")
        if not args.no_browser:
            webbrowser.open(f"http://{HOST}:{port}/")
        return

    # Pick a free port first: failing to bind after the server started would leave the crawler half-started
    found = free_port(port)
    if found is None:
        log.error("ports %d-%d are all in use", port, port + PORT_TRIES - 1)
        sys.exit(1)
    if found != port:
        log.info("port %d is in use by another app; using %d", port, found)
    url = f"http://{HOST}:{found}/"
    log.info("started: %s (version %s, data: %s)", url, __version__, paths.DATA_DIR)
    server = Server(found)
    if not server.start():
        log.error("could not start the server (port %d)", found)
        sys.exit(1)
    if not args.no_browser:
        webbrowser.open(url)
    def after_start():
        unblock_app_folder(settings)
        register_start_menu(settings)
    threading.Thread(target=after_start, daemon=True).start()

    if args.no_tray:
        try:
            while server.thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.stop()
    else:
        run_tray(server, url)
