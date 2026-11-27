"""Penjaga di sisi server: job yang sejak awal pasti gagal tidak boleh dibuat.

Halaman Submit sudah mematikan tombolnya, tapi itu penjaga di browser saja —
permintaan langsung ke API melewatinya begitu saja. Yang dijaga di sini adalah
biayanya: tanpa key, job tetap mengunduh videonya lebih dulu (beberapa menit
sampai satu jam) baru berhenti di stage transkrip.
"""
import pytest

from config.settings import settings


def _db_ready() -> bool:
    try:
        from sqlalchemy import create_engine, text

        probe = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 2})
        with probe.connect() as c:
            c.execute(text("select 1"))
        probe.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _db_ready(), reason="Postgres tidak jalan — `docker compose up -d`"
)

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def jangan_antre(monkeypatch):
    from api import routes

    monkeypatch.setattr(routes, "enqueue", lambda job_id: None)


@pytest.fixture(autouse=True)
def bersihkan():
    from sqlalchemy import select

    from db.models import Job, session_scope

    with session_scope() as s:
        sebelum = {str(x) for x in s.scalars(select(Job.id)).all()}
    yield
    with session_scope() as s:
        for j in s.scalars(select(Job)).all():
            if str(j.id) not in sebelum:
                s.delete(j)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    with TestClient(app) as c:
        yield c


# --- konfigurasi bolong ---

def test_tanpa_key_gemini_ditolak(client, monkeypatch):
    """Transkrip dan LLM sama-sama lewat pool "gemini" sekarang, jadi satu
    key kosong memblokir keduanya sekaligus."""
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")

    r = client.post("/jobs", json={"url": URL, "target_clips": 2, "template_id": "full_screen"})
    assert r.status_code == 400
    assert "gemini" in r.text


def test_retry_tetap_memeriksa_api_key(client, monkeypatch):
    from db import jobs

    job = jobs.create(URL, 2, "full_screen", {})
    jobs.fail(job["id"], "gagal")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    r = client.post(f"/jobs/{job['id']}/retry")
    assert r.status_code == 400
    assert jobs.get(job["id"])["status"] == "failed"


def test_pesan_menyebut_akibatnya_bukan_cuma_larangan(client, monkeypatch):
    """"Key belum diisi" saja tidak memberitahu kenapa itu penting SEKARANG."""
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")

    teks = client.post("/jobs", json={"url": URL, "template_id": "full_screen"}).text.lower()
    assert "setting" in teks
    assert "diunduh" in teks


def test_konfigurasi_lengkap_tetap_lolos(client):
    """Penjaganya jangan sampai menghalangi jalur normal."""
    r = client.post("/jobs", json={"url": URL, "target_clips": 2, "template_id": "full_screen"})
    assert r.status_code in (200, 201), r.text


# --- parameter kosong / di luar batas ---

@pytest.mark.parametrize("payload,kenapa", [
    ({}, "url wajib"),
    ({"url": ""}, "url kosong"),
    ({"url": "   "}, "url cuma spasi"),
    ({"url": "youtube.com/watch?v=x"}, "tanpa https"),
    ({"url": "https://vimeo.com/123"}, "bukan youtube"),
    ({"url": URL, "target_clips": 0}, "nol klip"),
    ({"url": URL, "target_clips": 21}, "di atas batas"),
    ({"url": URL, "target_clips": -3}, "negatif"),
])
def test_parameter_tidak_sah_ditolak(client, payload, kenapa):
    assert client.post("/jobs", json={"template_id": "full_screen", **payload}).status_code == 422, kenapa


def test_adjustment_asing_ditolak(client):
    """Batas kepercayaan: isi kolom ini masuk ke generator .ass dan tersimpan
    di database."""
    r = client.post("/jobs", json={
        "url": URL, "target_clips": 2,
        "template_id": "full_screen", "adjustments": {"font": "Anton", "__proto__": "x"},
    })
    assert r.status_code == 422


def test_adjustment_kosong_memakai_default_tersimpan(client):
    """Kosong berarti 'ikut default', bukan 'kosongkan' — nilai kosong yang
    tersimpan akan menimpa setelan dan menghasilkan caption tanpa gaya."""
    r = client.post("/jobs", json={
        "url": URL, "target_clips": 2,
        "template_id": "full_screen", "adjustments": {},
    })
    from pipeline.templates import resolve
    assert client.get(f"/jobs/{r.json()['job_id']}").json()["adjustments"] == resolve("full_screen", {})
