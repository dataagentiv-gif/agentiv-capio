"""Rotasi key lintas proses.

Yang memakai key adalah worker; yang menampilkan statusnya adalah proses API.
Keduanya proses terpisah, jadi penghitung di memori tidak akan pernah cocok.
Rotasinya lewat Redis, dan kalau Redis mati pipeline TIDAK BOLEH ikut mati —
kehilangan panel status jauh lebih ringan daripada job yang gagal.
"""
import pytest

import keypool
from config.settings import settings


@pytest.fixture
def tiga(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEYS", "aaaa1111bbbb2222,cccc3333dddd4444,eeee5555ffff6666")
    return settings.groq_keys


@pytest.fixture
def tanpa_redis(monkeypatch):
    """Paksa jalur cadangan: Redis tidak bisa dihubungi."""
    def meledak():
        raise ConnectionError("redis mati")
    monkeypatch.setattr(keypool, "_redis", meledak)


# --- parsing ---

def test_groq_menerima_banyak_key(tiga):
    assert len(tiga) == 3


def test_nama_lama_tetap_terbaca(monkeypatch):
    """.env yang sudah ada memakai GROQ_API_KEY tunggal; jangan sampai mati."""
    monkeypatch.setattr(settings, "GROQ_API_KEYS", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_lama")
    assert settings.groq_keys == ["gsk_lama"]


def test_nama_baru_menang_atas_nama_lama(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEYS", "baru1,baru2")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_lama")
    assert settings.groq_keys == ["baru1", "baru2"]


# --- rotasi ---

def test_berputar_x_plus_1(tiga, tanpa_redis):
    urut = [keypool.ambil("groq")[0] for _ in range(6)]
    # Penghitungnya global dan bisa mulai dari mana saja; yang diuji polanya:
    # maju satu tiap panggilan, berulang tiap 3.
    assert urut[3:] == urut[:3]
    assert set(urut) == {0, 1, 2}


def test_indeks_dan_key_cocok(tiga, tanpa_redis):
    idx, key = keypool.ambil("groq")
    assert key == tiga[idx]


def test_tanpa_key_ditolak_dengan_pesan_jelas(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEYS", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError, match="groq"):
        keypool.ambil("groq")


def test_redis_mati_tidak_menggagalkan_rotasi(tiga, tanpa_redis):
    """Panel status boleh hilang; job tidak boleh ikut mati."""
    assert keypool.ambil("groq")[1] in tiga
    keypool.lapor("groq", 0, True, "OK")   # tidak boleh melempar


# --- status untuk UI ---

def test_status_menandai_satu_key_sebagai_berikutnya(tiga, tanpa_redis):
    s = keypool.status("groq")
    assert s["jumlah"] == 3
    assert sum(1 for k in s["keys"] if k["berikutnya"]) == 1


def test_status_tidak_membocorkan_key_utuh(tiga, tanpa_redis):
    teks = str(keypool.status("groq"))
    for k in tiga:
        assert k not in teks
    assert "••••" in teks


def test_pool_kosong_dilaporkan_nol(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    s = keypool.status("gemini")
    assert s["jumlah"] == 0 and s["keys"] == []
