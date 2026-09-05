"""Analisis perbandingan transkrip.

Yang diuji di sini bagian yang benar-benar memutuskan sesuatu: apakah dua
bentuk kegagalan yang sangat berbeda bisa dibedakan. Panggilan ke provider
tidak diuji — itu jaringan, bukan logika.

Dua bentuk itu:

  berpindah bahasa   keluaran berubah jadi aksara lain. Terlihat dari hurufnya.
  menerjemahkan      kalimatnya diubah maknanya tapi tetap huruf Latin. TIDAK
                     terlihat dari hurufnya sama sekali — hanya dari
                     perbandingan kata terhadap provider lain.

Kalau keduanya dilaporkan sama, laporan ini kehilangan seluruh gunanya: yang
kedua persis kegagalan yang paling mudah lolos tanpa disadari.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import banding_asr as ba  # noqa: E402


# --- deteksi pindah bahasa ---

def test_teks_indonesia_murni_nol_non_latin():
    assert ba.rasio_non_latin("Halo semua, ini contoh kalimat biasa.") == 0.0


def test_aksara_jepang_terhitung():
    """Inilah yang menghasilkan temuan 29,6% itu."""
    assert ba.rasio_non_latin("halo これは日本語です") > 40


def test_angka_dan_tanda_baca_tidak_mengencerkan_angkanya():
    """Dihitung dari HURUF saja. Ikut menghitung spasi dan digit membuat teks
    penuh angka terlihat lebih 'aman' dari yang sebenarnya."""
    a = ba.rasio_non_latin("日本語")
    b = ba.rasio_non_latin("日本語 123 456 !!! ... 789")
    assert a == b == 100.0


def test_teks_kosong_tidak_membagi_nol():
    assert ba.rasio_non_latin("") == 0.0
    assert ba.rasio_non_latin("123 !!!") == 0.0


# --- laporan membedakan dua bentuk kegagalan ---

def test_pindah_bahasa_disebut_eksplisit():
    teks = ba.laporan(Path("uji.mp4"), {
        "elevenlabs": "ini adalah kalimat bahasa indonesia yang biasa saja",
        "groq": "これは日本語のテキストです",
    })
    assert "berpindah bahasa" in teks
    assert "groq" in teks


def test_terjemahan_disebut_saat_huruf_tetap_latin():
    """Kemiripan rendah TANPA huruf asing berarti diterjemahkan. Kalau ini
    dilaporkan sama dengan pindah bahasa, kegagalan yang paling mudah lolos
    justru yang paling tidak terjelaskan."""
    teks = ba.laporan(Path("uji.mp4"), {
        "elevenlabs": "tools like google analytics membantu mengukur engagement",
        "groq": "tua seperti analitik menolong menghitung keterlibatan pengguna",
    })
    assert "penerjemahan" in teks.lower()
    assert "berpindah bahasa" not in teks


def test_dua_transkrip_yang_sama_tidak_dituduh_apa_apa():
    sama = "ini kalimat yang sama persis di kedua provider tanpa ada bedanya"
    teks = ba.laporan(Path("uji.mp4"), {"a": sama, "b": sama})
    assert "berpindah bahasa" not in teks
    assert "penerjemahan" not in teks.lower()
    assert "100.0%" in teks


def test_laporan_memuat_angka_yang_bisa_dibandingkan():
    teks = ba.laporan(Path("uji.mp4"), {
        "elevenlabs": " ".join(["kata"] * 50),
        "groq": " ".join(["kata"] * 30),
    })
    assert "Jumlah kata" in teks
    assert "Huruf non-Latin" in teks
    assert "Kemiripan kata" in teks


# --- potongan berdampingan ---

def test_potongan_beda_menunjukkan_bagian_yang_berubah():
    """Angka persentase membuat orang mengangguk; satu kalimat Indonesia yang
    keluar sebagai aksara Jepang membuat mereka ingat."""
    beda = ba.potongan_beda(
        "awal sama sekali ini bagian indonesia yang panjang sekali akhir sama",
        "awal sama sekali これは日本語のテキストです akhir sama",
    )
    assert beda
    assert "indonesia" in beda[0][0]


def test_potongan_beda_kosong_saat_identik():
    assert ba.potongan_beda("sama persis di kedua sisi", "sama persis di kedua sisi") == []


def test_beda_sangat_pendek_diabaikan():
    """Satu-dua kata beda itu wajar di transkrip mana pun — menampilkannya cuma
    menenggelamkan potongan yang benar-benar berarti."""
    a = "satu dua tiga empat lima enam tujuh delapan sembilan sepuluh"
    b = "satu dua tiga empat lima enam tujuh delapan sembilan sebelas"
    assert ba.potongan_beda(a, b) == []
