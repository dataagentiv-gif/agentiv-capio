"""Kontrak Stage 6: crop map {clip_id: {x, w}} yang selalu berada di dalam frame.

Fixture sintetis tidak punya wajah, jadi yang diuji di sini adalah jalur
fallback — dan justru itu jalur yang paling sering kepakai di produksi (video
tanpa wajah, wajah membelakangi kamera, shot b-roll).
"""
import shutil

import pytest

from pipeline.stages.crop import (
    DET_H, DET_W, _face_center, _face_pair_from_observations, _sample,
)
from utils.ffmpeg_helpers import Deadline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg tidak ada di PATH"
)


@pytest.fixture(scope="module")
def sample():
    from tests.fixtures.make_fixture import build

    return build()


def test_sample_mengembalikan_frame_rgb_dengan_dimensi_deteksi(sample):
    frames = _sample(sample, 5.0, 10.0, Deadline(120))
    assert frames, "tidak ada frame yang terambil"
    assert frames[0].shape == (DET_H, DET_W, 3)


def test_sample_tidak_melebihi_jatah(sample):
    from pipeline.stages.crop import SAMPLES

    assert len(_sample(sample, 5.0, 10.0, Deadline(120))) <= SAMPLES


def test_tanpa_wajah_mengembalikan_none(sample):
    """None inilah yang memicu fallback center crop di run()."""
    frames = _sample(sample, 5.0, 10.0, Deadline(120))
    assert _face_center(frames) is None


def test_daftar_frame_kosong_tidak_bikin_crash():
    assert _face_center([]) is None


@pytest.mark.parametrize(
    "src_w,src_h,expect_w",
    [
        (1920, 1080, 608),  # 607.5 dibulatkan ke genap terdekat oleh round()
        (1280, 720, 404),
        (3840, 2160, 1214),
    ],
)
def test_lebar_jendela_genap_dan_muat_di_frame(src_w, src_h, expect_w):
    """libx264 dengan yuv420p menolak dimensi ganjil."""
    win_w = min(src_w, round(src_h * 9 / 16)) & ~1
    assert win_w == expect_w
    assert win_w % 2 == 0
    assert win_w <= src_w


def test_crop_x_tidak_pernah_keluar_frame():
    src_w, win_w = 1920, 606
    for frac in (0.0, 0.02, 0.5, 0.98, 1.0):
        x = max(0, min(src_w - win_w, int(frac * src_w - win_w / 2))) & ~1
        assert 0 <= x <= src_w - win_w


# --- posisi wajah mentah untuk layout lain ---
#
# Layout `penuh` memakai jendela 9:16 setinggi frame penuh, jadi tidak pernah
# ada keputusan vertikal. Layout yang menaruh video di kotak lebih pendek harus
# memutuskannya sendiri, dan untuk itu ia butuh tahu di mana orangnya — bukan
# jendela yang sudah terlanjur diputuskan di stage ini.

def _jalankan(tmp_path, monkeypatch, frac):
    import subprocess

    from pipeline.stages import crop as c

    src = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=15:duration=3",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
        check=True, timeout=120)
    from utils.ffmpeg_helpers import Deadline

    monkeypatch.setattr(c, "_face_center", lambda frames: frac)
    # Deadline sungguhan, bukan None: _sample memanggil .remaining() dan akan
    # gagal lebih dulu, sehingga deteksi wajah tidak pernah tercapai — testnya
    # lolos karena alasan yang salah.
    return c.run({"source": src, "meta": {"width": 1920, "height": 1080},
                  "deadline": Deadline(300),
                  "segments_final": [{"id": "c1", "start": 0.0, "end": 2.0}]})["crops"]["c1"]


def test_posisi_wajah_ikut_dibawa(tmp_path, monkeypatch):
    out = _jalankan(tmp_path, monkeypatch, (0.62, 0.35))
    assert out["fx"] == 0.62
    assert out["fy"] == 0.35


def test_tanpa_wajah_posisinya_none_bukan_nol(tmp_path, monkeypatch):
    """Nol adalah posisi yang SAH (tepi kiri/atas). Memakainya sebagai penanda
    'tidak ada' membuat layout membingkai ke pojok, bukan jatuh ke tengah."""
    out = _jalankan(tmp_path, monkeypatch, None)
    assert out["fx"] is None and out["fy"] is None


def test_jendela_lama_tidak_berubah(tmp_path, monkeypatch):
    """Regresi: layout `penuh` harus menghasilkan angka yang persis sama seperti
    sebelum koordinat vertikal dibuka. 1920x1080 -> jendela 608 px."""
    out = _jalankan(tmp_path, monkeypatch, (0.5, 0.4))
    assert out["w"] == 608
    assert out["x"] == ((1920 - 608) // 2) & ~1


def muka(x, y=.35, area=.08):
    return {"x": x, "y": y, "area": area}


def test_duo_memilih_dua_wajah_terbesar_dari_tiga():
    obs = [[muka(.2, area=.10), muka(.55, area=.02), muka(.8, area=.09)]
           for _ in range(20)]
    assert _face_pair_from_observations(obs) == [
        {"fx": .2, "fy": .35}, {"fx": .8, "fy": .35}]


def test_duo_mengikuti_wajah_yang_bergerak_antar_sampel():
    obs = [[muka(.18 + i * .005), muka(.82 - i * .005)] for i in range(20)]
    pair = _face_pair_from_observations(obs)
    assert pair and pair[0]["fx"] < .3 and pair[1]["fx"] > .7


def test_duo_butuh_hadir_bersama_tiga_puluh_persen():
    obs = [[muka(.2), muka(.8)] if i < 5 else [muka(.2)] for i in range(20)]
    assert _face_pair_from_observations(obs) is None


def test_duo_fallback_bila_hanya_satu_wajah():
    assert _face_pair_from_observations([[muka(.4)] for _ in range(20)]) is None
