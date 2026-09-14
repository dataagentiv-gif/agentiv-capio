"""Ukuran teks dalam piksel keluaran, dihitung dengan cara libass menghitungnya.

Dipakai hanya oleh gaya kata aktif bertipe blok (pipeline/stages/caption.py).
Bloknya digambar sendiri, jadi posisi tiap kata harus diketahui dalam piksel —
sesuatu yang di jalur caption biasa diurus libass dan tidak pernah terlihat
dari Python.

Skalanya BUKAN em. libass meniru VSFilter: Fontsize dipetakan ke tinggi
usWinAscent + usWinDescent tabel OS/2, bukan ke em. Pada Poppins, "Fontsize
96" menggambar em sekitar 54 px — menghitung dengan em membuat tiap kata
terukur hampir dua kali lebih lebar dari aslinya.

Kerning tidak dihitung. Selisihnya beberapa piksel per kata, dan yang terkena
cuma jarak antar kata — blok dan katanya tetap sepusat karena keduanya
ditaruh di titik tengah hasil hitungan yang sama.
"""
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
#: Nama font di .ass -> berkasnya. Harus sepakat dengan yang dipasang Dockerfile
#: ke fontconfig; nama yang tidak dikenal diukur memakai Poppins.
BERKAS = {
    "poppins": "Poppins-Bold.ttf",
    "anton": "Anton-Regular.ttf",
    "archivo black": "ArchivoBlack-Regular.ttf",
    "lora": "Lora.ttf",
}
#: DejaVu tidak ikut di assets/ — di image ia sudah ada sebagai font sistem.
DEJAVU = ("/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts")


def _path(nama: str, tebal: bool) -> Path:
    kunci = str(nama).strip().lower()
    if kunci == "dejavu sans":
        berkas = "DejaVuSans-Bold.ttf" if tebal else "DejaVuSans.ttf"
        for d in DEJAVU:
            if (Path(d) / berkas).is_file():
                return Path(d) / berkas
    return FONTS / BERKAS.get(kunci, BERKAS["poppins"])


@lru_cache(maxsize=None)
def _font(nama: str, tebal: bool) -> tuple:
    """(cmap, advance per glyph, win ascent, win descent, cap height, descender)."""
    f = TTFont(_path(nama, tebal))
    # Lora satu berkas variabel. Minta tebal, libass memilih instance Bold-nya
    # yang hurufnya lebih lebar — mengukur instance bawaan (Regular) membuat
    # tiap kata terukur terlalu sempit.
    if tebal and "fvar" in f:
        from fontTools.varLib.instancer import instantiateVariableFont

        f = instantiateVariableFont(f, {"wght": 700})
    os2, hhea = f["OS/2"], f["hhea"]
    return (
        f.getBestCmap(),
        {g: m[0] for g, m in f["hmtx"].metrics.items()},
        os2.usWinAscent,
        os2.usWinDescent,
        getattr(os2, "sCapHeight", 0) or hhea.ascent * 0.7,
        -hhea.descent,
    )


def lebar(teks: str, font: str, ukuran: float, tebal: bool) -> float:
    """Lebar advance teks dalam piksel keluaran."""
    cmap, adv, naik, turun, *_ = _font(font, tebal)
    # Glyph yang tidak ada di font ini digambar libass dengan font cadangan
    # yang ukurannya tidak diketahui; .notdef adalah tebakan paling dekat.
    kosong = adv.get(".notdef", 0)
    return sum(adv.get(cmap.get(ord(c)), kosong) for c in teks) * ukuran / (naik + turun)


def vertikal(font: str, ukuran: float, tebal: bool) -> tuple[float, float, float, float]:
    """(tinggi baris, geser ke tengah kapital, tinggi kapital, descender), piksel.

    Kotak baris yang dipakai libass untuk meratakan teks — termasuk titik
    tengah \\an5 — adalah win ascent + win descent, jadi tingginya persis
    `ukuran`. Tapi titik tengah kotak itu BUKAN tengah hurufnya: terukur pada
    render, Poppins duduk ~5 px di atasnya dan Anton ~6 px di bawahnya pada
    ukuran 96. `geser` = jarak dari titik tengah kotak ke tengah huruf kapital,
    positif ke bawah — ditambahkan ke posisi blok supaya hurufnya yang di
    tengah blok, bukan kotak tak kasatmatanya.
    """
    _, _, naik, turun, cap, ekor = _font(font, tebal)
    s = ukuran / (naik + turun)
    return ukuran, ((naik - turun) / 2 - cap / 2) * s, cap * s, ekor * s
