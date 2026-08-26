"""RQ worker. Satu job per proses (PRD Bagian 5); scale horizontal dengan
menjalankan lebih banyak proses, tanpa ubah kode.
"""
from rq import Queue, SimpleWorker

import asr
from config.settings import settings
from jobqueue.client import QUEUE_NAME, connection
from storage.client import check_config
from utils.ffmpeg_helpers import rmtree_stale
from utils.logging import get, setup

log = get(__name__)


def main() -> None:
    setup()
    # Diperiksa SEBELUM worker menerima job. Upload adalah langkah terakhir
    # pipeline, jadi tanpa ini satu env var R2 yang kosong baru ketahuan setelah
    # download, transkrip, dan render selesai — belasan menit terbuang untuk job
    # yang sejak awal pasti gagal.
    check_config()
    asr.check_config()

    # Workdir job yang gagal sengaja ditinggal untuk diperiksa, jadi disapu di
    # sini supaya tidak tumbuh tanpa batas — isinya source video mentah.
    rmtree_stale(settings.WORK_DIR)

    conn = connection()
    # SimpleWorker, bukan Worker: rq.Worker default memakai os.fork() yang tidak
    # ada di Windows. SpawnWorker juga tidak bisa meski docs menyebutnya
    # Windows-friendly — ia mewarisi os.wait4/os.killpg dari Worker.
    #
    # death_penalty_class tidak perlu di-set: rq 2.x sudah memilih
    # TimerDeathPenalty sendiri saat signal.SIGALRM tidak tersedia.
    log.info("worker siap, antre di queue '%s'", QUEUE_NAME)
    SimpleWorker([Queue(QUEUE_NAME, connection=conn)], connection=conn).work(
        # RQScheduler melakukan fork. Dimatikan eksplisit walaupun defaultnya
        # sudah False, supaya tidak ada yang menyalakannya tanpa sadar.
        with_scheduler=False,
        logging_level="INFO",
    )
