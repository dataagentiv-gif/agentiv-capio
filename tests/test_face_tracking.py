"""Regresi crop dua pembicara tanpa mengubah komposisi template."""
import subprocess

from pipeline.composition import _panel
from pipeline.stages.crop import _tracked_shots


def face(x, area=.04, width=.08):
    return {"x": x, "y": .4, "area": area, "width": width}


def shots(frames, template="full_screen", words=None):
    return _tracked_shots(frames, len(frames), 1920, 1080, template, words or [], 0)


def test_dua_wajah_berganti_ukuran_tidak_menghasilkan_crop_di_tengah():
    frames = [[face(.30, .05 if i % 2 else .04),
               face(.74, .04 if i % 2 else .05)] for i in range(12)]
    result = shots(frames)
    assert len(result) == 1
    assert abs(result[0]["center"] - .74) < .01


def test_wajah_keluar_lalu_wajah_lain_stabil_memicu_satu_cut_di_jeda():
    frames = [[face(.28)] for _ in range(4)]
    frames += [[face(.75, .03)] for _ in range(6)]
    words = [{"s": 3.1, "e": 3.6}, {"s": 4.8, "e": 5.2}]
    result = shots(frames, words=words)
    assert len(result) == 2
    assert result[0]["center"] == .28
    assert result[1]["center"] == .75
    assert result[1]["at"] == 4.2


def test_dropout_sesaat_dan_wajah_tepi_tidak_memicu_cut_berulang():
    frames = [[face(.02)] for _ in range(4)] + [[]] + [[face(.02)] for _ in range(5)]
    assert shots(frames) == [{"at": 0.0, "center": .02}]


def test_gerak_kepala_alami_tetap_satu_bingkai():
    positions = [.492, .471, .486, .559, .508, .527, .543, .559,
                 .495, .468, .505, .499, .452, .453, .506, .473,
                 .453, .492, .479, .513, .486, .445, .466, .529,
                 .455, .470, .475, .544, .573, .451, .470, .447,
                 .452, .473, .439, .452, .450, .452, .448]
    frames = [[face(x, width=.18)] for x in positions]
    assert len(shots(frames)) == 1


def test_blur_memuat_dua_wajah_jika_keduanya_muat():
    frames = [[face(.34 + (i % 3) * .01), face(.70 - (i % 2) * .01)]
              for i in range(10)]
    result = shots(frames, "blur_atas_bawah")
    assert len(result) == 1
    assert abs(result[0]["center"] - .52) < .01


def test_tanpa_wajah_jatuh_ke_crop_tengah_lama():
    assert shots([[] for _ in range(10)]) == []
    assert "crop=" in _panel(1920, 1080, 1080, 1920, {"fx": None})


def test_filter_ffmpeg_menerima_cut_relativ_klip():
    graph = _panel(160, 90, 90, 160,
                   {"shots": [{"at": 0.0, "center": .25},
                              {"at": 2.0, "center": .75}]})
    assert "lt(t\\,2.000)" in graph
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=80x90:r=1:d=4",
         "-f", "lavfi", "-i", "color=blue:s=80x90:r=1:d=4", "-filter_complex",
         f"[0:v][1:v]hstack=inputs=2[wide];[wide]{graph}[out]", "-map", "[out]",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    frame_size = 90 * 160 * 3
    assert result.stdout[0] > 240 and result.stdout[2] < 20
    assert result.stdout[2 * frame_size] < 20 and result.stdout[2 * frame_size + 2] > 240


def test_hanya_full_screen_dan_blur_memakai_jejak_baru(monkeypatch):
    from pipeline.stages import crop

    frames = [object()] * 10
    observations = [[face(.28)] for _ in range(4)] + [[face(.75)] for _ in range(6)]
    monkeypatch.setattr(crop, "_sample", lambda *args: frames)
    monkeypatch.setattr(crop, "_face_observations", lambda *args, **kwargs: observations)
    monkeypatch.setattr(crop, "_face_center", lambda frames: (.42, .4))
    base = {"source": "source.mp4", "meta": {"width": 1920, "height": 1080},
            "deadline": None, "words": [],
            "segments_final": [{"id": "c1", "start": 0, "end": 10}]}
    for template in ("full_screen", "blur_atas_bawah"):
        result = crop._template_crops({**base, "template_id": template})["crops"]["c1"]
        assert len(result["shots"]) == 2
    result = crop._template_crops({**base, "template_id": "kotak_tengah"})["crops"]["c1"]
    assert result["fx"] == .42 and "shots" not in result
