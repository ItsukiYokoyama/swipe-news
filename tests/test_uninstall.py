import base64
import sys

import pytest

from swipe_news import paths, uninstall


@pytest.fixture
def zip_build(tmp_path, monkeypatch):
    """A fake extracted zip build: SwipeNews/{Swipe News.cmd, python/pythonw.exe, python/swipe-news-portable}."""
    app = tmp_path / "SwipeNews"
    (app / "python").mkdir(parents=True)
    (app / "Swipe News.cmd").write_text("x")
    (app / "python" / "swipe-news-portable").write_text("1.0.0")
    exe = app / "python" / "pythonw.exe"
    exe.write_text("x")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(paths, "PORTABLE", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    started = []
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    return app, started


def script_of(started) -> str:
    [(args, kw)] = started
    return base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_deletes_app_folder_and_start_menu_but_keeps_data(zip_build, data_dir):
    app, started = zip_build
    lnk = paths.start_menu_shortcut()
    lnk.parent.mkdir(parents=True)
    lnk.write_text("x")
    uninstall.start(delete_data=False)
    assert not lnk.exists()
    script = script_of(started)
    assert str(app.resolve()) in script and str(data_dir / "news.db") not in script
    assert started[0][1]["cwd"] != str(app)  # The cleaner must not run inside the folder it deletes


def test_deletes_only_known_data_files(zip_build, data_dir):
    _, started = zip_build
    for name in ("settings.json", "swipe-news.log", "swipe-news.log.1", "feeds.yaml", "someone-elses.txt"):
        (data_dir / name).write_text("x")
    uninstall.start(delete_data=True)
    script = script_of(started)
    for name in ("news.db", "settings.json", "swipe-news.log", "swipe-news.log.1", "feeds.yaml"):
        assert str(data_dir / name) in script
    assert "someone-elses.txt" not in script
    assert "[IO.Directory]::Delete" in script  # The folder itself only goes if it ends up empty


def test_refuses_a_folder_that_is_not_the_zip_build(zip_build):
    app, started = zip_build
    (app / "Swipe News.cmd").unlink()
    with pytest.raises(uninstall.UninstallError):
        uninstall.start(delete_data=False)
    assert started == []


def test_refuses_outside_the_zip_build(monkeypatch):
    monkeypatch.setattr(paths, "PORTABLE", False)
    with pytest.raises(uninstall.UninstallError):
        uninstall.start(delete_data=False)
