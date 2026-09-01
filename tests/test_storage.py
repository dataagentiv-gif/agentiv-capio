"""Penyimpanan klip lokal.

Penanganan Range diuji ketat karena kalau salah, gejalanya bukan error:
videonya tetap terbuka, cuma tidak bisa digeser posisinya — dan itu baru
ketahuan saat seseorang mencoba menonton.
"""
import pytest

import storage
from config.settings import settings
from storage import client_local


@pytest.fixture
def lokal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local")
    monkeypatch.setattr(settings, "CLIPS_DIR", tmp_path / "clips")
    return tmp_path


@pytest.fixture
def klip(lokal):
    src = lokal / "c1.mp4"
    src.write_bytes(bytes(range(256)) * 40)  # 10.240 byte
    storage.save_clip("job-1", "c1", src)
    return 10240


def _kumpul(hasil):
    potongan, panjang, cr = hasil
    return b"".join(potongan), panjang, cr


# --- simpan ---

def test_save_mengembalikan_url_lokal(lokal):
    src = lokal / "x.mp4"
    src.write_bytes(b"halo")
    assert storage.save_clip("job-1", "c1", src) == "/clips/job-1/c1"


def test_file_benar_benar_mendarat_di_folder(lokal):
    """Inti dari mode lokal: klip jadi file biasa yang bisa dibuka manusia."""
    src = lokal / "x.mp4"
    src.write_bytes(b"halo")
    storage.save_clip("job-1", "c1", src)
    assert (lokal / "clips" / "job-1" / "c1.mp4").read_bytes() == b"halo"


def test_folder_dibuat_sendiri(lokal):
    assert not (lokal / "clips").exists()
    storage.check_config()
    assert (lokal / "clips").is_dir()


# --- baca ---

def test_tanpa_range_mengembalikan_seluruh_file(klip):
    isi, panjang, cr = _kumpul(storage.open_clip("job-1", "c1"))
    assert panjang == klip == len(isi)
    assert cr is None  # tanpa Range berarti balasan 200, bukan 206


def test_range_awal_dipotong_tepat(klip):
    isi, panjang, cr = _kumpul(storage.open_clip("job-1", "c1", "bytes=0-1023"))
    assert panjang == 1024 == len(isi)
    assert cr == f"bytes 0-1023/{klip}"


def test_range_tengah(klip):
    isi, panjang, cr = _kumpul(storage.open_clip("job-1", "c1", "bytes=100-199"))
    assert panjang == 100 == len(isi)
    assert cr == f"bytes 100-199/{klip}"


def test_range_terbuka_sampai_akhir(klip):
    """`bytes=9000-` — bentuk yang dipakai pemutar video saat menggeser maju."""
    isi, panjang, cr = _kumpul(storage.open_clip("job-1", "c1", "bytes=9000-"))
    assert panjang == klip - 9000 == len(isi)


def test_range_suffix_mengambil_ekor(klip):
    """`bytes=-500` artinya 500 byte TERAKHIR, bukan 500 pertama.
    Salah menafsirkannya membuat pemutar gagal membaca moov atom di ekor file."""
    isi, panjang, cr = _kumpul(storage.open_clip("job-1", "c1", "bytes=-500"))
    assert panjang == 500 == len(isi)
    assert cr == f"bytes {klip - 500}-{klip - 1}/{klip}"


def test_range_melebihi_ukuran_di_clamp(klip):
    _, panjang, _ = _kumpul(storage.open_clip("job-1", "c1", "bytes=0-999999"))
    assert panjang == klip


def test_klip_tidak_ada_melempar(lokal):
    with pytest.raises(FileNotFoundError):
        storage.open_clip("job-x", "c9")


# --- pemilihan provider ---

def test_provider_tidak_dikenal_ditolak(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "s3")
    with pytest.raises(RuntimeError, match="tidak dikenal"):
        storage.check_config()


def test_default_adalah_lokal():
    """Supaya project ini bisa dicoba tanpa akun Cloudflare sama sekali."""
    from config.settings import Settings

    assert Settings.model_fields["STORAGE_PROVIDER"].default == "local"


def test_hapus_job_membuang_seluruh_foldernya(klip, lokal):
    client_local.delete_job("job-1")
    assert not (lokal / "clips" / "job-1").exists()
