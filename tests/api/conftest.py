"""Lisensi dianggap aktif untuk seluruh test API di folder ini.

Sejak gerbang lisensi ada, `POST /jobs` menolak dengan 403 kalau tidak ada
lisensi aktif. Tanpa fixture ini, setiap test yang membuat job akan gagal
karena alasan yang sama sekali tidak sedang diujinya — dan yang tampil bukan
"guard-nya rusak" melainkan belasan kegagalan yang menutupi kegagalan asli.

Gerbangnya sendiri diuji di dua tempat lain, dan sengaja tidak di sini:
tests/test_lisensi.py untuk logikanya, dan tests/api/test_penjaga.py untuk
penolakan di ENDPOINT — yang justru harus dicoba tanpa fixture ini.
"""
import pytest


@pytest.fixture(autouse=True)
def lisensi_aktif(request, monkeypatch):
    if "tanpa_lisensi" in request.keywords:
        return
    import license as lisensi

    monkeypatch.setattr(lisensi, "boleh_submit", lambda: (True, ""))
