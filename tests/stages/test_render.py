"""Kontrak Stage 7: rantai filter ffmpeg benar-benar menghasilkan MP4 9:16
dengan caption yang menempel.

Test ini menjalankan ffmpeg sungguhan. Itu disengaja: yang paling mungkin patah
di stage ini bukan logika Python-nya, melainkan urutan argumen ffmpeg — dan
salah urut `-ss` tetap menghasilkan exit code 0 dengan caption yang lenyap.
"""
import shutil
import subprocess

import pytest

from pipeline.layout import ambil
from pipeline.stages.caption import build_ass
from pipeline.stages.render import (
    OUT_H, OUT_W, _gradient_alpha_at, _mask, _render_one,
)
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


def test_duo_statis_render_1080x1920_dengan_audio_dan_durasi_utuh(workdir, seg):
    kata = [{"i": 0, "w": "SAMBUNGAN", "s": CLIP_START, "e": CLIP_END}]
    ass = build_ass(kata, CLIP_START, CLIP_END, lay=ambil("duo"))
    (workdir / "c1.ass").write_text(ass, encoding="utf-8")
    style = next(x for x in ass.splitlines() if x.startswith("Style:"))
    assert style.split(",")[18] == "5"
    c = {"x": 656, "w": 608, "fx": .25, "fy": .35,
         "duo": [{"fx": .25, "fy": .35}, {"fx": .75, "fy": .35}]}
    info = probe(render(workdir, seg, crop=c, layout="duo"), Deadline(60))
    assert (info["width"], info["height"]) == (1080, 1920)
    assert abs(info["duration"] - 8.0) < .5

    import json
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "json", str(workdir / "clips" / "c1.mp4")],
        capture_output=True, text=True, check=True,
    )
    assert {s["codec_type"] for s in json.loads(out.stdout)["streams"]} == {"video", "audio"}


def test_duo_kedua_panel_tetap_video_live_dan_tidak_tertukar(tmp_path):
    """Crop boleh diam, tetapi kedua cabang harus terus membaca frame sumber.

    Sisi kiri merah bergerak mendatar dan sisi kanan biru bergerak vertikal.
    Hash membuktikan tidak ada panel yang berubah menjadi still frame; rerata
    warna membuktikan kiri tetap di atas dan kanan tetap di bawah.
    """
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
            "-f", "lavfi", "-i", "color=red:s=960x1080:r=10:d=4",
            "-f", "lavfi", "-i", "color=white:s=140x140:r=10:d=4",
            "-f", "lavfi", "-i", "color=blue:s=960x1080:r=10:d=4",
            "-f", "lavfi", "-i", "color=white:s=140x140:r=10:d=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-filter_complex",
            "[0:v][1:v]overlay=x='100+100*t':y=250[left];"
            "[2:v][3:v]overlay=x=400:y='100+100*t'[right];"
            "[left][right]hstack=inputs=2[v]",
            "-map", "[v]", "-map", "4:a", "-c:v", "libx264",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(source),
        ],
        check=True,
    )
    (tmp_path / "clips").mkdir()
    crop = {"x": 656, "w": 608, "fx": .25, "fy": .35,
            "duo": [{"fx": .25, "fy": .35}, {"fx": .75, "fy": .35}]}
    out = _render_one(
        source, tmp_path, {"id": "live", "start": 0.0, "end": 4.0}, crop,
        1920, 1080, Deadline(120), ambil("duo"), teks=False,
    )

    def panel(y: int) -> tuple[list[str], tuple[int, int, int]]:
        hashes = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-i", str(out), "-map", "0:v:0",
                "-vf", f"crop=1080:800:0:{y},fps=5", "-an",
                "-f", "framemd5", "-",
            ],
            capture_output=True, text=True, check=True,
        ).stdout
        frame_hashes = [
            line.rsplit(",", 1)[-1].strip()
            for line in hashes.splitlines() if line.startswith("0,")
        ]
        rgb = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", "2", "-i", str(out),
                "-map", "0:v:0", "-vf", f"crop=1080:800:0:{y},scale=1:1",
                "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
            ],
            capture_output=True, check=True,
        ).stdout
        return frame_hashes, tuple(rgb[:3])

    atas, warna_atas = panel(0)
    bawah, warna_bawah = panel(1120)
    assert len(atas) == len(bawah) >= 15
    assert len(set(atas)) == len(atas)
    assert len(set(bawah)) == len(bawah)
    assert warna_atas[0] > warna_atas[2] * 2  # sumber kiri merah -> atas
    assert warna_bawah[2] > warna_bawah[0] * 2  # sumber kanan biru -> bawah


def test_gradasi_mirror_nol_sebelum_wajah_dan_255_di_ujung():
    kiri = ambil("samping")
    from pipeline import layout
    kanan = layout.terapkan_knob(kiri, {"speaker_side": "kanan"})
    assert _gradient_alpha_at(kiri, 0) == 0
    assert _gradient_alpha_at(kiri, kiri.wajah_x * 1080) == 0
    assert _gradient_alpha_at(kiri, 1080) == 255
    assert _gradient_alpha_at(kanan, 0) == 255
    assert _gradient_alpha_at(kanan, kanan.wajah_x * 1080) == 0
    assert _gradient_alpha_at(kanan, 1080) == 0


def test_png_gradasi_produksi_punya_alpha_yang_tepat(workdir):
    from PIL import Image
    from pipeline import layout

    c = {"x": 656, "w": 608, "fx": .5, "fy": .4}
    kiri = ambil("samping")
    g = layout.geometri(kiri, c, 1920, 1080)
    p_kiri = workdir / _mask(workdir, kiri, g, Deadline(60))
    alpha = Image.open(p_kiri).convert("RGBA").getchannel("A")
    assert alpha.getpixel((round(kiri.wajah_x * 1080), 960)) == 0
    assert alpha.getpixel((1079, 960)) == 255

    kanan = layout.terapkan_knob(kiri, {"speaker_side": "kanan"})
    p_kanan = workdir / _mask(workdir, kanan, g, Deadline(60))
    alpha = Image.open(p_kanan).convert("RGBA").getchannel("A")
    assert alpha.getpixel((0, 960)) == 255
    assert alpha.getpixel((round(kanan.wajah_x * 1080), 960)) == 0


def test_duo_tanpa_pasangan_fallback_ke_penuh(workdir, seg):
    c = {"x": 656, "w": 608, "fx": .5, "fy": .35, "duo": None}
    info = probe(render(workdir, seg, crop=c, layout="duo"), Deadline(60))
    assert (info["width"], info["height"]) == (1080, 1920)
