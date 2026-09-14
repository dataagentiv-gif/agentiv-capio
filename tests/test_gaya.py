"""Saringan knob tampilan per video di batas kepercayaan (JobCreate.gaya).

Sengaja tanpa database: yang diuji cuma validatornya. Versi yang menembak
endpoint ada di tests/api/test_penjaga.py, dan ikut di-skip saat Postgres mati.
"""
from api.schemas import JobCreate

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def gaya(**isi):
    return JobCreate(url=URL, gaya=isi).gaya


def test_bayangan_nol_tidak_dibuang_saringan_kosong():
    """0% bayangan adalah pilihan, bukan 'ikut default' — dan `0` justru yang
    dibuang saringan untuk knob lain."""
    assert gaya(redup_gelap=0) == {"redup_gelap": 0}


def test_bayangan_dipaksa_jadi_bilangan_bulat():
    assert gaya(redup_gelap="70", redup_luas=60.7) == {"redup_gelap": 70, "redup_luas": 60}


def test_gaya_kata_aktif_yang_dikenal_lolos():
    assert gaya(active_word_style="background_scale") == {"active_word_style": "background_scale"}


def test_gaya_kata_aktif_asing_dibuang():
    assert gaya(active_word_style="neon") is None


def test_ukuran_blok_nol_tetap_tersimpan():
    """Radius 0 = sudut siku, bukan 'ikut default'."""
    assert gaya(active_word_border_radius=0, active_word_padding_y="0") == {
        "active_word_border_radius": 0, "active_word_padding_y": 0}


def test_warna_blok_ikut_tersimpan():
    assert gaya(active_word_background_color="FF0000") == {
        "active_word_background_color": "FF0000"}


def test_bayangan_ngawur_dibuang_bukan_ditolak():
    """Form versi lama atau nilai rusak tidak boleh menggagalkan submit."""
    assert gaya(redup_gelap="abc", redup_luas=float("inf")) is None
