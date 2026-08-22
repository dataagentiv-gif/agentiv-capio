"""Kontrak Stage 6: crop map {clip_id: {x, w}} yang selalu berada di dalam frame.

Fixture sintetis tidak punya wajah, jadi yang diuji di sini adalah jalur
fallback — dan justru itu jalur yang paling sering kepakai di produksi (video
tanpa wajah, wajah membelakangi kamera, shot b-roll).
"""
import shutil

import pytest

from pipeline.stages.crop import DET_H, DET_W, _face_center, _sample
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
    [(1920, 1080, 606), (1280, 720, 404), (3840, 2160, 1214)],
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
