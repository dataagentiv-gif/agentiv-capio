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


#: Worker RQ yang menganggur memblokir di BLPOP selama 405 detik
#: (DEFAULT_WORKER_TTL 420 dikurangi 15). Batas soket HARUS lebih longgar dari
#: itu, kalau tidak soketnya kedaluwarsa lebih dulu, redis-py melempar
#: TimeoutError, dan RQ menanggapinya dengan "Redis connection timeout,
#: quitting..." lalu keluar.
#:
#: Terlihat di log sungguhan: worker mati dan di-restart tiap 6 menit 45 detik
#: — persis 405 detik — sepanjang jam-jam menganggur. Tidak ada job yang gagal
#: karenanya (timeout ini hanya berdenyut saat tidak ada pekerjaan), tapi tiap
#: restart menjalankan bereskan_gantung(), dan itu menandai gagal setiap job
#: yang berstatus berjalan. Job yang mengantre di detik yang salah akan
#: dinyatakan yatim padahal baru saja dimulai.
BLOKIR_DEQUEUE = 405
SOKET_TIMEOUT = BLOKIR_DEQUEUE + 45


def connection() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        socket_timeout=SOKET_TIMEOUT,
        # Docker memutus koneksi TCP yang diam terlalu lama. Tanpa keepalive,
        # soket yang menganggur tujuh menit sudah mati saat balasan BLPOP
        # akhirnya datang — dan gejalanya sama persis dengan timeout di atas.
        socket_keepalive=True,
        # Diperiksa berkala saat menganggur, jadi koneksi yang sudah putus
        # ketahuan dan diganti sebelum dipakai, bukan saat sedang dibutuhkan.
        health_check_interval=30,
        retry_on_timeout=True,
    )


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
