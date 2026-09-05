"""Unggah berkas sebagai sumber video, selain link YouTube.

Sampai sekarang satu-satunya sumber adalah link YouTube, dan `JobCreate` bahkan
MENOLAK apa pun selain host YouTube. Itu memblokir pemakaian yang justru jadi
target: operator jasa clipper umumnya punya rekamannya sendiri.

Yang dijaga di sini dua hal, dan keduanya batas kepercayaan:

1. Nilai `unggah:<id>` ikut menyusun path di disk, jadi bentuknya harus dikunci
   ke UUID — bukan sekadar "bukan URL YouTube".
2. Nilai itu TIDAK BOLEH sampai ke yt-dlp. Stage download harus bercabang lebih
   dulu, kalau tidak penanda internal berubah jadi argumen subprocess.
"""
import io

import pytest

import unggah


@pytest.fixture(autouse=True)
def kerja(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "WORK_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    with TestClient(app) as c:
        yield c


# --- batas kepercayaan ---

@pytest.mark.parametrize("nilai", [
    "unggah:../../etc/passwd",
    "unggah:bukan-uuid",
    "unggah:",
    "unggah:5f2a9c1e-8b47-4d3a-9f61",          # terlalu pendek
    "unggah:5f2a9c1e_8b47_4d3a_9f61_2c7e0a1b8d43",  # pemisah salah
])
def test_penanda_ngawur_tidak_dikenali_sebagai_unggahan(nilai):
    assert unggah.sumber(nilai) is None


def test_penanda_sah_dikenali():
    ident = "5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    assert unggah.sumber(f"unggah:{ident}") == ident


def test_link_youtube_bukan_unggahan():
    assert unggah.sumber("https://youtu.be/abc") is None


def test_schema_menolak_penanda_unggahan_yang_ngawur():
    """Kalau ini lolos, nilai ngawur tersimpan di kolom url dan baru meledak di
    worker — belasan menit kemudian, di proses yang berbeda."""
    from api.schemas import JobCreate

    with pytest.raises(ValueError):
        JobCreate(url="unggah:../../etc/passwd")


def test_schema_menerima_penanda_unggahan_yang_sah():
    from api.schemas import JobCreate

    nilai = "unggah:5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    assert JobCreate(url=nilai).url == nilai


# --- endpoint unggah ---

def test_berkas_tersimpan_dan_mengembalikan_penanda(client):
    r = client.post("/api/unggah",
                    files={"berkas": ("podcast.mp4", io.BytesIO(b"x" * 2048), "video/mp4")})
    assert r.status_code == 201, r.text
    d = r.json()
    ident = unggah.sumber(d["sumber"])
    assert ident is not None
    assert unggah.berkas(ident).read_bytes() == b"x" * 2048
    assert d["bytes"] == 2048


def test_nama_asli_disimpan_untuk_dipakai_jadi_judul(client):
    """Tanpa ini judulnya kosong, dan stage metadata kehilangan satu-satunya
    petunjuk soal isi video selain transkripnya sendiri."""
    r = client.post("/api/unggah",
                    files={"berkas": ("Wawancara Bu Ani.mp4", io.BytesIO(b"x"), "video/mp4")})
    assert unggah.nama_asli(unggah.sumber(r.json()["sumber"])) == "Wawancara Bu Ani.mp4"


def test_nama_berkas_tidak_bisa_membawa_path(client):
    """Nama dikirim pengguna. Menyusun path dari nama itu adalah cara paling
    umum untuk menulis di luar folder yang dimaksud."""
    r = client.post("/api/unggah",
                    files={"berkas": ("../../jahat.mp4", io.BytesIO(b"x"), "video/mp4")})
    assert r.status_code == 201
    assert unggah.nama_asli(unggah.sumber(r.json()["sumber"])) == "jahat.mp4"


def test_format_tidak_didukung_ditolak(client):
    r = client.post("/api/unggah",
                    files={"berkas": ("naskah.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert r.status_code == 400
    assert "MP4" in r.text


def test_berkas_kosong_ditolak_dan_tidak_meninggalkan_sisa(client, kerja):
    r = client.post("/api/unggah",
                    files={"berkas": ("kosong.mp4", io.BytesIO(b""), "video/mp4")})
    assert r.status_code == 400
    assert list(unggah.folder().glob("*")) == []


# --- stage download bercabang sebelum yt-dlp ---

def test_unggahan_tidak_pernah_sampai_ke_ytdlp(monkeypatch, tmp_path):
    """Kalau bercabangnya kelewat, penanda internal berubah jadi argumen
    subprocess yt-dlp — dan yt-dlp akan mencoba mengambilnya sebagai URL."""
    from pipeline.stages import download

    ident = "5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    unggah.berkas(ident).write_bytes(b"video palsu")
    unggah.catat_nama(ident, "rapat.mp4")

    monkeypatch.setattr(download, "_ytdlp",
                        lambda *a, **k: pytest.fail("yt-dlp tidak boleh dipanggil"))
    wd = tmp_path / "job"
    wd.mkdir()
    download._pindahkan(ident, wd / "source.mp4")

    assert (wd / "source.mp4").read_bytes() == b"video palsu"


def test_berkas_dipindah_bukan_disalin(tmp_path):
    """Video sumber bisa berukuran giga. Disalin, dua salinan hidup berdampingan
    sepanjang job di volume yang sama."""
    from pipeline.stages import download

    ident = "5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    unggah.berkas(ident).write_bytes(b"x" * 100)
    wd = tmp_path / "job"
    wd.mkdir()
    download._pindahkan(ident, wd / "source.mp4")

    assert not unggah.berkas(ident).exists()
    assert not (unggah.folder() / f"{ident}.json").exists()


def test_pindah_ulang_tidak_menggagalkan_percobaan_kedua(tmp_path):
    """Stage bisa diulang. Berkas yang sudah pindah bukan alasan gagal."""
    from pipeline.stages import download

    ident = "5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    wd = tmp_path / "job"
    wd.mkdir()
    (wd / "source.mp4").write_bytes(b"sudah pindah")
    download._pindahkan(ident, wd / "source.mp4")   # tidak boleh melempar
    assert (wd / "source.mp4").read_bytes() == b"sudah pindah"


def test_berkas_unggahan_hilang_memberi_pesan_yang_menyebut_tindakan(tmp_path):
    from pipeline.stages import download

    wd = tmp_path / "job"
    wd.mkdir()
    with pytest.raises(RuntimeError, match="unggah ulang"):
        download._pindahkan("5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43", wd / "source.mp4")
