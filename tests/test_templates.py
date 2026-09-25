import pytest
from pydantic import ValidationError

from api.schemas import JobCreate
from pipeline.composition import _panel
from pipeline.emphasis import choose
from pipeline.motion import build, title_lines
from pipeline.templates import MOTIONS, TEMPLATES, resolve

URL = "https://youtu.be/dQw4w9WgXcQ"


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_setiap_template_punya_konfigurasi_valid(template_id):
    job = JobCreate(url=URL, template_id=template_id)
    assert job.adjustments == resolve(template_id, {})


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_adjustment_silang_ditolak(template_id):
    with pytest.raises(ValidationError):
        JobCreate(url=URL, template_id=template_id, adjustments={"ukuran": 999})


@pytest.mark.parametrize("template_id,motion", [(t, m) for t, ms in MOTIONS.items() for m in ms])
def test_semua_motion_valid(template_id, motion):
    assert resolve(template_id, {"caption_motion": motion})["caption_motion"] == motion


@pytest.mark.parametrize("options", [
    {"caption_motion": "scatter_emphasis"}, {"caption_motion": "kinetic_words", "redup_gelap": 0},
    {"caption_style": "background", "active_background_color": "nothex"},
])
def test_opsi_tidak_sah_ditolak(options):
    with pytest.raises(ValueError):
        resolve("pembicara_samping" if "caption_motion" in options else "full_screen", options)


def test_warna_kondisional():
    with pytest.raises(ValueError):
        resolve("full_screen", {"active_background_color": "#FFFFFF"})
    assert resolve("full_screen", {"caption_style": "background", "active_background_color": "#aabbcc"})["active_background_color"] == "AABBCC"
    assert resolve("full_screen", {"caption_style": "background"})["active_text_color"] == "000000"
    with pytest.raises(ValueError):
        resolve("kotak_tengah", {"scatter_accent_color": "#FF0000"})


def test_custom_dan_legacy_tidak_diterima():
    for template_id in ("custom", "penuh", "ori"):
        with pytest.raises(ValueError):
            resolve(template_id, {})


def test_hook_selalu_dua_baris():
    title = title_lines("", "Ini hook yang sangat panjang dan perlu dipotong di batas dua baris agar tetap terbaca")
    assert len(title.split(r"\N")) <= 2
    assert all(len(line) <= 34 for line in title.split(r"\N"))


def test_seleksi_momen_mempertahankan_judul_terpisah(monkeypatch):
    from pipeline.stages.segment import _validate
    from config.settings import settings
    monkeypatch.setattr(settings, "MIN_CLIP_SEC", 1)
    monkeypatch.setattr(settings, "MAX_CLIP_SEC", 30)
    words = [{"i": i, "w": f"kata{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(12)]
    raw = [{"start_idx": 0, "end_idx": 10, "hook": "kata0 kata1", "hook_title": "Topik singkat",
            "reason": "bagus", "score": 80}]
    assert _validate(raw, words, 1)[0]["hook_title"] == "Topik singkat"


def test_no_face_center_tanpa_stretch():
    assert "force_original_aspect_ratio=decrease" in _panel(1080, 1920, 1080, 800, {"fx": None})
    assert "crop=" in _panel(1920, 1080, 1080, 800, {"fx": None})


def test_crop_tanpa_wajah_memakai_tengah(monkeypatch):
    from pipeline.stages import crop
    monkeypatch.setattr(crop, "_sample", lambda *a, **k: [])
    monkeypatch.setattr(crop, "_face_center", lambda frames: None)
    ctx = {"source": "x.mp4", "meta": {"width": 1920, "height": 1080},
           "deadline": None, "template_id": "pembicara_samping",
           "segments_final": [{"id": "c1", "start": 0.0, "end": 2.0}]}
    result = crop._template_crops(ctx)["crops"]["c1"]
    assert result["x"] == (1920 - result["w"]) // 2
    assert result["speaker_side"] == "kiri"


def test_bayangan_berpindah_mengikuti_sisi_klip(tmp_path):
    from pipeline.composition import filters
    from utils.ffmpeg_helpers import Deadline
    crop = {"fx": 0.75, "speaker_side": "kanan"}
    graph, is_complex = filters("pembicara_samping", crop, 1920, 1080,
                                "c1.ass", tmp_path, Deadline(30))
    assert is_complex
    assert "kiri" in graph
    assert "subtitles=c1.ass" in graph


def test_caption_waktu_asli_dan_sisi_klip():
    words = [{"i": 0, "w": "Halo", "s": 5.0, "e": 5.4},
             {"i": 1, "w": "dunia", "s": 5.5, "e": 6.0}]
    seg = {"start": 5.0, "end": 7.0, "hook": "Halo dunia"}
    opts = resolve("pembicara_samping", {"caption_motion": "editorial_focus"})
    left = build(words, seg, "pembicara_samping", opts, {"speaker_side": "kiri"}, {1})
    right = build(words, seg, "pembicara_samping", opts, {"speaker_side": "kanan"}, {1})
    assert "\\pos(780," in left and "\\pos(300," in right
    assert "0:00:00.00" in left and "0:00:00.50" in left


def test_kata_tanpa_spasi_mengecil_tanpa_mengubah_teks():
    word = "A" * 80
    seg = {"start": 0.0, "end": 2.0, "hook": word}
    ass = build([{"i": 0, "w": word, "s": 0.0, "e": 1.0}], seg,
                "full_screen", resolve("full_screen", {}), {"fx": None})
    assert word in ass
    assert "Style: Cap,Poppins,17," in ass


def test_blur_hanya_blok_hook_dan_gaya_caption():
    assert resolve("blur_atas_bawah", {})["hook_block"] == "none"
    assert resolve("blur_atas_bawah", {"hook_block": "white",
                                      "caption_style": "background"})["hook_block"] == "white"
    with pytest.raises(ValueError):
        resolve("blur_atas_bawah", {"hook_block": "acak"})
    with pytest.raises(ValueError):
        resolve("blur_atas_bawah", {"spoken_layout": "single_word"})
    with pytest.raises(ValueError):
        resolve("blur_atas_bawah", {"hook_title_style": "normal"})


def test_blur_hook_putih_atau_blok_putih_teks_hitam():
    words = [{"i": 0, "w": "Halo", "s": 0.0, "e": .5}]
    seg = {"start": 0., "end": 2., "hook_title": "Ini hook", "hook": "Halo"}
    plain = build(words, seg, "blur_atas_bawah", resolve("blur_atas_bawah", {}), {})
    block = build(words, seg, "blur_atas_bawah",
                  resolve("blur_atas_bawah", {"hook_block": "white"}), {})
    assert r"\p1" not in plain
    assert r"\p1" in block
    assert r"\1c&H000000&" in block
    assert "Ini hook" in plain and "Ini hook" in block


def test_tipografi_motion_dan_fallback_per_grup():
    words = [{"i": i, "w": w, "s": i * 0.5, "e": i * 0.5 + 0.4}
             for i, w in enumerate("satu dua tiga empat lima enam".split())]
    seg = {"start": 0.0, "end": 4.0, "hook": "satu dua"}
    scatter = build(words, seg, "kotak_tengah",
                    resolve("kotak_tengah", {"caption_motion": "scatter_emphasis"}), {}, set())
    assert "\\fnArchivo Black" in scatter
    assert scatter.count("\\fnArchivo Black") == 2
    assert all(w["w"] in scatter for w in words)
    soft = build(words, seg, "pembicara_samping",
                 resolve("pembicara_samping", {"caption_motion": "soft_focus"}),
                 {"speaker_side": "kiri"})
    assert "\\fnLora" in soft and "\\b1" in soft
    kinetic = build(words, seg, "pembicara_samping",
                    resolve("pembicara_samping", {"caption_motion": "kinetic_words"}), {})
    assert all(w["w"].upper() in kinetic for w in words)


def test_anotasi_gagal_fallback(monkeypatch):
    monkeypatch.setattr("pipeline.emphasis.call_llm", lambda *a, **k: {"indices": [999]})
    assert choose([{"i": 4, "w": "pentingnya", "s": 1.0, "e": 1.4}], 0, 2) == {4}


def test_api_menyimpan_default_per_job(monkeypatch):
    from api import routes

    saved = {}
    monkeypatch.setattr(routes, "_pastikan_boleh_memproses", lambda: None)
    monkeypatch.setattr(routes.jobs, "create", lambda url, n, template_id, adjustments: saved.update(
        url=url, n=n, template_id=template_id, adjustments=adjustments) or {"id": "job", "status": "queued"})
    monkeypatch.setattr(routes, "enqueue", lambda job_id: None)
    routes.create_job(JobCreate(url=URL, template_id="full_screen"))
    assert saved["template_id"] == "full_screen"
    assert saved["adjustments"] == resolve("full_screen", {})


def test_retry_job_lama_ditolak(monkeypatch):
    from api import routes
    from fastapi import HTTPException

    monkeypatch.setattr(routes.jobs, "get", lambda job_id: {"status": "failed", "layout": "penuh"})
    with pytest.raises(HTTPException) as exc:
        routes.retry_job("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert exc.value.status_code == 409
