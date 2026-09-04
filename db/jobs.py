"""CRUD tabel jobs. Satu fungsi = satu operasi, tanpa logic pipeline."""
import uuid

from sqlalchemy import select

from db.models import Job, Status, session_scope
from utils.logging import get

log = get(__name__)


def create(url: str, target_clips: int, layout: str = "penuh") -> dict:
    with session_scope() as s:
        job = Job(url=url, target_clips=target_clips, layout=layout,
                  status=Status.QUEUED)
        s.add(job)
        s.flush()
        return job.as_dict()


def get(job_id: str | uuid.UUID) -> dict | None:
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        # job_id datang dari path URL. Bentuk yang bukan UUID artinya tidak ada,
        # bukan error server.
        return None
    with session_scope() as s:
        job = s.get(Job, key)
        return job.as_dict() if job else None


def list_all(limit: int = 100) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(
            select(Job).order_by(Job.created_at.desc()).limit(limit)
        ).all()
        return [r.as_dict() for r in rows]


def _update(job_id: str | uuid.UUID, **fields) -> None:
    """Row yang hilang di tengah jalan bukan error.

    Satu-satunya cara sebuah row lenyap saat worker masih mengerjakannya adalah
    pengguna menghapusnya lewat UI, dan itu berarti "sudah tidak dipedulikan".
    Kalau di sini melempar, worker justru gagal saat mencoba menulis status
    gagal — dan yang muncul di log adalah KeyError yang membingungkan, bukan
    penghapusan yang memang disengaja.
    """
    with session_scope() as s:
        job = s.get(Job, uuid.UUID(str(job_id)))
        if job is None:
            log.info("job %s sudah dihapus — pembaruan status dilewati", job_id)
            return
        for k, v in fields.items():
            setattr(job, k, v)


def update_status(job_id, status: str, progress: int | None = None) -> None:
    fields = {"status": status}
    if progress is not None:
        fields["progress"] = progress
    _update(job_id, **fields)


def finish(job_id, clips: list[dict]) -> None:
    _update(job_id, status=Status.DONE, progress=100, clips=clips, error=None)


def fail(job_id, error: str) -> None:
    # Pesan error dipotong: traceback ffmpeg/yt-dlp bisa puluhan KB dan yang
    # berguna di UI selalu ada di bagian akhir (baris error sebenarnya).
    _update(job_id, status=Status.FAILED, error=error[-2000:])


def bereskan_gantung() -> int:
    """Tandai job yang tertinggal di status berjalan sebagai gagal.

    SimpleWorker menjalankan job DI DALAM prosesnya sendiri, jadi kalau
    prosesnya mati di tengah jalan — container di-restart, mesin dimatikan,
    OOM — baris database berhenti di status tengah dan tidak pernah berubah
    lagi. RQ membereskan registry-nya sendiri tapi tidak tahu-menahu soal
    tabel ini, jadi job itu terlihat masih berjalan SELAMANYA di UI.

    Dipanggil saat worker start: satu-satunya saat kita tahu pasti tidak ada
    job yang sedang dikerjakan.

    ponytail: benar selama worker cuma satu. Dengan dua worker, yang baru
    menyala akan menggagalkan job milik worker lain yang masih sehat —
    perbaikannya menyimpan identitas worker di baris job dan hanya
    membereskan milik sendiri.
    """
    with session_scope() as s:
        rows = s.scalars(select(Job).where(Job.status.in_(Status.BERJALAN))).all()
        for job in rows:
            tahap = job.status
            log.warning("job %s tertinggal di status '%s' — ditandai gagal",
                        job.id, tahap)
            job.status = Status.FAILED
            job.error = (
                f"Worker berhenti saat job masih di tahap '{tahap}'. "
                "Job tidak dilanjutkan otomatis — kirim ulang link-nya "
                "kalau masih dibutuhkan."
            )
        return len(rows)


def delete(job_id: str | uuid.UUID) -> bool:
    """Hapus satu job. False kalau memang sudah tidak ada."""
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        return False
    with session_scope() as s:
        job = s.get(Job, key)
        if job is None:
            return False
        s.delete(job)
        return True


def remove_clip(job_id: str | uuid.UUID, clip_id: str) -> bool:
    """Buang satu klip dari kolom `clips`. False kalau job atau klipnya tidak ada."""
    try:
        key = uuid.UUID(str(job_id))
    except ValueError:
        return False
    with session_scope() as s:
        job = s.get(Job, key)
        if job is None or not job.clips:
            return False
        sisa = [c for c in job.clips if c.get("id") != clip_id]
        if len(sisa) == len(job.clips):
            return False
        # Ditugaskan ulang, bukan diubah di tempat: SQLAlchemy melacak perubahan
        # kolom JSONB lewat identitas objek, jadi list yang di-mutate langsung
        # tidak akan pernah ikut ter-commit.
        job.clips = sisa
        return True
