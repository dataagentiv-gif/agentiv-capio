"""Kontrak Stage 7: rantai filter ffmpeg benar-benar menghasilkan MP4 9:16
dengan caption yang menempel.

Test ini menjalankan ffmpeg sungguhan. Itu disengaja: yang paling mungkin patah
di stage ini bukan logika Python-nya, melainkan urutan argumen ffmpeg — dan
salah urut `-ss` tetap menghasilkan exit code 0 dengan caption yang lenyap.
"""
import shutil

import pytest

from pipeline.layout import ambil
from pipeline.stages.caption import build_ass
from pipeline.stages.render import OUT_H, OUT_W, _render_one
from utils.ffmpeg_helpers import Deadline, probe

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg tidak ada di PATH"
)

CLIP_START, CLIP_END = 5.0, 13.0


@pytest.fixture(scope="module")
def sample():
    from tests.fixtures.make_fixture import build

    return build()


@pytest.fixture
def workdir(tmp_path, sample):
    shutil.copy(sample, tmp_path / "source.mp4")
    (tmp_path / "clips").mkdir()
    words = [
        {"i": i, "w": f"kata{i}", "s": CLIP_START + i * 0.5, "e": CLIP_START + i * 0.5 + 0.4}
        for i in range(14)
    ]
    (tmp_path / "c1.ass").write_text(
        build_ass(words, CLIP_START, CLIP_END), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def seg():
    return {"id": "c1", "start": CLIP_START, "end": CLIP_END}


def render(workdir, seg, crop=None, layout="penuh", teks=True):
    return _render_one(
        workdir / "source.mp4",
        workdir,
        seg,
        crop or {"x": 656, "w": 608, "fx": None, "fy": None},
        src_w=1920,
        src_h=1080,
        deadline=Deadline(300),
        lay=ambil(layout),
        teks=teks,
    )


def test_output_persis_1080x1920(workdir, seg):
    info = probe(render(workdir, seg), Deadline(60))
    assert (info["width"], info["height"]) == (OUT_W, OUT_H)


def test_durasi_sesuai_potongan(workdir, seg):
    info = probe(render(workdir, seg), Deadline(60))
    # Toleransi 0.5 detik: potongan berhenti di batas frame terdekat.
    assert abs(info["duration"] - (CLIP_END - CLIP_START)) < 0.5


def test_crop_x_berpengaruh_ke_isi_gambar(workdir, seg):
    """Kalau argumen crop diabaikan ffmpeg, dua render ini akan identik."""
    kiri = render(workdir, seg, {"x": 0, "w": 608}).read_bytes()
    (workdir / "clips" / "c1.mp4").unlink()
    kanan = render(workdir, seg, {"x": 1312, "w": 608}).read_bytes()
    assert kiri != kanan


def test_file_punya_audio_dan_video(workdir, seg):
    import json
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "json", str(render(workdir, seg))],
        capture_output=True, text=True, check=True,
    )
    kinds = {s["codec_type"] for s in json.loads(out.stdout)["streams"]}
    assert kinds == {"video", "audio"}


def test_ass_yang_rusak_menggagalkan_render_bukan_lolos_diam_diam(workdir, seg):
    """Salah satu mode gagal terburuk: file caption tidak terbaca, render tetap
    sukses, dan hasilnya klip tanpa caption yang baru ketahuan saat ditonton."""
    (workdir / "c1.ass").unlink()
    with pytest.raises(RuntimeError):
        render(workdir, seg)


# --- mentahan dan saklar caption ---

def test_ori_mempertahankan_rasio_sumber(workdir, seg):
    """Yang dituju justru TIDAK 1080x1920: ini mentahan untuk diedit lagi."""
    info = probe(render(workdir, seg, layout="ori"), Deadline(60))
    assert (info["width"], info["height"]) == (1920, 1080)


def test_ori_tetap_dipotong_tepat_di_sumbu_waktu(workdir, seg):
    """Tanpa filter bukan berarti tanpa potongan — dan potongannya harus tepat,
    bukan melompat ke keyframe terdekat seperti `-c copy`."""
    info = probe(render(workdir, seg, layout="ori"), Deadline(60))
    assert abs(info["duration"] - (CLIP_END - CLIP_START)) < 0.5


def test_caption_mati_tidak_menyentuh_ass(workdir, seg):
    """Bukti bahwa filter subtitles benar-benar hilang, bukan cuma menunjuk file
    kosong: tanpa .ass render harus tetap SUKSES di sini, padahal dengan caption
    nyala hal yang sama menggagalkannya."""
    (workdir / "c1.ass").unlink()
    info = probe(render(workdir, seg, teks=False), Deadline(60))
    assert (info["width"], info["height"]) == (OUT_W, OUT_H)


def test_caption_mati_menghasilkan_gambar_yang_berbeda(workdir, seg):
    """Kalau sama persis, captionnya memang tidak pernah terbakar sejak awal —
    dan test di atas jadi lolos karena alasan yang salah."""
    dengan = render(workdir, seg).read_bytes()
    (workdir / "clips" / "c1.mp4").unlink()
    tanpa = render(workdir, seg, teks=False).read_bytes()
    assert dengan != tanpa
