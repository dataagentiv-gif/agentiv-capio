"""RQ worker. Satu job per proses (PRD Bagian 5); scale horizontal dengan
menjalankan lebih banyak proses, tanpa ubah kode.
"""
from rq import Queue, SimpleWorker

import asr
from config import env_store
from config.settings import settings
from db import jobs
from jobqueue.client import QUEUE_NAME, connection
import storage
import unggah
from utils.ffmpeg_helpers import rmtree_stale
from utils.logging import get, setup

log = get(__name__)


def main() -> None:
    setup()
    # WAJIB sebelum check_config, dan alasannya sama persis dengan yang ditulis
    # di docstring env_store.reload(): compose memuat .env ke environment
    # container saat container DIBUAT, dan pydantic-settings memprioritaskan
    # environment di atas isi file.
    #
    # Sisi API sudah memanggil ini saat halaman Setting menyimpan; worker
    # terlewat, dan akibatnya baru terlihat di mesin yang key-nya mulai dari
    # kosong — yaitu setiap pemasangan baru. Di sana worker membaca nilai kosong
    # dari saat container lahir, check_config melempar, `restart: unless-stopped`
    # mengulanginya selamanya, dan mengisi key lewat halaman Setting TIDAK
    # menyembuhkannya: tulisannya masuk ke file, worker tetap membaca environment
    # lama. Satu-satunya obatnya `docker compose up -d` sekali lagi, dan tidak
    # ada pengguna yang akan menebak itu.
    env_store.reload()

    # Diperiksa SEBELUM worker menerima job: folder klip dibuat sekarang, dan
    # key transkrip yang bolong ketahuan di detik pertama — bukan setelah
    # download dan render selesai, yang berarti belasan menit terbuang untuk
    # job yang sejak awal pasti gagal.
    storage.check_config()
    asr.check_config()

    # Workdir job yang gagal sengaja ditinggal untuk diperiksa, jadi disapu di
    # sini supaya tidak tumbuh tanpa batas — isinya source video mentah.
    rmtree_stale(settings.WORK_DIR)

    # Berkas unggahan yang tidak pernah jadi job. Orang membatalkan submit
    # setelah berkasnya terlanjur terunggah, dan yang tertinggal berukuran giga.
    if (sisa := unggah.sapu_lama()):
        log.info("%d berkas unggahan tak terpakai disapu", sisa)

    # Job yang tertinggal di status berjalan dari proses sebelumnya. Ini
    # satu-satunya saat kita tahu pasti tidak ada job yang sedang dikerjakan,
    # jadi apa pun yang masih berstatus berjalan sudah pasti yatim.
    gantung = jobs.bereskan_gantung()
    if gantung:
        log.warning("%d job yatim dari proses sebelumnya ditandai gagal", gantung)

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
