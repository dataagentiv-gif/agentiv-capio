"""Integration test endpoint. Butuh Postgres + Redis hidup (docker compose up -d).

Test end-to-end penuh butuh kredensial nyata dan video nyata, jadi dipisah di
belakang mark `integration` supaya `pytest` polos tetap cepat.
"""
import os
import time

import pytest

from config.settings import settings


def _infra_ready() -> bool:
    """Timeout-nya sengaja pendek. Dengan default, menjalankan pytest tanpa
    Docker hidup menggantung berbelas menit di TCP connect timeout sebelum
    akhirnya skip — dan itu terlihat seperti test yang hang, bukan infra mati.
    """
    try:
        from redis import Redis
        from sqlalchemy import create_engine, text

        probe = create_engine(
            settings.DATABASE_URL, connect_args={"connect_timeout": 2}
        )
        with probe.connect() as c:
            c.execute(text("select 1"))
        probe.dispose()

        Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
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
    not (E2E_URL and settings.GROQ_API_KEY),
    reason="butuh TEST_YOUTUBE_URL + GROQ_API_KEY",
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
        assert c["url"].startswith("/clips/")
        assert 0 <= c["score"] <= 100
        assert c["reason"].strip()
        assert settings.MIN_CLIP_SEC <= c["duration"] <= settings.MAX_CLIP_SEC


# --- pemutar klip ---

@pytest.mark.parametrize(
    "job_id,clip_id",
    [
        ("bukan-uuid", "c1"),
        ("../../etc", "c1"),
        ("00000000-0000-0000-0000-000000000000", "../secret"),
        ("00000000-0000-0000-0000-000000000000", "c1/../../x"),
        ("00000000-0000-0000-0000-000000000000", "cX"),
    ],
)
def test_id_tidak_valid_ditolak_404(client, job_id, clip_id):
    """Keduanya menyusun path file di disk — bentuknya wajib dikunci."""
    r = client.get(f"/clips/{job_id}/{clip_id}", follow_redirects=False)
    assert r.status_code in (404, 307), r.status_code


def test_klip_yang_tidak_ada_balas_404(client):
    r = client.get("/clips/00000000-0000-0000-0000-000000000000/c1")
    assert r.status_code == 404


# --- halaman dan endpoint setting ---

@pytest.mark.parametrize("path", ["/", "/process", "/results", "/settings"])
def test_semua_halaman_kebuka(client, path):
    assert client.get(path).status_code == 200


def test_history_lama_dialihkan_ke_hasil(client):
    """Tautan lama tidak boleh mati begitu halaman dipecah jadi empat."""
    r = client.get("/history", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/results"


def test_api_settings_tidak_membocorkan_rahasia(client):
    from config.settings import settings

    r = client.get("/api/settings")
    assert r.status_code == 200
    isi = r.text
    for key in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEYS"):
        nilai = getattr(settings, key, "")
        if nilai:
            assert nilai not in isi, f"{key} terkirim utuh ke browser"


def test_api_settings_menolak_key_di_luar_allowlist(client):
    r = client.post("/api/settings", json={"values": {"PATH": "/evil"}})
    assert r.status_code == 200
    assert r.json()["changed"] == []


def test_tes_provider_tidak_dikenal_dijawab_sopan(client):
    d = client.post("/api/settings/test/tidakada").json()
    assert d["ok"] is False and "tidak dikenal" in d["message"]


def test_api_status_merangkum_kesiapan(client):
    d = client.get("/api/status").json()
    assert set(d) >= {"asr", "llm", "storage", "ready", "default_clips"}
    assert isinstance(d["ready"], bool)


# --- autentikasi opsional ---
#
# Mati secara default (aman selama server hanya di loopback). Begitu diisi,
# SELURUH halaman dan endpoint harus tertutup — termasuk /settings yang bisa
# menimpa kredensial.

@pytest.fixture
def berkunci(monkeypatch):
    from api.routes import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "AUTH_TOKEN", "rahasia-panjang-sekali")
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/settings", "/jobs", "/api/settings"])
def test_tanpa_token_semua_ditolak_401(berkunci, path):
    r = berkunci.get(path)
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")


def test_token_benar_diterima(berkunci):
    assert berkunci.get("/", auth=("apa saja", "rahasia-panjang-sekali")).status_code == 200


def test_token_salah_ditolak(berkunci):
    assert berkunci.get("/", auth=("x", "rahasia-panjang-sekalii")).status_code == 401


def test_header_rusak_tidak_bikin_crash(berkunci):
    """Basic yang bukan base64 valid harus jadi 401, bukan 500."""
    r = berkunci.get("/", headers={"Authorization": "Basic bukan-base64!!"})
    assert r.status_code == 401


def test_default_tanpa_token_tetap_terbuka(client):
    assert settings.AUTH_TOKEN == ""
    assert client.get("/").status_code == 200


# --- penghapusan ---
#
# Yang diuji bukan cuma barisnya hilang dari layar, tapi berkasnya benar-benar
# lenyap dari disk. Kalau tidak, tombolnya justru menipu: daftar terlihat
# bersih sementara disk tetap penuh.

@pytest.fixture
def job_berklip(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CLIPS_DIR", tmp_path / "clips")
    import storage
    from db import jobs as db_jobs

    j = client.post(
        "/jobs", json={"url": "https://youtu.be/abc", "target_clips": 2}
    ).json()["job_id"]

    src = tmp_path / "x.mp4"
    src.write_bytes(b"video" * 100)
    klip = []
    for cid in ("c1", "c2"):
        url = storage.save_clip(j, cid, src)
        klip.append({"id": cid, "url": url, "duration": 40.0, "score": 90,
                     "hook": "h", "reason": "r", "title": "t",
                     "caption": "", "hashtags": []})
    db_jobs.finish(j, klip)
    return j, tmp_path / "clips" / j


def test_hapus_klip_membuang_berkas_dan_entrinya(client, job_berklip):
    job_id, folder = job_berklip
    assert client.delete(f"/jobs/{job_id}/clips/c1").status_code == 204

    assert not (folder / "c1.mp4").exists(), "berkas masih ada di disk"
    assert (folder / "c2.mp4").exists(), "klip lain ikut terhapus"
    sisa = client.get(f"/jobs/{job_id}").json()["clips"]
    assert [c["id"] for c in sisa] == ["c2"]


def test_hapus_klip_terakhir_membuang_folder_kosong(client, job_berklip):
    job_id, folder = job_berklip
    client.delete(f"/jobs/{job_id}/clips/c1")
    client.delete(f"/jobs/{job_id}/clips/c2")
    assert not folder.exists(), "folder kosong ditinggal menumpuk"


def test_hapus_job_membuang_row_dan_semua_berkas(client, job_berklip):
    job_id, folder = job_berklip
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert not folder.exists()
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_hapus_job_yang_sudah_hilang_balas_404(client):
    assert client.delete("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_hapus_klip_yang_tidak_ada_balas_404(client, job_berklip):
    job_id, _ = job_berklip
    assert client.delete(f"/jobs/{job_id}/clips/c9").status_code == 404


@pytest.mark.parametrize("job_id,clip_id", [
    ("bukan-uuid", "c1"),
    ("00000000-0000-0000-0000-000000000000", "../../etc/passwd"),
    ("00000000-0000-0000-0000-000000000000", "cX"),
])
def test_id_rusak_ditolak_bukan_dieksekusi(client, job_id, clip_id):
    """Keduanya menyusun path di disk — bentuknya wajib dikunci."""
    r = client.delete(f"/jobs/{job_id}/clips/{clip_id}", follow_redirects=False)
    assert r.status_code in (404, 307)


def test_worker_tidak_ribut_saat_row_sudah_dihapus(client):
    """Menghapus job yang sedang berjalan adalah cara satu-satunya membersihkan
    job yang tersangkut. Worker yang masih menulis ke row itu harus berhenti
    diam-diam, bukan melempar KeyError."""
    from db import jobs as db_jobs

    j = client.post(
        "/jobs", json={"url": "https://youtu.be/abc", "target_clips": 1}
    ).json()["job_id"]
    assert client.delete(f"/jobs/{j}").status_code == 204

    db_jobs.update_status(j, "rendering", progress=50)   # tidak boleh melempar
    db_jobs.fail(j, "error apa pun")                     # juga tidak
