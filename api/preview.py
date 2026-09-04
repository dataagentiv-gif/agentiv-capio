"""Contoh tampilan klip, dirender lewat jalur yang sama persis dengan produksi.

Bukan tiruan HTML, dan itu bukan soal kerapian. Tiruan CSS akan merender pakai
font milik BROWSER, sementara video dirender libass pakai font di dalam
container — dan sudah terbukti keduanya bisa berbeda tanpa satu pun tanda
(`fc-match Arial` di image ini pernah mengembalikan DejaVu Sans). Preview yang
berbohong justru soal hal yang paling ingin dilihat lebih buruk daripada tidak
ada preview.

Alasan adanya sama sekali: tanpa ini, melihat akibat satu perubahan warna
menuntut menjalankan job penuh — 3 menit sampai satu jam. Itu yang membuat knob
apa pun tidak pernah terpakai.

Preview besar berupa VIDEO, bukan gambar diam: yang paling menentukan dari gaya
caption adalah sorotan kata yang berpindah, dan itu tidak ada di satu frame.
Deretan pilihan di halaman Submit tetap gambar diam — di sana yang dibandingkan
bentuk kotaknya, dan tiga video yang berputar bersamaan cuma bikin berat.
"""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from config.settings import settings
from pipeline import layout
from pipeline.stages.caption import build_ass, knob_dari_settings
from utils.logging import get

log = get(__name__)

ROOT = Path(__file__).resolve().parent.parent
#: Video contoh yang ikut di dalam repo. Diutamakan di atas klip milik pengguna:
#: klip terbaru berubah tiap job baru, dan di instalasi yang belum pernah
#: memproses apa pun ia tidak ada sama sekali — preview jadi tidak konsisten
#: persis saat orang pertama kali menilai tampilannya.
CONTOH_MP4 = ROOT / "assets" / "preview.mp4"

# Kalimat contoh sengaja memuat kata panjang dan angka: dua hal yang paling
# sering bikin caption pecah baris atau meluber, dan tidak akan ketahuan dari
# contoh pendek yang rapi.
CONTOH = "Ini contoh caption dengan kata panjang 144 Hertz supaya kelihatan"
DETIK = 5.0

_CACHE: dict[str, bytes] = {}


def _kata_contoh() -> list[dict]:
    kata = CONTOH.split()
    jeda = DETIK / len(kata)
    return [{"i": i, "w": w, "s": i * jeda, "e": (i + 1) * jeda}
            for i, w in enumerate(kata)]


def _sumber(kerja: Path) -> tuple[str, int, int, bool]:
    """(nama berkas di kerja, lebar, tinggi, apakah bergerak).

    Urutan: video contoh bawaan -> klip pengguna terbaru -> pola sintetis.
    """
    if CONTOH_MP4.exists():
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             str(CONTOH_MP4)],
            capture_output=True, text=True, check=True)
        w, h = (int(x) for x in p.stdout.strip().split("x")[:2])
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-t", str(DETIK),
             "-i", str(CONTOH_MP4), "-an", "-c:v", "copy", str(kerja / "src.mp4")],
            check=True, timeout=180)
        return "src.mp4", w, h, True

    mp4 = sorted(settings.CLIPS_DIR.glob("*/c*.mp4"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    if mp4:
        # Klip jadi BUKAN sumber mendatar: ia sudah ter-crop jadi 9:16 dan
        # sudah punya caption terbakar. Memakainya mentah menghasilkan caption
        # bertumpuk dua lapis, dan wajah yang di-crop ulang sampai terpotong.
        #
        # TIDAK ADA potongan yang menang di dua sisi, dan itu sudah dicoba:
        # caption klip duduk di tempat berbeda tergantung layout yang dipakai
        # saat merendernya (tengah-bawah untuk penuh dan kotak, tengah-kanan
        # untuk samping), sementara potongan yang menghindari semuanya selalu
        # merusak pembingkaian wajah. Dipilih yang pembingkaiannya paling baik
        # dan caption yang sesekali ikut terbawa diterima apa adanya —
        # assets/preview.mp4 adalah jawaban sebenarnya, karena ia bebas caption
        # sejak awal.
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "2",
             "-i", str(mp4[0]), "-frames:v", "1",
             "-vf", "crop=1080:1080:0:120,scale=1080:1080,"
                    "pad=1920:1080:(ow-iw)/2:0:black",
             str(kerja / "src.png")],
            check=True, timeout=120)
        return "src.png", 1920, 1080, False

    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=1920x1080:rate=1:duration=1",
         "-frames:v", "1", str(kerja / "src.png")],
        check=True, timeout=120)
    return "src.png", 1920, 1080, False


def render(nama_layout: str | None = None, knob_tambahan: dict | None = None,
           kecil: bool = False) -> tuple[bytes, str]:
    """(isi berkas, media type). MP4 kalau sumbernya bergerak, PNG kalau tidak.

    `kecil` mengecilkan keluaran dan memaksa gambar diam, untuk deretan pilihan
    di halaman Submit — tiga video yang berputar bersamaan cuma bikin berat
    tanpa membantu membandingkan bentuk kotak.
    """
    lay = layout.ambil(nama_layout or settings.CLIP_LAYOUT)
    knob = {**knob_dari_settings(), **(knob_tambahan or {})}

    # Render ffmpeg butuh beberapa detik; setelan yang sama pasti menghasilkan
    # berkas yang sama, jadi tidak ada gunanya menghitung ulang saat orang
    # bolak-balik antar layout.
    # Jejak video contoh ikut masuk kunci. Tanpa itu, menambah atau mengganti
    # assets/preview.mp4 tidak mengubah apa pun sampai proses di-restart —
    # persis kelas kegagalan yang paling membingungkan: berkasnya sudah benar,
    # yang tampil masih yang lama, dan tidak ada satu pun error.
    contoh = (
        f"{CONTOH_MP4.stat().st_mtime_ns}:{CONTOH_MP4.stat().st_size}"
        if CONTOH_MP4.exists() else "kosong"
    )
    kunci = hashlib.sha1(
        json.dumps([lay.nama, knob, kecil, contoh], sort_keys=True,
                   default=str).encode()
    ).hexdigest()
    if kunci in _CACHE:
        return _CACHE[kunci]

    with tempfile.TemporaryDirectory() as td:
        kerja = Path(td)
        src, sw, sh, gerak = _sumber(kerja)
        gerak = gerak and not kecil

        teks = layout.pakai_caption(lay, knob)
        if teks:
            (kerja / "p.ass").write_text(
                build_ass(_kata_contoh(), 0.0, DETIK, lay, knob), encoding="utf-8")

        # Wajah dianggap di tengah-atas: preview menilai GEOMETRI dan gaya
        # teks, bukan ketepatan deteksi wajah pada satu frame.
        g = layout.geometri(lay, {"x": (sw - 608) // 2, "w": 608,
                                  "fx": 0.5, "fy": 0.38}, sw, sh)
        mask = None
        if layout.butuh_lapisan(lay):
            from pipeline.stages.render import _mask

            class _TanpaBatas:
                def remaining(self, cap=600.0):
                    return cap

            mask = _mask(kerja, lay, g, _TanpaBatas())

        vf = layout.filtergraph(lay, g, "p.ass" if teks else None, mask)
        if not vf:
            # Layout mentahan tidak punya filter sama sekali, dan pratinjaunya
            # tetap harus muat di bingkai HP yang 9:16. Bilah hitamnya bukan
            # kompromi — justru itu yang menyampaikan "rasionya memang bukan
            # 9:16", yang persis membedakan layout ini dari yang lain.
            vf = (f"scale={layout.OUT_W}:{layout.OUT_H}"
                  ":force_original_aspect_ratio=decrease,"
                  f"pad={layout.OUT_W}:{layout.OUT_H}:(ow-iw)/2:(oh-ih)/2:black")
        if kecil:
            # Dikecilkan SETELAH seluruh rantai: caption dirender pada resolusi
            # penuh dulu supaya ukuran dan ketebalan hurufnya sebanding dengan
            # hasil sungguhan.
            vf += ",scale=270:480"

        if gerak:
            keluar, tipe = "preview.mp4", "video/mp4"
            argumen = [
                "-i", src, "-t", str(DETIK), "-vf", vf, "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", keluar,
            ]
        else:
            keluar, tipe = "preview.png", "image/png"
            argumen = ["-i", src, "-vf", vf, "-frames:v", "1", keluar]

        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", *argumen],
            check=True, cwd=kerja, timeout=300)

        hasil = ((kerja / keluar).read_bytes(), tipe)

    _CACHE[kunci] = hasil
    return hasil


def pakai_contoh_bawaan() -> bool:
    """True kalau pratinjau memakai video contoh di repo, bukan klip pengguna."""
    return CONTOH_MP4.exists()


def bersihkan_cache() -> None:
    """Dipanggil setelah setelan disimpan — nilai yang berubah membuat seluruh
    hasil lama tidak lagi mewakili apa pun."""
    _CACHE.clear()
