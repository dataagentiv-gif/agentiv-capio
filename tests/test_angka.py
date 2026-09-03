"""Angka yang dieja diubah jadi digit sebelum masuk caption.

Alasannya ruang layar, bukan kebenaran: caption dibatasi 4 kata / 22 karakter
per tampilan, dan "seratus empat puluh empat Hertz" (5 kata / 31 karakter)
pecah jadi dua tampilan sementara "144 Hertz" muat dalam satu.

Bahaya utamanya bukan gagal mengubah, melainkan mengubah yang bukan bilangan:
"salah satu" yang jadi "salah 1" merusak kalimat, dan bentuk itu jauh lebih
sering muncul daripada bilangan tunggal yang perlu jadi digit.
"""
import pytest

from asr.angka import normalkan


def kata(*ws: str) -> list[dict]:
    return [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate(ws)]


def teks(words: list[dict]) -> str:
    return " ".join(w["w"] for w in words)


# --- rangkaian bilangan ---

@pytest.mark.parametrize("ucapan,harap", [
    ("seratus empat puluh empat", "144"),
    ("dua puluh", "20"),
    ("dua belas", "12"),
    ("sebelas", "11"),
    ("sepuluh", "10"),
    ("lima puluh enam", "56"),
    ("seribu dua ratus", "1200"),
    ("dua ribu dua puluh lima", "2025"),
    ("sembilan belas", "19"),
    ("seratus", "100"),
    ("seratus ribu", "100000"),
])
def test_rangkaian_jadi_digit(ucapan, harap):
    assert teks(normalkan(kata(*ucapan.split()))) == harap


def test_kalimat_utuh():
    hasil = teks(normalkan(kata(
        "refresh", "rate", "nya", "seratus", "empat", "puluh", "empat", "Hertz")))
    assert hasil == "refresh rate nya 144 Hertz"


# --- yang TIDAK boleh diubah ---

def test_satu_sebagai_kata_biasa_dibiarkan():
    """Regresi paling penting: 'salah satu' bukan bilangan."""
    assert teks(normalkan(kata("salah", "satu", "cara"))) == "salah satu cara"


def test_satuan_tunggal_tanpa_satuan_ukur_dibiarkan():
    assert teks(normalkan(kata("ada", "dua", "orang"))) == "ada dua orang"


def test_satuan_tunggal_dengan_satuan_ukur_diubah():
    """'delapan giga' jelas bilangan — bentuk paling sering di konten teknis."""
    assert teks(normalkan(kata("RAM", "nya", "delapan", "giga"))) == "RAM nya 8 giga"


def test_persen_ikut_dihitung_satuan():
    assert teks(normalkan(kata("baru", "lima", "persen"))) == "baru 5 persen"


def test_kata_bukan_bilangan_tidak_disentuh():
    assert teks(normalkan(kata("halo", "dunia"))) == "halo dunia"


def test_transkrip_yang_sudah_digit_tidak_berubah():
    """Groq sudah memakai digit — langkah ini harus jadi operasi kosong."""
    asal = kata("layarnya", "144Hz", "dan", "120fps")
    assert teks(normalkan(asal)) == "layarnya 144Hz dan 120fps"


# --- waktu dan tanda baca ---

def test_rentang_waktu_dipertahankan():
    """Sorotan karaoke harus menyala selama angkanya diucapkan, bukan hanya
    selama kata pertamanya."""
    hasil = normalkan(kata("seratus", "empat", "puluh", "empat"))
    assert len(hasil) == 1
    assert hasil[0]["s"] == 0.0
    assert hasil[0]["e"] == pytest.approx(1.9)


def test_tanda_baca_di_ujung_dipertahankan():
    """Titik menentukan pemenggalan kalimat di Stage 3 — kalau hilang, batas
    klip kehilangan salah satu penandanya."""
    assert teks(normalkan(kata("harganya", "dua", "juta."))) == "harganya 2 juta."


# --- angka besar ditulis dengan kata skalanya ---
#
# "20000000" secara harfiah benar tapi tidak terbaca sebagai apa pun dalam
# sekilas pandang, dan caption cuma tampil beberapa detik. "20 juta" adalah
# cara orang benar-benar menuliskannya.

@pytest.mark.parametrize("ucapan,harap", [
    ("dua puluh juta", "20 juta"),
    ("tiga juta", "3 juta"),
    ("dua miliar", "2 miliar"),
    # Kelipatan tidak bulat tetap digit penuh — "2 juta 500 ribu" malah lebih
    # panjang daripada angkanya sendiri.
    ("dua juta lima ratus ribu", "2500000"),
    # Tahun jangan ikut dipendekkan.
    ("dua ribu dua puluh empat", "2024"),
])
def test_angka_besar_memakai_kata_skala(ucapan, harap):
    assert teks(normalkan(kata(*ucapan.split()))) == harap


# --- batas rangkaian ---

def test_tanda_baca_memutus_dua_bilangan():
    """Regresi dari transkrip sungguhan: 'belasan juta, dua puluh juta' pernah
    menyatu jadi satu bilangan 21000000, dan komanya hilang."""
    hasil = teks(normalkan(kata("belasan", "juta,", "dua", "puluh", "juta")))
    assert hasil == "belasan juta, 20 juta"


def test_kata_skala_tanpa_bilangan_bukan_bilangan():
    """'belasan juta' memakai 'juta' sebagai satuan. Menganggapnya '1 juta'
    mengarang isi yang tidak pernah diucapkan."""
    assert teks(normalkan(kata("harganya", "belasan", "juta"))) == "harganya belasan juta"


def test_daftar_kosong_aman():
    assert normalkan([]) == []
