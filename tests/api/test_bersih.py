"""Auto clear terhadap database sungguhan: yang lewat umur dan sudah selesai
saja yang terpilih.

Satu jaminan yang tidak bisa diuji tanpa Postgres, dan justru yang paling mahal
kalau jebol: job yang antre atau sedang berjalan TIDAK PERNAH ikut terhapus,
berapa pun umurnya.
"""
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import settings
from tests.api.test_penjaga import _db_ready

pytestmark = pytest.mark.skipif(
    not _db_ready(), reason="Postgres tidak jalan — `docker compose up -d`"
)

LAMA = datetime.now(timezone.utc) - timedelta(days=90)


@pytest.fixture
def buat():
    from db.models import Job, init, session_scope

    init()
    dibuat = []

    def _buat(status, clips=None, created_at=LAMA):
        with session_scope() as s:
            j = Job(url="https://youtu.be/x", target_clips=1, status=status,
                    clips=clips, created_at=created_at)
            s.add(j)
            s.flush()
            dibuat.append(j.id)
            return str(j.id)

    yield _buat
    with session_scope() as s:
        for jid in dibuat:
            if (j := s.get(Job, jid)) is not None:
                s.delete(j)


def test_hanya_job_selesai_yang_lewat_umur(buat):
    from db import jobs

    batas = datetime.now(timezone.utc) - timedelta(days=30)
    gagal = buat("failed")
    selesai = buat("done", clips=[{"id": "c1"}])
    antre = buat("queued")
    jalan = buat("rendering")
    muda = buat("done", created_at=datetime.now(timezone.utc))

    terpilih = {j["id"] for j in jobs.list_selesai_sebelum(batas)}
    assert {gagal, selesai} <= terpilih
    assert not {antre, jalan, muda} & terpilih


def test_sapu_hasil_mengosongkan_klip_dan_mempertahankan_baris(buat, monkeypatch, tmp_path):
    from api import bersih
    from db import jobs

    monkeypatch.setattr(settings, "CLIPS_DIR", tmp_path)
    monkeypatch.setattr(settings, "AUTO_CLEAR_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_CLEAR_DAYS", 30)
    monkeypatch.setattr(settings, "AUTO_CLEAR_TARGET", "hasil")

    jid = buat("done", clips=[{"id": "c1"}])
    folder = tmp_path / jid
    folder.mkdir()
    (folder / "c1.mp4").write_bytes(b"x")
    jalan = buat("rendering", clips=[{"id": "c1"}])

    bersih.sapu()
    assert jobs.get(jid)["clips"] == []
    assert not folder.exists()
    assert jobs.get(jalan)["clips"] == [{"id": "c1"}]
