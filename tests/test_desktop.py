import sys

import pytest

from swipe_news import desktop, paths


@pytest.mark.skipif(sys.platform != "win32", reason="Zone.Identifier streams exist only on Windows (NTFS)")
def test_unblock_removes_downloaded_mark_once(tmp_path, monkeypatch):
    app = tmp_path / "SwipeNews"
    (app / "python").mkdir(parents=True)
    exe = app / "python" / "pythonw.exe"
    files = [app / "Swipe News.cmd", exe]
    for f in files:
        f.write_text("x")
        with open(str(f) + ":Zone.Identifier", "w") as s:
            s.write("[ZoneTransfer]\nZoneId=3\n")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(paths, "PORTABLE", True)
    monkeypatch.setattr(paths, "SETTINGS_PATH", tmp_path / "settings.json")

    settings = {}
    desktop.unblock_app_folder(settings)

    for f in files:
        with pytest.raises(OSError):
            open(str(f) + ":Zone.Identifier").close()
        assert f.read_text() == "x"
    assert settings["unblocked"] == str(app.resolve())
