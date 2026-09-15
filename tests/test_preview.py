from pathlib import Path

from api import preview


def test_preview_memberi_libass_folder_font(monkeypatch):
    perintah = []

    def ffmpeg(cmd, **kw):
        perintah.extend(cmd)
        (Path(kw["cwd"]) / "preview.mp4").write_bytes(b"preview")

    monkeypatch.setattr(preview.subprocess, "run", ffmpeg)
    preview._CACHE.clear()
    assert preview.render("penuh", {"active_word_style": "background"})[0] == b"preview"
    vf = perintah[perintah.index("-vf") + 1]
    assert "fontsdir=" in vf and "assets/fonts" in vf
