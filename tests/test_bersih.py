"""Auto clear: apa yang dibuang, dan kapan TIDAK ada yang dibuang.

Fitur ini menghapus data tanpa ada orang yang menekan tombol, jadi yang paling
penting diuji justru jalur "jangan hapus": mati, hari tidak masuk akal, target
salah ketik. Tanpa database — urusan query ada di tests/api/test_bersih.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from api import bersih
from config.settings import settings

GAGAL = {"id": "gagal", "status": "failed", "clips": []}
BERKLIP = {"id": "berklip", "status": "done", "clips": [{"id": "c1"}]}
KOSONG = {"id": "kosong", "status": "done", "clips": []}
SEMUA = [GAGAL, BERKLIP, KOSONG]


@pytest.mark.parametrize("target,hapus,kosongkan", [
    ("keduanya", ["gagal", "berklip", "kosong"], []),
    # Job yang masih punya klip TIDAK dihapus: barisnya hilang berarti klipnya
    # lenyap dari halaman Hasil sementara berkasnya tertinggal di disk.
    ("task", ["gagal", "kosong"], []),
    ("hasil", [], ["berklip"]),
])
def test_rencana_per_target(target, hapus, kosongkan):
    assert bersih.rencana(SEMUA, target) == (hapus, kosongkan)


@pytest.fixture
def catat(monkeypatch):
    """Ganti semua efek samping dengan pencatat, dan nyalakan auto clear."""
    log = {"batas": None, "hapus": [], "kosongkan": [], "berkas": []}

    def daftar(batas):
        log["batas"] = batas
        return SEMUA

    monkeypatch.setattr(bersih.jobs, "list_selesai_sebelum", daftar)
    monkeypatch.setattr(bersih, "hapus_job", lambda j: log["hapus"].append(j) or True)
    monkeypatch.setattr(bersih.jobs, "kosongkan_clips", lambda j: log["kosongkan"].append(j))
    monkeypatch.setattr(bersih.storage, "delete_job", lambda j: log["berkas"].append(j))
    monkeypatch.setattr(settings, "AUTO_CLEAR_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_CLEAR_DAYS", 30)
    monkeypatch.setattr(settings, "AUTO_CLEAR_TARGET", "keduanya")
    return log


def test_mati_tidak_menyentuh_apa_pun(catat, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_CLEAR_ENABLED", False)
    assert bersih.sapu() == {"task": 0, "hasil": 0}
    assert catat["batas"] is None, "database bahkan tidak boleh ditanya"


@pytest.mark.parametrize("hari", [0, -5])
def test_hari_kurang_dari_satu_dianggap_mati(catat, monkeypatch, hari):
    monkeypatch.setattr(settings, "AUTO_CLEAR_DAYS", hari)
    bersih.sapu()
    assert catat["batas"] is None


def test_target_salah_ketik_tidak_jatuh_ke_keduanya(catat, monkeypatch):
    """Bawaannya "keduanya"; salah ketik tidak boleh berakhir menghapus semua klip."""
    monkeypatch.setattr(settings, "AUTO_CLEAR_TARGET", "semua")
    bersih.sapu()
    assert catat["hapus"] == [] and catat["kosongkan"] == []


def test_umur_dihitung_mundur_dari_sekarang(catat):
    sekarang = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    bersih.sapu(sekarang)
    assert catat["batas"] == sekarang - timedelta(days=30)


def test_keduanya_menghapus_lewat_jalur_tombol_hapus(catat):
    assert bersih.sapu() == {"task": 3, "hasil": 0}
    assert catat["hapus"] == ["gagal", "berklip", "kosong"]


def test_hasil_membuang_berkas_tapi_barisnya_tetap(catat, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_CLEAR_TARGET", " Hasil ")
    assert bersih.sapu() == {"task": 0, "hasil": 1}
    assert catat["hapus"] == []
    assert catat["kosongkan"] == ["berklip"] and catat["berkas"] == ["berklip"]
