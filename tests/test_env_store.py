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
    assert env_store.write({"GROQ_API_KEYS": "gsk_baru"}) == ["GROQ_API_KEYS"]
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
    assert env_store.write({"GROQ_API_KEYS": "gsk_ab••••••••3io8"}) == []
    assert env_tmp.read_text(encoding="utf-8").strip() == ""


def test_nilai_kosong_diabaikan(env_tmp):
    """Field rahasia sengaja dirender kosong; kosong berarti 'jangan diubah',
    bukan 'hapus key-nya'."""
    assert env_store.write({"GROQ_API_KEYS": "", "GEMINI_MODEL": "   "}) == []


# --- pembacaan tidak boleh membocorkan rahasia ---

def test_rahasia_tidak_pernah_dikirim_utuh(monkeypatch):
    rahasia = "gsk_rahasiaSekaliJanganBocor123"
    monkeypatch.setattr(settings, "GROQ_API_KEYS", rahasia)
    teks = str(env_store.read_public())
    assert rahasia not in teks
    assert "••••" in teks


def test_nilai_non_rahasia_tampil_apa_adanya(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-x")
    f = [x for g in env_store.read_public()["groups"] for x in g["fields"]]
    assert next(x for x in f if x["key"] == "GEMINI_MODEL")["value"] == "gemini-x"


def test_penanda_terisi_ikut_dikirim(monkeypatch):
    """UI perlu tahu key sudah ada atau belum tanpa melihat isinya."""
    monkeypatch.setattr(settings, "GROQ_API_KEYS", "gsk_ada")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", "")
    f = {x["key"]: x for g in env_store.read_public()["groups"] for x in g["fields"]}
    assert f["GROQ_API_KEYS"]["filled"] is True
    assert f["ELEVENLABS_API_KEYS"]["filled"] is False


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


# --- angka desimal ---
#
# Locale Indonesia menampilkan 0.25 sebagai "0,25" di input number. Koma yang
# lolos ke .env membuat pydantic gagal mem-parse float, dan yang rusak bukan
# cuma field itu — SELURUH konfigurasi gagal dimuat dan aplikasinya tidak start.

def test_koma_desimal_dinormalkan(env_tmp):
    assert env_store.write({"SILENCE_MIN_DUR": "0,25"}) == ["SILENCE_MIN_DUR"]
    assert "0.25" in env_tmp.read_text(encoding="utf-8")


def test_koma_desimal_pada_nilai_negatif(env_tmp):
    env_store.write({"SNAP_MAX_DRIFT": "1,2"})
    assert "1.2" in env_tmp.read_text(encoding="utf-8")


@pytest.mark.parametrize("sampah", ["abc", "1.2.3", "--5", "1 2"])
def test_angka_ngawur_dilewati_bukan_ditulis(env_tmp, sampah):
    """Menulisnya mentah akan membuat aplikasi gagal start di jalankan berikutnya."""
    assert env_store.write({"MIN_CLIP_SEC": sampah}) == []
    assert env_tmp.read_text(encoding="utf-8").strip() == ""


def test_field_teks_tidak_ikut_dinormalkan(env_tmp):
    """Koma di GEMINI_API_KEYS memisahkan beberapa key — jangan diubah."""
    env_store.write({"GEMINI_API_KEYS": "key1,key2"})
    assert "key1,key2" in env_tmp.read_text(encoding="utf-8")


# --- penulisan .env di tempat ---
#
# python-dotenv.set_key menulis ke file sementara lalu os.replace, dan itu
# GAGAL di Docker: .env di-bind-mount sebagai satu file, jadi menggantinya
# berarti mengganti inode — kernel menolak dengan "Device or resource busy".
# Halaman Setting jadi tidak bisa menyimpan apa pun justru pada cara pemasangan
# yang paling disarankan.

def test_komentar_dan_urutan_baris_dipertahankan(env_tmp):
    env_tmp.write_text("# catatan penting\nGROQ_API_KEYS=lama\n# ekor\n", encoding="utf-8")
    env_store.write({"GROQ_API_KEYS": "baru"})
    isi = env_tmp.read_text(encoding="utf-8")
    assert "# catatan penting" in isi and "# ekor" in isi
    assert "GROQ_API_KEYS=baru" in isi and "lama" not in isi


def test_key_baru_ditambahkan_di_akhir(env_tmp):
    env_tmp.write_text("GROQ_API_KEY=a\n", encoding="utf-8")
    env_store.write({"GEMINI_MODEL": "gemini-x"})
    assert "GEMINI_MODEL=gemini-x" in env_tmp.read_text(encoding="utf-8")


def test_key_yang_dikomentari_tidak_ditimpa(env_tmp):
    """`# MIN_CLIP_SEC=30` adalah dokumentasi, bukan nilai aktif."""
    env_tmp.write_text("# MIN_CLIP_SEC=30\n", encoding="utf-8")
    env_store.write({"MIN_CLIP_SEC": "45"})
    isi = env_tmp.read_text(encoding="utf-8")
    assert "# MIN_CLIP_SEC=30" in isi
    assert "\nMIN_CLIP_SEC=45" in isi


def test_nilai_berspasi_dikutip(env_tmp):
    env_store.write({"WORK_DIR": "C:/folder ada spasi"})
    assert 'WORK_DIR="C:/folder ada spasi"' in env_tmp.read_text(encoding="utf-8")


def test_baris_baru_ditolak(env_tmp):
    """Jalan pintas menulis variabel apa pun tanpa lewat allowlist."""
    assert env_store.write({"GEMINI_MODEL": "x\nADMIN=1"}) == []
    assert "ADMIN" not in env_tmp.read_text(encoding="utf-8")


def test_hasil_tulisan_masih_terbaca_pydantic(env_tmp, monkeypatch):
    """Penjaga sesungguhnya: apa pun yang ditulis harus tetap bisa dimuat.
    Satu nilai yang tidak terbaca membuat SELURUH konfigurasi gagal."""
    from dotenv import dotenv_values

    env_store.write({
        "GROQ_API_KEYS": "gsk_abc123",
        "WORK_DIR": "C:/ada spasi",
        "SILENCE_MIN_DUR": "0,45",
        "GEMINI_API_KEYS": "k1,k2",
    })
    v = dotenv_values(env_tmp)
    assert v["GROQ_API_KEYS"] == "gsk_abc123"
    assert v["WORK_DIR"] == "C:/ada spasi"
    assert v["SILENCE_MIN_DUR"] == "0.45"
    assert v["GEMINI_API_KEYS"] == "k1,k2"


# --- environment variable vs isi file ---
#
# pydantic-settings memberi prioritas pada env var di atas file .env, dan di
# Docker compose memuat .env ke environment container saat start. Tanpa
# penanganan khusus, setiap setelan yang sudah terisi saat container menyala
# tidak akan pernah bisa diubah dari halaman Setting: file berubah, aplikasi
# tetap memakai nilai lama, dan tidak ada error apa pun yang muncul.

@pytest.fixture
def env_asli(tmp_path, monkeypatch):
    """Seperti env_tmp, tapi reload TIDAK dinon-aktifkan — reload itulah yang
    justru diuji di sini."""
    p = tmp_path / ".env"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_store, "ENV_PATH", p)
    return p


def test_file_menang_atas_env_var_untuk_key_yang_bisa_ditulis(env_asli, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "model-lama-dari-env")
    env_asli.write_text("GEMINI_MODEL=model-baru-dari-file\n", encoding="utf-8")

    env_store.reload()
    assert settings.GEMINI_MODEL == "model-baru-dari-file"


def test_infra_tidak_ikut_ditimpa_dari_file(env_asli, monkeypatch):
    """compose mengarahkan DATABASE_URL ke nama service; .env berisi localhost.
    Menimpanya dari file akan memutus koneksi database di dalam container."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@postgres:5432/db")
    env_asli.write_text(
        "DATABASE_URL=postgresql+psycopg://x@localhost:5432/db\n", encoding="utf-8")

    env_store.reload()
    assert "postgres:5432" in settings.DATABASE_URL
