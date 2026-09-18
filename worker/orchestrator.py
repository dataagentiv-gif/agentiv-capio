"""Satu-satunya tempat yang memanggil stage secara berurutan dan menulis
progress ke db/jobs.py. Stage sendiri tidak tahu-menahu soal HTTP atau queue.
"""
import time
import traceback
from pathlib import Path

from config import env_store
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
import storage
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
    (Status.CROPPING, crop),
    (Status.CAPTIONING, caption),
    (Status.RENDERING, render),
    (Status.METADATA, metadata),
]
TOTAL_STEPS = len(STAGES) + 1  # +1 untuk upload


def _rincian(lama: dict[str, float]) -> str:
    """Waktu per stage, yang paling boros lebih dulu — itu yang dicari orang."""
    return ", ".join(
        f"{nama} {detik:.0f}s"
        for nama, detik in sorted(lama.items(), key=lambda x: -x[1])
    )


def _build_clips(ctx: dict, job_id: str) -> list[dict]:
    """Susun kontrak final untuk kolom `clips` JSONB (PRD Bagian 4)."""
    clips = []
    for seg in ctx["segments_final"]:
        meta = ctx["metadata"][seg["id"]]
        url = storage.save_clip(job_id, seg["id"], ctx["rendered"][seg["id"]])
        fallback_duo = (
            ctx.get("layout") == "duo"
            and not ctx.get("crops", {}).get(seg["id"], {}).get("duo")
        )
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
                "layout": "penuh" if fallback_duo else ctx.get("layout", "penuh"),
                "layout_fallback": fallback_duo,
            }
        )
    return clips


def run(job_id: str) -> None:
    """Entry point yang di-enqueue ke RQ. Payload cuma job_id — semua state lain
    dibaca dan ditulis lewat Postgres.
    """
    # .env dibaca ulang tiap job. Halaman Settings menulis ke file itu dari
    # proses API, sementara worker adalah proses terpisah yang memuat settings
    # sekali saat start — tanpa ini, mengganti provider atau key lewat UI tidak
    # berpengaruh sampai worker di-restart manual.
    env_store.reload()

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
        # Dibaca dari BARIS JOB, bukan dari settings: layout dipilih saat
        # menempel link, dan job yang mengantre beberapa jam harus tetap keluar
        # dengan bentuk yang dipilih waktu itu — bukan bentuk yang kebetulan
        # aktif saat gilirannya tiba.
        "layout": job.get("layout") or "penuh",
        "gaya": job.get("gaya") or {},
        "workdir": workdir,
        "deadline": Deadline(settings.JOB_TIMEOUT_SEC),
    }
    log.info("mulai job %s -> %s", job_id, workdir)

    # Lama tiap stage, dicatat untuk dilampirkan ke pesan kegagalan. Batas waktu
    # job dibagi seluruh stage, jadi saat deadline terlampaui pertanyaannya
    # selalu "siapa yang memakannya" — dan tanpa angka ini jawabannya cuma
    # tebakan. Terjadi sungguhan: satu video 26 menit gagal karena UNDUHANNYA
    # sendiri menghabiskan seluruh anggaran, tapi pesannya hanya "deadline job
    # terlampaui" sehingga terlihat seperti pipeline yang rusak.
    lama: dict[str, float] = {}

    # Import di sini, bukan top-level: WORKER_ID disetel runner.main() saat
    # proses worker mulai, dan import top-level akan membekukan nilai lama
    # ("") yang dibaca sebelum itu terjadi.
    from worker.runner import WORKER_ID as _worker_id

    try:
        for i, (status, stage) in enumerate(STAGES):
            ctx["deadline"].check(status)
            jobs.update_status(job_id, status, progress=int(i / TOTAL_STEPS * 100),
                                worker_id=_worker_id)
            log.info("stage %s", status)
            t0 = time.monotonic()
            ctx.update(stage.run(ctx))
            lama[status] = time.monotonic() - t0

        jobs.update_status(job_id, Status.UPLOADING, progress=int(8 / TOTAL_STEPS * 100),
                            worker_id=_worker_id)
        t0 = time.monotonic()
        clips = _build_clips(ctx, str(job_id))
        lama[Status.UPLOADING] = time.monotonic() - t0
        jobs.finish(job_id, clips)
        log.info("job %s selesai: %d klip (%s)", job_id, len(clips), _rincian(lama))

        # Baru dihapus setelah upload sukses. Kalau job gagal, workdir sengaja
        # ditinggal utuh supaya artefak antar-stage bisa diperiksa.
        rmtree_retry(workdir)

    except TimeoutError as e:
        # Kegagalan deadline butuh perlakuan sendiri: yang perlu diketahui
        # bukan traceback-nya — stack-nya selalu sama — melainkan stage mana
        # yang menghabiskan anggaran, karena itu yang menentukan apakah
        # JOB_TIMEOUT_SEC perlu dinaikkan atau ada yang benar-benar macet.
        rinci = _rincian(lama) or "belum ada stage yang selesai"
        log.error("job %s kehabisan waktu: %s | %s", job_id, e, rinci)
        jobs.fail(
            job_id,
            f"Waktu job habis ({settings.JOB_TIMEOUT_SEC}s). Waktu terpakai per "
            f"tahap: {rinci}.\n\nKalau tahap yang boros adalah download, "
            f"videonya terlalu panjang atau jaringan sedang lambat — naikkan "
            f"JOB_TIMEOUT_SEC di halaman Setting.\n\n{traceback.format_exc()}",
        )
        raise

    except Exception as e:  # noqa: BLE001
        log.error("job %s gagal: %s", job_id, e)
        jobs.fail(job_id, f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")
        raise
