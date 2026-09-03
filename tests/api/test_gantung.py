"""Job yang tertinggal saat worker mati tidak boleh menggantung selamanya.

SimpleWorker menjalankan job di dalam prosesnya sendiri, jadi container yang
di-restart di tengah render meninggalkan baris database berhenti di status
tengah. RQ membereskan registry-nya sendiri tapi tidak tahu-menahu soal tabel
ini — tanpa rekonsiliasi, job itu terlihat masih berjalan SELAMANYA di UI, dan
tidak ada satu pun pesan error yang muncul.

Butuh Postgres hidup: yang diuji adalah query terhadap status, bukan logika
murni yang bisa dipalsukan.
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


@pytest.fixture
def buat():
    """Bikin job dengan status tertentu, lalu bersihkan setelah test.

    Row dibuat langsung lewat model, bukan lewat db.jobs.create(), supaya
    status bisa diatur ke tahap tengah tanpa menjalankan pipeline.
    """
    from db.models import Job, session_scope

    dibuat = []

    def _buat(status: str) -> str:
        with session_scope() as s:
            j = Job(url="https://www.youtube.com/watch?v=uji", target_clips=3,
                    status=status)
            s.add(j)
            s.flush()
            dibuat.append(j.id)
            return str(j.id)

    yield _buat

    with session_scope() as s:
        for jid in dibuat:
            row = s.get(Job, jid)
            if row:
                s.delete(row)


def _status(job_id: str) -> str:
    from db import jobs

    return jobs.get(job_id)["status"]


# --- yang harus dibereskan ---

@pytest.mark.parametrize("tahap", [
    "downloading", "transcribing", "segmenting", "refining",
    "captioning", "cropping", "rendering", "metadata", "uploading",
])
def test_status_berjalan_ditandai_gagal(buat, tahap):
    from db import jobs

    jid = buat(tahap)
    jobs.bereskan_gantung()
    assert _status(jid) == "failed"


def test_pesan_menyebut_tahap_saat_berhenti(buat):
    """Tanpa menyebut tahapnya, orang tidak tahu apakah kegagalannya wajar
    (worker di-restart) atau ada yang benar-benar rusak."""
    from db import jobs

    jid = buat("rendering")
    jobs.bereskan_gantung()
    pesan = jobs.get(jid)["error"]
    assert "rendering" in pesan
    assert "Worker berhenti" in pesan


def test_mengembalikan_jumlah_yang_dibereskan(buat):
    from db import jobs

    jobs.bereskan_gantung()  # bersihkan sisa job lain lebih dulu
    buat("cropping")
    buat("uploading")
    assert jobs.bereskan_gantung() == 2


# --- yang TIDAK boleh disentuh ---

def test_queued_tidak_ikut_digagalkan(buat):
    """Job antre belum disentuh worker mana pun dan masih sah dikerjakan
    setelah worker menyala lagi. Menggagalkannya membuang pekerjaan yang
    sebenarnya baik-baik saja."""
    from db import jobs

    jid = buat("queued")
    jobs.bereskan_gantung()
    assert _status(jid) == "queued"


@pytest.mark.parametrize("akhir", ["done", "failed"])
def test_status_terminal_tidak_disentuh(buat, akhir):
    from db import jobs

    jid = buat(akhir)
    jobs.bereskan_gantung()
    assert _status(jid) == akhir


def test_done_tidak_kehilangan_klipnya(buat):
    """Regresi: menimpa error/status pada job selesai akan menghapus hasil
    yang sudah jadi dari halaman Hasil."""
    from db import jobs
    from db.models import Job, session_scope

    jid = buat("done")
    with session_scope() as s:
        s.get(Job, __import__("uuid").UUID(jid)).clips = [{"id": "c1", "url": "/x.mp4"}]

    jobs.bereskan_gantung()
    j = jobs.get(jid)
    assert j["status"] == "done"
    assert j["clips"] and j["clips"][0]["id"] == "c1"


def test_tanpa_job_gantung_tidak_melakukan_apa_apa(buat):
    from db import jobs

    jobs.bereskan_gantung()
    assert jobs.bereskan_gantung() == 0
