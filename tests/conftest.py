"""Test tidak boleh membaca .env milik mesin yang menjalankannya.

Sejak lifespan() di api/routes.py memanggil env_store.reload(), setiap
`TestClient(app)` membaca ulang .env SUNGGUHAN lalu menimpa SEMUA field
settings — termasuk nilai yang baru saja dipasang fixture lewat monkeypatch.
Tidak ada error: AUTH_TOKEN palsu hilang sehingga test auth mendapat 200, dan
WORK_DIR kembali ke folder kerja asli sehingga test unggah menulis ke sana.
Test tetap berjalan, hanya saja menguji konfigurasi mesin, bukan kodenya.

Test yang memang menguji reload() memakai fixture `env_asli`, yang sudah
mengarahkan ENV_PATH ke berkas sementara — hanya itu yang dikecualikan.
"""
import pytest


@pytest.fixture(autouse=True)
def tanpa_env_sungguhan(request, monkeypatch):
    if "env_asli" in request.fixturenames:
        return
    from config import env_store

    monkeypatch.setattr(env_store, "reload", lambda: None)
