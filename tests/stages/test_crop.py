"""Kontrak Stage 6: crop map {clip_id: {x, w}} yang selalu berada di dalam frame.

Fixture sintetis tidak punya wajah, jadi yang diuji di sini adalah jalur
fallback — dan justru itu jalur yang paling sering kepakai di produksi (video
tanpa wajah, wajah membelakangi kamera, shot b-roll).
"""
import shutil
from pathlib import Path

import pytest

from pipeline.stages.crop import (
    DET_H, DET_W, _face_center, _face_pair, _face_pair_from_observations,
    _pair_fits_duo, _sample,
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


def test_podcast_dua_orang_stabil_mengunci_posisi_median():
    obs = [[muka(.24 + (i % 3) * .01), muka(.74 + (i % 3) * .01)]
           for i in range(20)]
    pair = _face_pair_from_observations(obs)
    assert pair == [{"fx": .25, "fy": .35}, {"fx": .75, "fy": .35}]


def test_podcast_menerima_dua_dropout_detector():
    obs = [[muka(.2), muka(.8)] for _ in range(18)] + [[], [muka(.2)]]
    assert _face_pair_from_observations(obs) is not None


def test_podcast_menolak_tiga_dropout_detector():
    obs = [[muka(.2), muka(.8)] for _ in range(17)] + [[], [], [muka(.2)]]
    assert _face_pair_from_observations(obs) is None


def test_podcast_closeup_bergantian_fallback_penuh():
    obs = [[muka(.3 if i < 10 else .7)] for i in range(20)]
    assert _face_pair_from_observations(obs) is None


def test_podcast_tiga_orang_fallback_penuh():
    obs = [[muka(.2, area=.10), muka(.55, area=.02), muka(.8, area=.09)]
           for _ in range(20)]
    assert _face_pair_from_observations(obs) is None


def test_podcast_posisi_kamera_berubah_fallback_penuh():
    obs = [[muka(.2), muka(.8)] for _ in range(10)] + \
          [[muka(.4), muka(.6)] for _ in range(10)]
    assert _face_pair_from_observations(obs) is None


def test_podcast_posisi_vertikal_berubah_fallback_penuh():
    obs = [[muka(.2, y=.2), muka(.8, y=.2)] for _ in range(10)] + \
          [[muka(.2, y=.5), muka(.8, y=.5)] for _ in range(10)]
    assert _face_pair_from_observations(obs) is None


def test_duo_menolak_pasangan_yang_hanya_muncul_sesekali():
    obs = [[muka(.2), muka(.8)] if i < 15 else [muka(.2)] for i in range(20)]
    assert _face_pair_from_observations(obs) is None


def test_duo_menerima_pasangan_stabil_sembilan_puluh_persen():
    obs = [[muka(.2), muka(.8)] if i < 18 else [muka(.2)] for i in range(20)]
    assert _face_pair_from_observations(obs) is not None


def test_duo_fallback_bila_hanya_satu_wajah():
    assert _face_pair_from_observations([[muka(.4)] for _ in range(20)]) is None


def test_duo_mengabaikan_wajah_kecil_di_latar():
    obs = [[muka(.2, area=.08), muka(.8, area=.07), muka(.5, area=.002)]
           for _ in range(20)]
    assert _face_pair_from_observations(obs) is not None


def test_podcast_menolak_duo_yang_cropnya_terlalu_sempit():
    pair = _face_pair_from_observations([[muka(.08), muka(.28)] for _ in range(20)])
    assert pair is not None
    assert _pair_fits_duo(pair, 1920, 1080) is False


def test_podcast_menerima_dua_pembicara_yang_duduk_rapat():
    pair = _face_pair_from_observations([[muka(.41), muka(.588)] for _ in range(20)])
    assert pair is not None
    assert _pair_fits_duo(pair, 1280, 720) is True


def test_duo_mendeteksi_wide_shot_dua_pembicara(tmp_path):
    """Regresi nyata: model short-range hanya melihat kedua wajah pada 3/20
    sampel fixture ini, sehingga versi lama selalu fallback ke Penuh."""
    import subprocess

    contoh = Path(__file__).resolve().parents[2] / "web/static/contoh/penuh.mp4"
    out = tmp_path / "wide.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=1280x720:d=1",
            "-ss", "2", "-i", str(contoh), "-ss", "6", "-i", str(contoh),
            "-t", "1", "-filter_complex",
            "[1:v]scale=-2:360[a];[2:v]scale=-2:360[b];"
            "[0:v][a]overlay=220:360[x];[x][b]overlay=860:360[v]",
            "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True, timeout=120,
    )
    frames = _sample(out, 0, 1, Deadline(120))
    pasangan = _face_pair(frames)
    assert pasangan and pasangan[0]["fx"] < .4 and pasangan[1]["fx"] > .6
