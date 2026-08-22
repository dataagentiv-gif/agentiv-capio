"""CRUD tabel jobs. Satu fungsi = satu operasi, tanpa logic pipeline."""
import uuid

from sqlalchemy import select

from db.models import Job, Status, session_scope


def create(url: str, target_clips: int) -> dict:
    with session_scope() as s:
        job = Job(url=url, target_clips=target_clips, status=Status.QUEUED)
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
    with session_scope() as s:
        job = s.get(Job, uuid.UUID(str(job_id)))
        if job is None:
            raise KeyError(f"job {job_id} tidak ada")
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
