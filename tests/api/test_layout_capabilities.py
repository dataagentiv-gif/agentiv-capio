"""Kontrak library template yang dipakai Submit."""
from api import routes


def test_library_mengekspos_lima_template():
    data = routes.daftar_layout()
    per_nama = {x["id"]: x for x in data["templates"]}
    assert list(per_nama) == ["mentahan", "full_screen", "pembicara_samping", "blur_atas_bawah", "kotak_tengah"]
    assert per_nama["mentahan"]["defaults"] == {}
    assert per_nama["pembicara_samping"]["defaults"]["caption_motion"] == "soft_focus"


def test_preview_meneruskan_adjustment(monkeypatch):
    terlihat = {}

    def palsu(nama, knob):
        terlihat.update(template_id=nama, adjustments=knob)
        return b"mp4"

    from api import template_preview
    monkeypatch.setattr(template_preview, "render", palsu)
    response = routes.template_preview({"template_id": "kotak_tengah", "adjustments": {"caption_motion": "soft_phrase"}})
    assert terlihat == {"template_id": "kotak_tengah", "adjustments": {"caption_motion": "soft_phrase"}}
    assert response.body == b"mp4"


def test_schema_clip_meneruskan_status_fallback_layout():
    from api.schemas import Clip

    clip = Clip.model_validate({
        "id": "c1", "url": "/c1", "duration": 10, "score": 80,
        "hook": "h", "reason": "r", "title": "t", "caption": "c",
        "hashtags": [], "layout": "full_screen", "layout_fallback": False,
    })
    assert clip.model_dump()["layout"] == "full_screen"
    assert clip.model_dump()["layout_fallback"] is False
