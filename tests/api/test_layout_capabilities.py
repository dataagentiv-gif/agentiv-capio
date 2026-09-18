"""Kontrak layout yang dipakai Submit tanpa aturan nama hard-coded."""
from api import routes


def test_layouts_mengekspos_duo_dan_arah_pembicara():
    data = routes.daftar_layout()
    per_nama = {x["nama"]: x for x in data["layouts"]}
    assert list(per_nama) == ["penuh", "duo", "kotak", "samping", "ori"]
    assert per_nama["duo"]["duo"] is True
    assert per_nama["duo"]["judul"] == "Podcast 2 Orang"
    assert per_nama["samping"]["speaker_side"] is True
    assert all(not x["speaker_side"] for n, x in per_nama.items() if n != "samping")


def test_preview_meneruskan_sisi_pembicara(monkeypatch):
    terlihat = {}

    def palsu(nama, knob):
        terlihat.update(layout=nama, knob=knob)
        return b"mp4", "video/mp4"

    monkeypatch.setattr(routes.preview, "render", palsu)
    response = routes.preview_tampilan(layout="samping", speaker_side="kanan")
    assert terlihat == {"layout": "samping", "knob": {"speaker_side": "kanan"}}
    assert response.body == b"mp4"


def test_schema_clip_meneruskan_status_fallback_layout():
    from api.schemas import Clip

    clip = Clip.model_validate({
        "id": "c1", "url": "/c1", "duration": 10, "score": 80,
        "hook": "h", "reason": "r", "title": "t", "caption": "c",
        "hashtags": [], "layout": "duo", "layout_fallback": True,
    })
    assert clip.model_dump()["layout"] == "duo"
    assert clip.model_dump()["layout_fallback"] is True
