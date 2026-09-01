"""Penyimpanan klip di folder lokal. Default project ini.

Dipilih jadi default supaya orang bisa mencoba tanpa akun Cloudflare sama
sekali. Klip mendarat sebagai file mp4 biasa di folder yang bisa dibuka lewat
File Explorer — dihapus, di-zip, atau diseret ke mana pun tanpa perantara.

Di dalam Docker, folder ini di-bind-mount ke host supaya file tetap terlihat
dari laptop, bukan terkurung di dalam container.
"""
import re
import shutil
from pathlib import Path

from config.settings import settings
from utils.logging import get

log = get(__name__)
CHUNK = 256 * 1024
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def check_config() -> None:
    """Selalu siap — itulah gunanya. Folder dibuat kalau belum ada."""
    Path(settings.CLIPS_DIR).mkdir(parents=True, exist_ok=True)


def _path(job_id: str, clip_id: str) -> Path:
    return Path(settings.CLIPS_DIR) / job_id / f"{clip_id}.mp4"


def save_clip(job_id: str, clip_id: str, path: Path) -> str:
    dest = _path(job_id, clip_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log.info("klip disimpan: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    # URL relatif ke server ini. Halaman Hasil memutar lewat route /clips yang
    # sama untuk kedua provider, jadi tidak ada cabang khusus di sisi UI.
    return f"/clips/{job_id}/{clip_id}"


def open_clip(job_id: str, clip_id: str, byte_range: str | None):
    """(potongan byte, panjang, Content-Range) — bentuk yang sama dengan R2."""
    p = _path(job_id, clip_id)
    if not p.is_file():
        raise FileNotFoundError(p)

    total = p.stat().st_size
    mulai, henti = 0, total - 1
    if byte_range and (m := _RANGE.match(byte_range.strip())):
        a, b = m.group(1), m.group(2)
        # `bytes=-500` berarti 500 byte TERAKHIR, bukan mulai dari nol.
        if not a:
            mulai = max(0, total - int(b or 0))
        else:
            mulai = min(int(a), total - 1)
            henti = min(int(b), total - 1) if b else total - 1

    panjang = henti - mulai + 1

    def baca():
        with open(p, "rb") as f:
            f.seek(mulai)
            sisa = panjang
            while sisa > 0:
                blok = f.read(min(CHUNK, sisa))
                if not blok:
                    break
                sisa -= len(blok)
                yield blok

    return baca(), panjang, (f"bytes {mulai}-{henti}/{total}" if byte_range else None)


def delete_job(job_id: str) -> None:
    shutil.rmtree(Path(settings.CLIPS_DIR) / job_id, ignore_errors=True)
