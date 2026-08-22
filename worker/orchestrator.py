"""Satu-satunya tempat yang memanggil stage secara berurutan dan menulis
progress ke db/jobs.py. Stage sendiri tidak tahu-menahu soal HTTP atau queue.
"""
import traceback
from pathlib import Path

from config.settings import settings
from db import jobs
from db.models import Status
from pipeline.stages import (
    caption,
    crop,
    download,
    metadata,
    refine,
    render,
    segment,
    transcribe,
)
from storage.client import upload_clip
from utils.ffmpeg_helpers import Deadline, rmtree_retry
from utils.logging import get

log = get(__name__)

# Urutan tetap, ditentukan di kode. Ini pipeline sekuensial berbasis workflow,
# bukan agentic loop — LLM dipanggil untuk tugas sempit di Stage 3 dan 8, tidak
# pernah memutuskan urutan eksekusi.
STAGES = [
    (Status.DOWNLOADING, download),
    (Status.TRANSCRIBING, transcribe),
    (Status.SEGMENTING, segment),
    (Status.REFINING, refine),
    (Status.CAPTIONING, caption),
    (Status.CROPPING, crop),
    (Status.RENDERING, render),
    (Status.METADATA, metadata),
]
TOTAL_STEPS = len(STAGES) + 1  # +1 untuk upload


def _build_clips(ctx: dict, job_id: str) -> list[dict]:
    """Susun kontrak final untuk kolom `clips` JSONB (PRD Bagian 4)."""
    clips = []
    for seg in ctx["segments_final"]:
        meta = ctx["metadata"][seg["id"]]
        url = upload_clip(job_id, seg["id"], ctx["rendered"][seg["id"]])
        clips.append(
            {
                "id": seg["id"],
                "url": url,
                "duration": round(seg["end"] - seg["start"], 1),
                "score": seg["score"],
                "hook": seg["hook"],
                "reason": seg["reason"],
                "title": meta["title"],
                "caption": meta["caption"],
                "hashtags": meta["hashtags"],
            }
        )
    return clips


def run(job_id: str) -> None:
    """Entry point yang di-enqueue ke RQ. Payload cuma job_id — semua state lain
    dibaca dan ditulis lewat Postgres.
    """
    job = jobs.get(job_id)
    if job is None:
        raise KeyError(f"job {job_id} tidak ada di database")

    # Workdir sengaja pendek (8 karakter pertama UUID): path Windows mentok di
    # MAX_PATH 260 dan artefak per job punya nama yang cukup panjang sendiri.
    workdir: Path = settings.WORK_DIR / str(job_id)[:8]
    workdir.mkdir(parents=True, exist_ok=True)

    ctx = {
        "job_id": str(job_id),
        "url": job["url"],
        "target_clips": job["target_clips"],
        "workdir": workdir,
        "deadline": Deadline(settings.JOB_TIMEOUT_SEC),
    }
    log.info("mulai job %s -> %s", job_id, workdir)

    try:
        for i, (status, stage) in enumerate(STAGES):
            ctx["deadline"].check(status)
            jobs.update_status(job_id, status, progress=int(i / TOTAL_STEPS * 100))
            log.info("stage %s", status)
            ctx.update(stage.run(ctx))

        jobs.update_status(job_id, Status.UPLOADING, progress=int(8 / TOTAL_STEPS * 100))
        clips = _build_clips(ctx, str(job_id))
        jobs.finish(job_id, clips)
        log.info("job %s selesai: %d klip", job_id, len(clips))

        # Baru dihapus setelah upload sukses. Kalau job gagal, workdir sengaja
        # ditinggal utuh supaya artefak antar-stage bisa diperiksa.
        rmtree_retry(workdir)

    except Exception as e:  # noqa: BLE001
        log.error("job %s gagal: %s", job_id, e)
        jobs.fail(job_id, f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")
        raise
