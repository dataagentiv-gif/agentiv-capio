"""RQ worker. Satu job per proses (PRD Bagian 5); scale horizontal dengan
menjalankan lebih banyak proses, tanpa ubah kode.
"""
from rq import SimpleWorker

from jobqueue.client import QUEUE_NAME, connection
from rq import Queue
from utils.ffmpeg_helpers import Deadline, warm_font_cache
from utils.logging import get, setup

log = get(__name__)


def main() -> None:
    setup()
    # Panggilan filter `subtitles` pertama bisa berhenti puluhan detik karena
    # libass membangun cache font Windows lewat fontconfig. Dibayar di sini
    # sekali, supaya tidak muncul sebagai "stage render hang" di job pertama.
    warm_font_cache(Deadline(180))

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
