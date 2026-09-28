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


@pytest.fixture(autouse=True)
def jangan_antre(monkeypatch):
    """Cegah test mengantre job ke worker SUNGGUHAN.

    Test di sini mem-POST /jobs ke Redis yang sama dengan yang dipakai worker
    produksi, jadi tanpa ini setiap kali `pytest` dijalankan worker benar-benar
    mengunduh video, memanggil Gemini, dan merender klip — membuang kuota, disk,
    dan waktu, sekaligus menaruh job sampah di halaman Proses.

    Yang diuji route ini memang cuma "row tertulis lalu enqueue dipanggil",
    bukan pipeline-nya. Jadi enqueue cukup dijadikan no-op.
    """
    from api import routes

    monkeypatch.setattr(routes, "enqueue", lambda job_id: None)


@pytest.fixture(autouse=True)
def bersihkan_job():
    """Hapus row yang dibuat test, supaya riwayat asli tidak tercemar."""
    from sqlalchemy import select

    from db.models import Job, session_scope

    with session_scope() as s:
        sebelum = {str(x) for x in s.scalars(select(Job.id)).all()}
    yield
    with session_scope() as s:
        for j in s.scalars(select(Job)).all():
            if str(j.id) not in sebelum:
                s.delete(j)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    with TestClient(app) as c:
        yield c


def test_url_bukan_youtube_ditolak(client):
    r = client.post("/jobs", json={"url": "https://evil.example/x", "target_clips": 3, "template_id": "full_screen"})
    assert r.status_code == 422


def test_url_kosong_ditolak(client):
    assert client.post("/jobs", json={"url": "", "target_clips": 3, "template_id": "full_screen"}).status_code == 422


def test_target_clips_di_luar_batas_ditolak(client):
    r = client.post(
        "/jobs",
        json={"url": "https://www.youtube.com/watch?v=abc", "target_clips": 999, "template_id": "full_screen"},
    )
    assert r.status_code == 422


def test_job_tidak_dikenal_balas_404(client):
    assert client.get("/jobs/tidak-ada").status_code == 404
    assert client.get("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_submit_menulis_row_dan_masuk_antrean(client):
    r = client.post(
        "/jobs",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "target_clips": 2, "template_id": "full_screen"},
    )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    detail = client.get(f"/jobs/{job_id}").json()
    assert detail["status"] == "queued"
    assert detail["target_clips"] == 2
    assert detail["clips"] == []

    assert any(j["id"] == job_id for j in client.get("/jobs").json())


def test_proses_ulang_memakai_job_dan_konfigurasi_yang_sama(client):
    from datetime import datetime, timedelta, timezone

    from db import jobs as db_jobs
    from db.models import Job, session_scope

    r = client.post("/jobs", json={
        "url": "https://youtu.be/abc", "target_clips": 4,
        "template_id": "pembicara_samping", "adjustments": {"caption_motion": "kinetic_words"},
    })
    job_id = r.json()["job_id"]
    with session_scope() as s:
        job = s.get(Job, job_id)
        job.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    sebelum = client.get(f"/jobs/{job_id}").json()
    db_jobs.fail(job_id, "gagal uji")

    ulang = client.post(f"/jobs/{job_id}/retry")
    assert ulang.status_code == 200
    sesudah = client.get(f"/jobs/{job_id}").json()
    assert sesudah["id"] == job_id
    for k in ("url", "target_clips", "template_id", "adjustments"):
        assert sesudah[k] == sebelum[k]
    assert sesudah["status"] == "queued"
    assert sesudah["progress"] == 0
    assert sesudah["error"] is None
    assert sesudah["created_at"] > sebelum["created_at"]


def test_job_aktif_tidak_bisa_dihapus_dan_tetap_tercatat(client):
    from db import jobs as db_jobs
    from db.models import Status

    r = client.post("/jobs", json={"url": "https://youtu.be/abc", "target_clips": 2, "template_id": "full_screen"})
    job_id = r.json()["job_id"]

    for status in (Status.QUEUED, Status.DOWNLOADING):
        db_jobs.update_status(job_id, status)
        hapus = client.delete(f"/jobs/{job_id}")
        assert hapus.status_code == 409
        assert "masih antre atau berjalan" in hapus.json()["detail"]
        assert client.get(f"/jobs/{job_id}").status_code == 200

    db_jobs.fail(job_id, "selesai gagal")
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_job_aktif_bisa_dibatalkan_dan_statusnya_tidak_ditiban(client):
    from db import jobs as db_jobs
    from db.models import Status

    job_id = client.post("/jobs", json={
        "url": "https://youtu.be/abc", "target_clips": 2,
        "template_id": "full_screen",
    }).json()["job_id"]
    db_jobs.update_status(job_id, Status.RENDERING, progress=70)

    response = client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    assert client.get(f"/jobs/{job_id}").json()["status"] == "cancelling"
    assert client.delete(f"/jobs/{job_id}").status_code == 409

    db_jobs.finish(job_id, [{"id": "c1"}])
    db_jobs.fail(job_id, "error balapan")
    assert client.get(f"/jobs/{job_id}").json()["status"] == "cancelling"
    db_jobs.mark_cancelled(job_id)
    assert client.get(f"/jobs/{job_id}").json()["status"] == "cancelled"
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 409


def test_job_antre_bisa_dibatalkan(client):
    job_id = client.post("/jobs", json={
        "url": "https://youtu.be/abc", "target_clips": 2,
        "template_id": "full_screen",
    }).json()["job_id"]
    response = client.post(f"/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_proses_ulang_upload_mempertahankan_source(client, tmp_path, monkeypatch):
    from db import jobs as db_jobs

    monkeypatch.setattr(settings, "WORK_DIR", tmp_path)
    ident = "5f2a9c1e-8b47-4d3a-9f61-2c7e0a1b8d43"
    r = client.post("/jobs", json={"url": f"unggah:{ident}", "target_clips": 2, "template_id": "full_screen"})
    job_id = r.json()["job_id"]
    source = tmp_path / job_id[:8] / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video-asli")
    db_jobs.fail(job_id, "worker mati")

    assert client.post(f"/jobs/{job_id}/retry").status_code == 200
    assert source.read_bytes() == b"video-asli"
    assert client.get(f"/jobs/{job_id}").json()["url"] == f"unggah:{ident}"


def test_proses_ulang_hanya_sekali_dan_hanya_job_gagal(client):
    from db import jobs as db_jobs

    r = client.post("/jobs", json={"url": "https://youtu.be/abc", "target_clips": 2, "template_id": "full_screen"})
    job_id = r.json()["job_id"]
    assert client.post(f"/jobs/{job_id}/retry").status_code == 409
    db_jobs.fail(job_id, "gagal uji")
    assert client.post(f"/jobs/{job_id}/retry").status_code == 200
    assert client.post(f"/jobs/{job_id}/retry").status_code == 409


def test_queue_gagal_mengembalikan_retry_ke_status_gagal(client, monkeypatch):
    from api import routes
    from db import jobs as db_jobs

    job = db_jobs.create("https://youtu.be/abc", 2, "full_screen", {})
    db_jobs.fail(job["id"], "gagal pertama")
    monkeypatch.setattr(routes, "enqueue", lambda _id: (_ for _ in ()).throw(RuntimeError("redis mati")))

    r = client.post(f"/jobs/{job['id']}/retry")
    assert r.status_code == 503
    sesudah = client.get(f"/jobs/{job['id']}").json()
    assert sesudah["status"] == "failed"
    assert "redis mati" in sesudah["error"]


def test_halaman_web_kebuka(client):
    assert client.get("/").status_code == 200
    assert client.get("/history").status_code == 200


# --- End-to-end penuh (PRD Bagian 10) ---

E2E_URL = os.getenv("TEST_YOUTUBE_URL", "")


@pytest.mark.integration
@pytest.mark.skipif(
    not (E2E_URL and settings.gemini_keys),
    reason="butuh TEST_YOUTUBE_URL + GEMINI_API_KEYS",
)
def test_end_to_end_sampai_done(client):
    """Jalankan `python main.py worker` di terminal lain sebelum test ini."""
    job_id = client.post("/jobs", json={"url": E2E_URL, "target_clips": 3, "template_id": "full_screen"}).json()["job_id"]

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
    nilai = settings.GEMINI_API_KEYS
    if nilai:
        assert nilai not in r.text, "GEMINI_API_KEYS terkirim utuh ke browser"


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


def test_process_mengabaikan_poll_lama_setelah_retry(client):
    html = client.get("/process").text
    assert "urutan !== urutanTick" in html
    assert "await tick();" in html


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
        "/jobs", json={"url": "https://youtu.be/abc", "target_clips": 2, "template_id": "full_screen"}
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


def test_worker_tidak_ribut_saat_row_selesai_sudah_dihapus(client):
    """Pembaruan terlambat setelah row selesai dihapus tidak boleh melempar.

    API kini menolak penghapusan job aktif karena eksekusi RQ tidak ikut
    berhenti. Perlindungan di lapisan DB tetap berguna untuk pembaruan worker
    yang datang sesaat setelah job gagal/done dihapus.
    """
    from db import jobs as db_jobs

    j = client.post(
        "/jobs", json={"url": "https://youtu.be/abc", "target_clips": 1, "template_id": "full_screen"}
    ).json()["job_id"]
    db_jobs.fail(j, "gagal sebelum dihapus")
    assert client.delete(f"/jobs/{j}").status_code == 204

    db_jobs.update_status(j, "rendering", progress=50)   # tidak boleh melempar
    db_jobs.fail(j, "error apa pun")                     # juga tidak
