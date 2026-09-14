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
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "aaaa1111bbbb2222,cccc3333dddd4444,eeee5555ffff6666")
    return settings.gemini_keys


@pytest.fixture
def tanpa_redis(monkeypatch):
    """Paksa jalur cadangan: Redis tidak bisa dihubungi."""
    def meledak():
        raise ConnectionError("redis mati")
    monkeypatch.setattr(keypool, "_redis", meledak)


# --- parsing ---

def test_menerima_banyak_key(tiga):
    assert len(tiga) == 3


# --- rotasi ---

def test_berputar_x_plus_1(tiga, tanpa_redis):
    urut = [keypool.ambil("gemini")[0] for _ in range(6)]
    # Penghitungnya global dan bisa mulai dari mana saja; yang diuji polanya:
    # maju satu tiap panggilan, berulang tiap 3.
    assert urut[3:] == urut[:3]
    assert set(urut) == {0, 1, 2}


def test_indeks_dan_key_cocok(tiga, tanpa_redis):
    idx, key = keypool.ambil("gemini")
    assert key == tiga[idx]


def test_tanpa_key_ditolak_dengan_pesan_jelas(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    with pytest.raises(RuntimeError, match="gemini"):
        keypool.ambil("gemini")


def test_redis_mati_tidak_menggagalkan_rotasi(tiga, tanpa_redis):
    """Panel status boleh hilang; job tidak boleh ikut mati."""
    assert keypool.ambil("gemini")[1] in tiga
    keypool.lapor("gemini", 0, True, "OK")   # tidak boleh melempar


# --- status untuk UI ---

def test_status_menandai_satu_key_sebagai_berikutnya(tiga, tanpa_redis):
    s = keypool.status("gemini")
    assert s["jumlah"] == 3
    assert sum(1 for k in s["keys"] if k["berikutnya"]) == 1


def test_status_tidak_membocorkan_key_utuh(tiga, tanpa_redis):
    teks = str(keypool.status("gemini"))
    for k in tiga:
        assert k not in teks
    assert "••••" in teks


def test_pool_kosong_dilaporkan_nol(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    s = keypool.status("gemini")
    assert s["jumlah"] == 0 and s["keys"] == []


# --- kontrak per pool ---
#
# Cuma satu pool sekarang, tapi parametrize dipertahankan: menambah provider
# baru berarti baris ini otomatis ikut mengujinya, tanpa kode test baru.

def test_semua_provider_punya_pool():
    assert set(keypool.POOLS) == {"gemini"}


@pytest.mark.parametrize("pool", keypool.POOLS)
def test_tiap_pool_punya_sumber_key_dan_env_field(pool):
    """Nama pool dipakai untuk menemukan properti settings DAN nama env var.
    Kalau salah satunya tidak ada, kegagalannya baru muncul saat dipakai."""
    assert hasattr(settings, f"{pool}_keys")
    assert keypool.ENV_FIELD[pool] == f"{pool.upper()}_API_KEYS"


@pytest.mark.parametrize("pool", keypool.POOLS)
def test_tiap_pool_bisa_dirotasi(monkeypatch, pool, tanpa_redis):
    monkeypatch.setattr(settings, keypool.ENV_FIELD[pool], "k1,k2,k3")
    diambil = {keypool.ambil(pool)[1] for _ in range(6)}
    assert diambil == {"k1", "k2", "k3"}, f"{pool} tidak berputar ke semua key"


@pytest.mark.parametrize("pool", keypool.POOLS)
def test_nama_lama_tunggal_masih_terbaca(monkeypatch, pool):
    """.env milik orang yang sudah memasang versi sebelumnya tidak boleh mati
    hanya karena nama variabelnya berubah jadi jamak."""
    tunggal = f"{pool.upper()}_API_KEY"
    if not hasattr(settings, tunggal):
        pytest.skip(f"{pool} tidak punya nama tunggal")
    monkeypatch.setattr(settings, keypool.ENV_FIELD[pool], "")
    monkeypatch.setattr(settings, tunggal, "key-lama")
    assert keypool.keys(pool) == ["key-lama"]
