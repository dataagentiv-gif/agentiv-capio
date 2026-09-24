"""Thumbnail klip: dibuat sekali, dipakai ulang, ikut terhapus.

Halaman Hasil memuat puluhan klip sekaligus. Kalau posternya dibangkitkan ulang
tiap kali halaman dibuka, itu puluhan proses ffmpeg untuk gambar yang isinya
tidak pernah berubah — dan gejalanya bukan error, melainkan halaman yang berat
tanpa sebab yang kelihatan.
"""
import shutil

import pytest

from config.settings import settings

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg tidak ada di PATH"
)

JOB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    client = TestClient(app)
    yield client
    client.close()


@pytest.fixture
def klip(tmp_path, monkeypatch):
    """Satu klip sungguhan di CLIPS_DIR sementara."""
    import storage
    from tests.fixtures.make_fixture import build

    monkeypatch.setattr(settings, "CLIPS_DIR", tmp_path)
    tujuan = tmp_path / JOB
    tujuan.mkdir(parents=True)
    shutil.copy(build(), tujuan / "c1.mp4")
    return storage


# --- batas kepercayaan ---

@pytest.mark.parametrize("job_id,clip_id", [
    ("../../etc", "c1"),
    (JOB, "../../../etc/passwd"),
    (JOB, "c1.mp4"),
    ("bukan-uuid", "c1"),
    (JOB, "c9999"),
])
def test_id_ngawur_ditolak(client, job_id, clip_id):
    """Dua nilai ini menyusun path di disk. Penjaganya harus sama persis dengan
    milik play_clip — penjaga versi kedua yang lambat laun berbeda adalah cara
    paling sunyi untuk membocorkannya."""
    r = client.get(f"/clips/{job_id}/{clip_id}/poster.jpg")
    assert r.status_code == 404


def test_klip_tidak_ada_bukan_error_server(client):
    assert client.get(f"/clips/{JOB}/c1/poster.jpg").status_code == 404


# --- dibuat sekali, dipakai ulang ---

def test_poster_dibuat_dari_klip(client, klip):
    r = client.get(f"/clips/{JOB}/c1/poster.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    # JPEG selalu diawali FF D8 FF. Memeriksa panjangnya saja tidak membedakan
    # gambar sungguhan dari berkas nol byte yang ditulis ffmpeg saat gagal.
    assert r.content[:3] == b"\xff\xd8\xff"
    assert klip.poster_path(JOB, "c1").is_file()


def test_permintaan_kedua_tidak_menjalankan_ffmpeg_lagi(client, klip, monkeypatch):
    """Inilah seluruh alasan posternya disimpan. Kalau ffmpeg tetap jalan tiap
    permintaan, halaman dengan 80 klip menjalankannya 80 kali per muat."""
    client.get(f"/clips/{JOB}/c1/poster.jpg")

    from api import routes

    def jangan(*a, **k):
        raise AssertionError("ffmpeg dipanggil ulang padahal poster sudah ada")

    monkeypatch.setattr(routes.subprocess, "run", jangan)
    assert client.get(f"/clips/{JOB}/c1/poster.jpg").status_code == 200


def test_poster_boleh_di_cache_lama(client, klip):
    """Isinya tidak akan pernah berubah untuk id yang sama — id klip tidak
    pernah dipakai ulang di dalam satu job."""
    r = client.get(f"/clips/{JOB}/c1/poster.jpg")
    assert "max-age" in r.headers.get("cache-control", "")


# --- ikut terhapus ---

def test_poster_ikut_terhapus_bersama_klipnya(client, klip):
    """Ditinggal, ia jadi berkas yatim yang tidak dibersihkan siapa pun — dan
    kalau suatu saat ada klip lain memakai id yang sama, yang tampil justru
    gambar milik klip yang sudah dihapus."""
    client.get(f"/clips/{JOB}/c1/poster.jpg")
    poster = klip.poster_path(JOB, "c1")
    assert poster.is_file()

    klip.delete_clip(JOB, "c1")
    assert not poster.exists()
    assert not klip.clip_path(JOB, "c1").exists()
