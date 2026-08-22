"""Integration test endpoint. Butuh Postgres + Redis hidup (docker compose up -d).

Test end-to-end penuh butuh kredensial nyata dan video nyata, jadi dipisah di
belakang mark `integration` supaya `pytest` polos tetap cepat.
"""
import os
import time

import pytest

from config.settings import settings


def _infra_ready() -> bool:
    try:
        from sqlalchemy import text

        from db.models import engine

        with engine.connect() as c:
            c.execute(text("select 1"))
        from jobqueue.client import connection

        connection().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _infra_ready(), reason="Postgres/Redis tidak jalan — `docker compose up -d`"
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    with TestClient(app) as c:
        yield c


def test_url_bukan_youtube_ditolak(client):
    r = client.post("/jobs", json={"url": "https://evil.example/x", "target_clips": 3})
    assert r.status_code == 422


def test_url_kosong_ditolak(client):
    assert client.post("/jobs", json={"url": "", "target_clips": 3}).status_code == 422


def test_target_clips_di_luar_batas_ditolak(client):
    r = client.post(
        "/jobs",
        json={"url": "https://www.youtube.com/watch?v=abc", "target_clips": 999},
    )
    assert r.status_code == 422


def test_job_tidak_dikenal_balas_404(client):
    assert client.get("/jobs/tidak-ada").status_code == 404
    assert client.get("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_submit_menulis_row_dan_masuk_antrean(client):
    r = client.post(
        "/jobs",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "target_clips": 2},
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    detail = client.get(f"/jobs/{job_id}").json()
    assert detail["status"] == "queued"
    assert detail["target_clips"] == 2
    assert detail["clips"] == []

    assert any(j["id"] == job_id for j in client.get("/jobs").json())


def test_halaman_web_kebuka(client):
    assert client.get("/").status_code == 200
    assert client.get("/history").status_code == 200


# --- End-to-end penuh (PRD Bagian 10) ---

E2E_URL = os.getenv("TEST_YOUTUBE_URL", "")


@pytest.mark.integration
@pytest.mark.skipif(
    not (E2E_URL and settings.GROQ_API_KEY and settings.OPENROUTER_API_KEY),
    reason="butuh TEST_YOUTUBE_URL + GROQ_API_KEY + OPENROUTER_API_KEY",
)
def test_end_to_end_sampai_done(client):
    """Jalankan `python main.py worker` di terminal lain sebelum test ini."""
    job_id = client.post("/jobs", json={"url": E2E_URL, "target_clips": 3}).json()["job_id"]

    deadline = time.time() + settings.JOB_TIMEOUT_SEC + 120
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(10)
    else:
        pytest.fail("job tidak selesai sebelum timeout")

    assert job["status"] == "done", job["error"]
    assert job["clips"], "status done tapi tidak ada klip"
    for c in job["clips"]:
        # Kriteria "berhasil" nomor 2 di PRD Bagian 10: score dan reason wajib
        # sampai ke hasil akhir, supaya seleksi LLM bisa dinilai manusia.
        assert c["url"].startswith("http")
        assert 0 <= c["score"] <= 100
        assert c["reason"].strip()
        assert settings.MIN_CLIP_SEC <= c["duration"] <= settings.MAX_CLIP_SEC
