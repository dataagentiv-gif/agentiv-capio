"""RQ worker. Satu job per proses (PRD Bagian 5); scale horizontal dengan
menjalankan lebih banyak proses, tanpa ubah kode.

Mode multi (WORKER_MODE) menjalankan itu secara harfiah: proses ini jadi
supervisor yang men-subprocess.Popen dirinya sendiri N kali (bukan
os.fork() — tidak ada di Windows), tiap anak diberi WORKER_SLOT tetap.
"""
import os
import signal
import subprocess
import sys
import time

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

#: Identitas worker proses ini, disetel _jalankan_slot() sebelum menerima job
#: pertama. orchestrator.py membacanya balik per job (bukan sekali saat impor)
#: supaya tidak membekukan nilai kosong dari sebelum main() jalan.
WORKER_ID: str = ""


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

    if os.environ.get("WORKER_CHILD") == "1":
        # Anak yang disupervisi mode multi: housekeeping berbasis filesystem
        # di bawah ini sudah dilakukan proses induk sebelum memunculkan anak-
        # anaknya — menjalankannya lagi di tiap anak cuma kerja berulang dan
        # (untuk rmtree_stale/sapu_lama) risiko balapan menghapus berkas yang
        # sama. Langsung masuk ke slotnya.
        _jalankan_slot(int(os.environ.get("WORKER_SLOT", "0")))
        return

    # Workdir job yang gagal sengaja ditinggal untuk diperiksa, jadi disapu di
    # sini supaya tidak tumbuh tanpa batas — isinya source video mentah.
    rmtree_stale(settings.WORK_DIR)

    # Berkas unggahan yang tidak pernah jadi job. Orang membatalkan submit
    # setelah berkasnya terlanjur terunggah, dan yang tertinggal berukuran giga.
    if (sisa := unggah.sapu_lama()):
        log.info("%d berkas unggahan tak terpakai disapu", sisa)

    n = settings.WORKER_COUNT if settings.WORKER_MODE == "multi" else 1
    if n <= 1:
        _jalankan_slot(0)
    else:
        _supervisor(n)


def _jalankan_slot(slot: int) -> None:
    """Satu proses SimpleWorker sungguhan, dengan identitas slotnya sendiri."""
    global WORKER_ID
    WORKER_ID = f"slot-{slot}"

    # Job yang tertinggal di status berjalan MILIK SLOT INI dari proses
    # sebelumnya. Dibatasi ke slot sendiri (lihat bereskan_gantung) supaya di
    # mode multi, slot yang baru menyala tidak ikut menggagalkan job slot lain
    # yang masih sehat.
    gantung = jobs.bereskan_gantung(WORKER_ID)
    if gantung:
        log.warning("%d job yatim milik %s dari proses sebelumnya ditandai gagal",
                    gantung, WORKER_ID)

    conn = connection()
    # SimpleWorker, bukan Worker: rq.Worker default memakai os.fork() yang tidak
    # ada di Windows. SpawnWorker juga tidak bisa meski docs menyebutnya
    # Windows-friendly — ia mewarisi os.wait4/os.killpg dari Worker.
    #
    # death_penalty_class tidak perlu di-set: rq 2.x sudah memilih
    # TimerDeathPenalty sendiri saat signal.SIGALRM tidak tersedia.
    log.info("worker %s siap, antre di queue '%s'", WORKER_ID, QUEUE_NAME)
    SimpleWorker([Queue(QUEUE_NAME, connection=conn)], connection=conn).work(
        # RQScheduler melakukan fork. Dimatikan eksplisit walaupun defaultnya
        # sudah False, supaya tidak ada yang menyalakannya tanpa sadar.
        with_scheduler=False,
        logging_level="INFO",
    )


def _supervisor(n: int) -> None:
    """N proses anak lewat subprocess.Popen (bukan os.fork — tidak ada di
    Windows), tiap anak diberi WORKER_SLOT tetap supaya bereskan_gantung()
    anak yang baru menyala cuma membereskan job miliknya sendiri, bukan job
    slot lain yang masih sehat.

    ponytail: restart-on-death lewat poll(), tanpa backoff atau deteksi
    proses yang hidup-tapi-hang. Cukup untuk mengembalikan slot yang mati;
    kalau ada worker yang macet tanpa keluar, itu perbaikan berikutnya.
    """
    procs: dict[int, subprocess.Popen] = {}

    def _mulai(slot: int) -> None:
        env = {**os.environ, "WORKER_SLOT": str(slot), "WORKER_CHILD": "1"}
        procs[slot] = subprocess.Popen([sys.executable, "main.py", "worker"], env=env)
        log.info("worker slot %d dimulai (pid %d)", slot, procs[slot].pid)

    def _matikan_semua(*_a) -> None:
        for p in procs.values():
            p.terminate()
        for p in procs.values():
            p.wait()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _matikan_semua)
    signal.signal(signal.SIGINT, _matikan_semua)

    for slot in range(n):
        _mulai(slot)

    log.info("supervisor mengawasi %d worker", n)
    while True:
        time.sleep(5)
        for slot, p in list(procs.items()):
            if p.poll() is not None:
                log.warning("worker slot %d mati (kode %s) — dinyalakan ulang",
                            slot, p.returncode)
                _mulai(slot)
