"""Semua panggilan ffmpeg/ffprobe lewat sini, supaya tiga hal tidak pernah lupa
dipasang: batas waktu yang terikat deadline job, -nostdin, dan decoding UTF-8.
"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from utils.logging import get

log = get(__name__)


class Deadline:
    """Batas waktu total satu job (PRD Bagian 6: 30 menit).

    Ini yang benar-benar menegakkan timeout, bukan job_timeout milik RQ.
    TimerDeathPenalty milik RQ memakai PyThreadState_SetAsyncExc yang baru
    bekerja saat thread target mengeksekusi bytecode Python — kalau thread
    sedang menunggu subprocess ffmpeg yang hang, exception-nya tertunda dan
    tidak pernah membunuh proses anak itu. Maka sisa waktu di sini disuntikkan
    ke tiap subprocess sebagai timeout=.
    """

    def __init__(self, total_sec: float):
        self.end = time.monotonic() + total_sec

    def remaining(self, cap: float = 600.0) -> float:
        left = self.end - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline job terlampaui")
        return min(cap, left)

    def check(self, stage: str) -> None:
        if time.monotonic() >= self.end:
            raise TimeoutError(f"deadline job terlampaui sebelum stage '{stage}'")


def run(
    args: list[str],
    deadline: Deadline,
    cwd: Path | None = None,
    cap: float = 600.0,
    check: bool = True,
    binary: bool = False,
) -> subprocess.CompletedProcess:
    """Jalankan ffmpeg/ffprobe/yt-dlp. Selalu argv list, tidak pernah shell.

    shell=False bukan gaya-gayaan: home directory di mesin ini ada spasinya, dan
    command yang dirakit jadi string bakal pecah di path pertama yang lewat.

    `binary=True` untuk output rawvideo — stdout tidak boleh di-decode teks.
    """
    log.debug("run: %s", " ".join(args[:6]))
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        # ffmpeg yang mewarisi stdin console di Windows bisa memakan input dan
        # sesekali menggantung. Dua sabuk pengaman sekaligus.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding=None if binary else "utf-8",
        errors=None if binary else "replace",
        timeout=deadline.remaining(cap),
    )
    if binary and check and proc.returncode != 0:
        raise RuntimeError(
            f"{args[0]} keluar dengan kode {proc.returncode}:\n"
            f"{proc.stderr.decode('utf-8', 'replace')[-3000:]}"
        )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"{args[0]} keluar dengan kode {proc.returncode}:\n{proc.stderr[-3000:]}"
        )
    return proc


def ffmpeg(args: list[str], deadline: Deadline, **kw) -> subprocess.CompletedProcess:
    """ffmpeg dengan flag yang selalu sama di depan.

    Catatan: loglevel di sini `error`. Filter yang menulis hasil ke log (
    silencedetect, metadata=print) memakai level `info` dan output-nya akan
    tertelan habis — pemanggilnya wajib menimpa dengan -v info sendiri.
    """
    return run(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-nostats", "-v", "error", *args],
        deadline,
        **kw,
    )


def probe(path: Path, deadline: Deadline) -> dict:
    """Kembalikan {duration, width, height} dari file video."""
    proc = run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", str(path),
        ],
        deadline,
        cap=60,
    )
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
    }


def rmtree_retry(path: Path, attempts: int = 3) -> None:
    """shutil.rmtree yang tahan WinError 32.

    File tidak bisa dihapus selama masih dipegang handle, dan Defender menahan
    handle beberapa saat setelah ffmpeg menutup file.

    Folder yang memang tidak ada bukan kegagalan. Job yang sukses sudah
    membuang workdir-nya sendiri, jadi menghapus job seperti itu dulu berarti
    tiga percobaan, dua detik jeda, dan satu peringatan palsu di log.
    """
    if not path.exists():
        return
    for i in range(attempts):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except OSError as e:
            if i == attempts - 1:
                log.warning("gagal hapus %s: %s — dibiarkan, disapu saat start", path, e)
                return
            time.sleep(1.0)


def rmtree_stale(root: Path, keep: int = 20) -> None:
    """Sapu workdir job gagal yang menumpuk.

    Workdir job yang gagal sengaja tidak dihapus supaya artefaknya bisa
    diperiksa, tapi tanpa penyapuan sesekali folder itu tumbuh tanpa batas —
    isinya source video mentah.
    """
    if not root.exists():
        return
    # Hanya folder yang BENAR-BENAR workdir job yang disapu. Namanya delapan
    # karakter heksadesimal pertama dari job id, dan pola itu yang dipakai
    # sebagai penanda kepemilikan.
    #
    # Tanpa saringan ini, folder lain di /work ikut jadi kandidat hapus dan
    # bersaing memperebutkan `keep` slot yang sama — termasuk /work/unggah yang
    # berisi berkas yang baru saja diunggah orang dan belum sempat jadi job.
    dirs = sorted(
        (d for d in root.iterdir()
         if d.is_dir() and re.fullmatch(r"[0-9a-f]{8}", d.name)),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for d in dirs[keep:]:
        log.info("menyapu workdir lama: %s", d)
        rmtree_retry(d)
