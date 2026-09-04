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

def test_tanpa_key_transkrip_ditolak(client, monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "elevenlabs")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", "")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")

    r = client.post("/jobs", json={"url": URL, "target_clips": 2})
    assert r.status_code == 400
    assert "elevenlabs" in r.text


def test_tanpa_key_llm_ditolak(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEYS", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    r = client.post("/jobs", json={"url": URL, "target_clips": 2})
    assert r.status_code == 400
    assert "openrouter" in r.text


def test_pesan_menyebut_akibatnya_bukan_cuma_larangan(client, monkeypatch):
    """"Key belum diisi" saja tidak memberitahu kenapa itu penting SEKARANG."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEYS", "")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    teks = client.post("/jobs", json={"url": URL}).text.lower()
    assert "setting" in teks
    assert "diunduh" in teks


def test_konfigurasi_lengkap_tetap_lolos(client):
    """Penjaganya jangan sampai menghalangi jalur normal."""
    r = client.post("/jobs", json={"url": URL, "target_clips": 2})
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
    assert client.post("/jobs", json=payload).status_code == 422, kenapa


def test_gaya_hanya_menerima_kunci_yang_dikenal(client):
    """Batas kepercayaan: isi kolom ini masuk ke generator .ass dan tersimpan
    di database."""
    r = client.post("/jobs", json={
        "url": URL, "target_clips": 2,
        "gaya": {"font": "Anton", "__proto__": "x", "perintah": "rm -rf /"},
    })
    assert r.status_code in (200, 201)
    gaya = client.get(f"/jobs/{r.json()['job_id']}").json()["gaya"]
    assert gaya == {"font": "Anton"}


def test_gaya_kosong_tidak_menimpa_default(client):
    """Kosong berarti 'ikut default', bukan 'kosongkan' — nilai kosong yang
    tersimpan akan menimpa setelan dan menghasilkan caption tanpa gaya."""
    r = client.post("/jobs", json={
        "url": URL, "target_clips": 2,
        "gaya": {"font": "", "ukuran": 0, "aktif": None},
    })
    assert client.get(f"/jobs/{r.json()['job_id']}").json()["gaya"] == {}
