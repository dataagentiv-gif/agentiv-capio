"""Halaman Setting menulis kredensial ke .env lewat HTTP.

Semua yang diuji di sini adalah batas kepercayaan. Kalau salah satunya jebol,
tidak ada yang error — key-nya cuma bocor atau tertimpa diam-diam.
"""
import pytest

from config import env_store
from config.settings import settings


@pytest.fixture
def env_tmp(tmp_path, monkeypatch):
    """Arahkan penulisan ke file sementara. Tanpa ini, menjalankan test akan
    menimpa .env sungguhan milik pengguna."""
    p = tmp_path / ".env"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_store, "ENV_PATH", p)
    monkeypatch.setattr(env_store, "reload", lambda: None)
    return p


# --- allowlist ---

def test_key_di_luar_allowlist_ditolak(env_tmp):
    """Tanpa allowlist, satu POST bisa menyuntikkan variabel apa pun ke .env."""
    assert env_store.write({"PATH": "/evil", "AWS_SECRET": "x"}) == []
    assert env_tmp.read_text(encoding="utf-8").strip() == ""


def test_key_yang_diizinkan_ditulis(env_tmp):
    assert env_store.write({"GROQ_API_KEY": "gsk_baru"}) == ["GROQ_API_KEY"]
    assert "gsk_baru" in env_tmp.read_text(encoding="utf-8")


def test_campuran_hanya_yang_diizinkan_lolos(env_tmp):
    hasil = env_store.write({"GEMINI_MODEL": "gemini-x", "HOME": "/tmp"})
    assert hasil == ["GEMINI_MODEL"]
    assert "HOME" not in env_tmp.read_text(encoding="utf-8")


# --- nilai ter-mask tidak boleh tersimpan ---

def test_nilai_ter_mask_diabaikan(env_tmp):
    """Halaman mengirim balik bentuk ter-mask untuk field yang tidak disentuh.
    Tanpa penjaga ini, menyimpan satu field akan menimpa key lain dengan
    titik-titik dan mematikan seluruh provider."""
    assert env_store.write({"GROQ_API_KEY": "gsk_ab••••••••3io8"}) == []
    assert env_tmp.read_text(encoding="utf-8").strip() == ""


def test_nilai_kosong_diabaikan(env_tmp):
    """Field rahasia sengaja dirender kosong; kosong berarti 'jangan diubah',
    bukan 'hapus key-nya'."""
    assert env_store.write({"GROQ_API_KEY": "", "R2_BUCKET": "   "}) == []


# --- pembacaan tidak boleh membocorkan rahasia ---

def test_rahasia_tidak_pernah_dikirim_utuh(monkeypatch):
    rahasia = "gsk_rahasiaSekaliJanganBocor123"
    monkeypatch.setattr(settings, "GROQ_API_KEY", rahasia)
    teks = str(env_store.read_public())
    assert rahasia not in teks
    assert "••••" in teks


def test_nilai_non_rahasia_tampil_apa_adanya(monkeypatch):
    monkeypatch.setattr(settings, "R2_BUCKET", "bucket-saya")
    f = [x for g in env_store.read_public()["groups"] for x in g["fields"]]
    assert next(x for x in f if x["key"] == "R2_BUCKET")["value"] == "bucket-saya"


def test_penanda_terisi_ikut_dikirim(monkeypatch):
    """UI perlu tahu key sudah ada atau belum tanpa melihat isinya."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_ada")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")
    f = {x["key"]: x for g in env_store.read_public()["groups"] for x in g["fields"]}
    assert f["GROQ_API_KEY"]["filled"] is True
    assert f["ELEVENLABS_API_KEY"]["filled"] is False


@pytest.mark.parametrize("nilai,harus", [("", ""), ("pendek", "••••••••")])
def test_mask_nilai_pendek_tidak_membocorkan_apa_pun(nilai, harus):
    assert env_store.mask(nilai) == harus


def test_mask_menyisakan_ujung_untuk_dikenali():
    m = env_store.mask("gsk_abcdefghijklmnop9999")
    assert m.startswith("gsk_ab") and m.endswith("9999") and "••••" in m


# --- infra tidak boleh bisa diubah dari UI ---

@pytest.mark.parametrize("key", ["DATABASE_URL", "REDIS_URL", "API_HOST", "API_PORT"])
def test_infra_tidak_bisa_ditulis_dari_ui(env_tmp, key):
    """Salah isi sekali, aplikasinya mati DAN halaman setting-nya ikut mati."""
    assert key not in env_store.WRITABLE
    assert env_store.write({key: "rusak"}) == []
