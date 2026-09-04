"""Satu frame contoh, dirender lewat jalur yang sama persis dengan produksi.

Bukan tiruan HTML, dan itu bukan soal kerapian. Tiruan CSS akan merender pakai
font milik BROWSER, sementara video dirender libass pakai font di dalam
container — dan sudah terbukti keduanya bisa berbeda tanpa satu pun tanda
(`fc-match Arial` di image ini mengembalikan DejaVu Sans). Preview yang
berbohong justru soal hal yang paling ingin dilihat lebih buruk daripada tidak
ada preview.

Alasan adanya sama sekali: tanpa ini, melihat akibat satu perubahan warna
menuntut menjalankan job penuh — 3 menit sampai satu jam. Itu yang membuat knob
apa pun tidak pernah terpakai.
"""
import subprocess
import tempfile
from pathlib import Path

from config.settings import settings
from pipeline import layout
from pipeline.stages.caption import build_ass, knob_dari_settings
from utils.logging import get

log = get(__name__)

# Kalimat contoh sengaja memuat kata panjang dan angka: dua hal yang paling
# sering bikin caption pecah baris atau meluber, dan tidak akan ketahuan dari
# contoh pendek yang rapi.
CONTOH = "Ini contoh caption dengan kata panjang 144 Hertz supaya kelihatan"
DETIK = 1.6


def _kata_contoh() -> list[dict]:
    kata = CONTOH.split()
    jeda = DETIK / len(kata)
    return [{"i": i, "w": w, "s": i * jeda, "e": (i + 1) * jeda}
            for i, w in enumerate(kata)]


def _sumber(kerja: Path) -> tuple[Path, int, int]:
    """Frame latar: dari klip terbaru kalau ada, kalau tidak pola sintetis.

    Klip sungguhan jauh lebih berguna untuk menilai geometri kotak — di pola
    sintetis tidak ada wajah yang bisa dinilai posisinya. Tapi halaman Setting
    harus tetap bisa dibuka sebelum video pertama diproses.
    """
    mp4 = sorted(
        settings.CLIPS_DIR.glob("*/c*.mp4"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    latar = kerja / "latar.png"
    if mp4:
        # Klip jadi BUKAN sumber mendatar: ia sudah ter-crop jadi 9:16 dan
        # sudah punya caption terbakar. Memakainya mentah menghasilkan dua
        # masalah sekaligus — caption bertumpuk dua lapis, dan wajah yang
        # di-crop ulang sampai terpotong di hidung.
        #
        # Dikembalikan mendekati bentuk aslinya: ambil bujur sangkar bagian
        # atas (bebas caption, yang duduk di bawah), lalu tempelkan ke kanvas
        # 16:9. Orangnya jadi tampil pada skala yang wajar untuk sumber
        # mendatar, dan layout bekerja pada geometri yang mewakili kenyataan.
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "2",
             "-i", str(mp4[0]), "-frames:v", "1",
             "-vf", "crop=1080:1080:0:120,scale=1080:1080,"
                    "pad=1920:1080:(ow-iw)/2:0:black",
             str(latar)],
            check=True, timeout=120)
        return latar, 1920, 1080

    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=1920x1080:rate=1:duration=1",
         "-frames:v", "1", str(latar)],
        check=True, timeout=120)
    return latar, 1920, 1080


def render(nama_layout: str | None = None, knob_tambahan: dict | None = None,
           kecil: bool = False) -> bytes:
    """PNG berisi satu frame dengan layout dan knob yang aktif.

    `kecil` mengecilkan keluaran untuk deretan pilihan di halaman Submit —
    tiga gambar 1080x1920 di satu halaman itu beberapa MB tanpa perlu.
    """
    lay = layout.ambil(nama_layout or settings.CLIP_LAYOUT)
    knob = {**knob_dari_settings(), **(knob_tambahan or {})}

    with tempfile.TemporaryDirectory() as td:
        kerja = Path(td)
        latar, sw, sh = _sumber(kerja)

        (kerja / "p.ass").write_text(
            build_ass(_kata_contoh(), 0.0, DETIK, lay, knob), encoding="utf-8")

        # Wajah dianggap di tengah-atas: preview menilai GEOMETRI dan gaya
        # teks, bukan ketepatan deteksi wajah pada satu frame diam.
        g = layout.geometri(lay, {"x": (sw - 608) // 2, "w": 608,
                                  "fx": 0.5, "fy": 0.38}, sw, sh)
        mask = None
        if lay.radius:
            from pipeline.stages.render import _mask

            class _TanpaBatas:
                def remaining(self, cap=600.0):
                    return cap

            mask = _mask(kerja, lay, g, _TanpaBatas())

        keluar = kerja / "preview.png"
        vf = layout.filtergraph(lay, g, "p.ass", mask)
        if kecil:
            # Dikecilkan SETELAH seluruh rantai, bukan sebelumnya: caption
            # dirender pada resolusi penuh dulu supaya ukuran dan ketebalan
            # hurufnya sebanding dengan hasil sungguhan.
            vf += ",scale=270:480"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", latar.name,
             "-vf", vf, "-frames:v", "1", keluar.name],
            check=True, cwd=kerja, timeout=180)
        return keluar.read_bytes()
