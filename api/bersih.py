"""Pembersihan otomatis task dan hasil lama (Setting → Infra → Auto clear).

Jalan di proses API, bukan worker. API selalu hidup, memegang volume clips/
dan /work yang sama, dan objek `settings`-nya dibaca ulang tiap kali halaman
Setting menyimpan — jadi nyala/mati berlaku tanpa restart apa pun. Worker
justru bisa sibuk berjam-jam di satu job, atau berjalan N kali di mode multi.

Keputusan "apa yang dibuang" dipisah jadi fungsi murni (`rencana`) supaya bisa
diuji tanpa database: fitur yang menghapus data tidak boleh pengujiannya
bergantung pada Postgres yang kebetulan menyala.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from config.settings import settings
from db import jobs
import storage
from utils.ffmpeg_helpers import rmtree_retry
from utils.logging import get

log = get(__name__)

TARGET = ("keduanya", "task", "hasil")
JEDA = 3600   # detik antar pengecekan
AWAL = 60     # pengecekan pertama, dihitung dari API menyala


def hapus_job(job_id: str) -> bool:
    """Hapus job beserta seluruh berkasnya. False kalau barisnya sudah tidak ada.

    Dipakai tombol Hapus dan auto clear sekaligus, supaya "menghapus job" cuma
    punya satu arti. Ikut membuang workdir: workdir job gagal sengaja ditinggal
    untuk diperiksa, dan isinya video sumber mentah — justru itu yang paling
    cepat memenuhi disk.
    """
    if not jobs.delete(job_id):
        return False
    storage.delete_job(job_id)
    rmtree_retry(settings.WORK_DIR / job_id[:8])
    return True


def rencana(daftar: list[dict], target: str) -> tuple[list[str], list[str]]:
    """(id job yang dihapus utuh, id job yang cuma dibuang klipnya).

    `daftar` sudah disaring ke job selesai yang lewat umur. "task" sengaja
    tidak menyentuh job yang masih punya klip: menghapus barisnya membuat
    klipnya lenyap dari halaman Hasil sementara berkasnya tertinggal di disk.
    """
    hapus, kosongkan = [], []
    for j in daftar:
        punya_klip = bool(j.get("clips"))
        if target == "keduanya" or (target == "task" and not punya_klip):
            hapus.append(j["id"])
        elif target == "hasil" and punya_klip:
            kosongkan.append(j["id"])
    return hapus, kosongkan


def sapu(sekarang: datetime | None = None) -> dict:
    """Satu kali pembersihan sesuai setelan. Kembalikan hitungannya."""
    hasil = {"task": 0, "hasil": 0}
    if not settings.AUTO_CLEAR_ENABLED or settings.AUTO_CLEAR_DAYS < 1:
        return hasil
    target = str(settings.AUTO_CLEAR_TARGET).strip().lower()
    if target not in TARGET:
        # Dilewati, BUKAN jatuh ke nilai bawaan: bawaannya "keduanya", dan
        # salah ketik tidak boleh berakhir dengan menghapus semua klip.
        log.warning("AUTO_CLEAR_TARGET='%s' tidak dikenal — pembersihan dilewati",
                    settings.AUTO_CLEAR_TARGET)
        return hasil

    batas = (sekarang or datetime.now(timezone.utc)) - timedelta(days=settings.AUTO_CLEAR_DAYS)
    hapus, kosongkan = rencana(jobs.list_selesai_sebelum(batas), target)
    for jid in hapus:
        hapus_job(jid)
    for jid in kosongkan:
        # Baris dulu, baru berkas: kalau penghapusan berkas gagal, yang tersisa
        # berkas yatim di disk — bukan halaman Hasil yang menunjuk klip hilang.
        jobs.kosongkan_clips(jid)
        storage.delete_job(jid)

    hasil = {"task": len(hapus), "hasil": len(kosongkan)}
    if hapus or kosongkan:
        log.info("auto clear (%s, lebih dari %d hari): %d job dihapus, %d job dibuang klipnya",
                 target, settings.AUTO_CLEAR_DAYS, len(hapus), len(kosongkan))
    return hasil


async def loop() -> None:
    """Pengecekan berkala, dijalankan lifespan API.

    ponytail: satu loop di satu proses API. Kalau suatu saat API berjalan
    lebih dari satu instance, sapuannya ikut berlipat — butuh kunci di Redis.
    """
    await asyncio.sleep(AWAL)
    while True:
        try:
            await asyncio.to_thread(sapu)
        except Exception as e:  # noqa: BLE001 — satu sapuan gagal jangan mematikan loop
            log.warning("auto clear gagal: %s", e)
        await asyncio.sleep(JEDA)
