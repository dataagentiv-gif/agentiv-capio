"""Contoh gaya caption, dirender lewat jalur yang sama persis dengan produksi.

Bukan tiruan HTML, dan itu bukan soal kerapian. Tiruan CSS akan merender pakai
font milik BROWSER, sementara video dirender libass pakai font di dalam
container — dan sudah terbukti keduanya bisa berbeda tanpa satu pun tanda
(`fc-match Arial` di image ini pernah mengembalikan DejaVu Sans). Preview yang
berbohong justru soal hal yang paling ingin dilihat lebih buruk daripada tidak
ada preview.

Alasan adanya sama sekali: tanpa ini, melihat akibat satu perubahan warna
menuntut menjalankan job penuh — 3 menit sampai satu jam. Itu yang membuat knob
apa pun tidak pernah terpakai.

Yang ditanya panel ini cuma SATU: "caption dengan setelanku kelihatan seperti
apa?" Pertanyaan yang satunya lagi — "layout ini bentuknya seperti apa?" —
dijawab contoh hasil sungguhan di web/static/contoh/, dan itu jawaban yang jauh
lebih jujur daripada apa pun yang bisa dirender di sini. Karena itu latarnya
polos: gambar bergerak di belakang teks justru menutupi hal yang sedang dinilai.

Tetap VIDEO, bukan gambar diam: yang paling menentukan dari gaya caption adalah
sorotan kata yang berpindah, dan itu tidak ada di satu frame.
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

# Abu-abu netral, dan angkanya bukan selera. Di atas hitam, garis luar caption
# ikut hilang; di atas putih, isi hurufnya yang hilang. Keduanya membuat
# pratinjau berbohong tepat di hal yang paling ingin diperiksa orang.
LATAR = "0x3a3f47"
# 16:9 seperti sumber sungguhan, bukan 9:16 keluaran: geometri layout dihitung
# DARI ukuran sumber, jadi memberinya rentang yang lain berarti kotak dan
# gradasinya jatuh di tempat yang tidak sama dengan hasil aslinya.
SRC_W, SRC_H = 1920, 1080
FONT_DIR = str((Path(__file__).resolve().parent.parent / "assets" / "fonts")) \
    .replace("\\", "/").replace(":", "\\:")

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


def render(nama_layout: str | None = None,
           knob_tambahan: dict | None = None) -> tuple[bytes, str]:
    """(isi berkas, media type)."""
    knob = {**knob_dari_settings(), **(knob_tambahan or {})}
    lay = layout.terapkan_knob(layout.ambil(nama_layout or settings.CLIP_LAYOUT), knob)

    # Render ffmpeg butuh waktu; setelan yang sama pasti menghasilkan berkas
    # yang sama, jadi tidak ada gunanya menghitung ulang saat orang bolak-balik
    # antar layout.
    kunci = hashlib.sha1(
        json.dumps([lay.nama, knob], sort_keys=True, default=str).encode()
    ).hexdigest()
    if kunci in _CACHE:
        return _CACHE[kunci]

    with tempfile.TemporaryDirectory() as td:
        kerja = Path(td)
        sw, sh = SRC_W, SRC_H

        teks = layout.pakai_caption(lay, knob)
        if teks:
            (kerja / "p.ass").write_text(
                build_ass(_kata_contoh(), 0.0, DETIK, lay, knob), encoding="utf-8")

        # Wajah dianggap di tengah-atas: preview menilai GEOMETRI dan gaya
        # teks, bukan ketepatan deteksi wajah pada satu frame.
        crop = {"x": (sw - 608) // 2, "w": 608, "fx": 0.5, "fy": 0.38,
                "duo": [{"fx": 0.30, "fy": 0.38},
                         {"fx": 0.70, "fy": 0.38}]}
        g = layout.geometri(lay, crop, sw, sh)
        mask = None
        if layout.butuh_lapisan(lay):
            from pipeline.stages.render import _mask

            class _TanpaBatas:
                def remaining(self, cap=600.0):
                    return cap

            mask = _mask(kerja, lay, g, _TanpaBatas())

        # Preview dari source lokal tidak memasang font ke Windows seperti
        # Dockerfile. Tanpa fontsdir libass diam-diam memakai Arial, sementara
        # posisi kata dihitung dari Poppins — hasilnya kata blok bertumpuk.
        ass = f"p.ass:fontsdir='{FONT_DIR}'" if teks else None
        vf = layout.filtergraph(lay, g, ass, mask)
        kompleks = None
        if lay.duo:
            a, b = layout.geometri_duo(lay, crop, sw, sh)
            cap = f",subtitles={ass}" if teks else ""
            kompleks = (
                f"[0:v]split=2[va][vb];"
                f"[va]crop={a['cw']}:{a['ch']}:{a['cx']}:{a['cy']},"
                f"scale={layout.OUT_W}:{layout.OUT_H // 2},setsar=1[top];"
                f"[vb]crop={b['cw']}:{b['ch']}:{b['cx']}:{b['cy']},"
                f"scale={layout.OUT_W}:{layout.OUT_H // 2},setsar=1[bottom];"
                f"[top][bottom]vstack=inputs=2{cap}[outv]"
            )
        if not vf:
            # Layout mentahan tidak punya filter sama sekali, dan pratinjaunya
            # tetap harus muat di bingkai HP yang 9:16. Bilah hitamnya bukan
            # kompromi — justru itu yang menyampaikan "rasionya memang bukan
            # 9:16", yang persis membedakan layout ini dari yang lain.
            vf = (f"scale={layout.OUT_W}:{layout.OUT_H}"
                  ":force_original_aspect_ratio=decrease,"
                  f"pad={layout.OUT_W}:{layout.OUT_H}:(ow-iw)/2:(oh-ih)/2:black")
        # Satu perintah ffmpeg, dan sumbernya dibangkitkan lavfi — tidak ada
        # video yang di-decode sama sekali.
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"color=c={LATAR}:s={sw}x{sh}:r=15",
             "-t", str(DETIK),
             *(["-filter_complex", kompleks, "-map", "[outv]"]
               if kompleks else ["-vf", vf]),
             "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "preview.mp4"],
            check=True, cwd=kerja, timeout=300)

        hasil = ((kerja / "preview.mp4").read_bytes(), "video/mp4")

    _CACHE[kunci] = hasil
    return hasil


def bersihkan_cache() -> None:
    """Dipanggil setelah setelan disimpan — nilai yang berubah membuat seluruh
    hasil lama tidak lagi mewakili apa pun."""
    _CACHE.clear()
