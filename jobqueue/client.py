"""Adapter Redis + RQ.

Folder ini bernama `jobqueue`, bukan `queue` seperti di PRD Bagian 2: `queue`
adalah nama modul stdlib, dan `python main.py` menaruh root project di
sys.path[0] sehingga `import queue` dari logging.handlers, concurrent.futures,
atau dependency mana pun akan nyasar ke folder ini.
"""
from redis import Redis
from rq import Queue

from config.settings import settings

QUEUE_NAME = "clips"

# Payload job cuma {job_id}. Semua state lain dibaca/ditulis worker lewat
# Postgres (db/jobs.py), bukan lewat queue — kontrak di PRD Bagian 4.
JOB_FUNC = "worker.orchestrator.run"


def connection() -> Redis:
    return Redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=connection())


def enqueue(job_id: str) -> None:
    # job_timeout WAJIB angka nyata, bukan -1. SimpleWorker (satu-satunya worker
    # yang jalan di Windows) menjalankan job di thread dequeue sehingga tidak bisa
    # heartbeat di tengah job, dan get_heartbeat_ttl() jatuh ke DEFAULT_WORKER_TTL
    # 420 detik saat timeout == -1. Akibatnya execution key di Redis expired di
    # menit ke-7 dan job 30 menit ditandai abandoned padahal masih render.
    #
    # Angka ini cuma jaring pengaman RQ; deadline sebenarnya (JOB_TIMEOUT_SEC)
    # ditegakkan orchestrator pakai time.monotonic().
    get_queue().enqueue(
        JOB_FUNC,
        job_id,
        job_timeout=settings.JOB_TIMEOUT_SEC + 900,
        result_ttl=86400,
        failure_ttl=604800,
    )
