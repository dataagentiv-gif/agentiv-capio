"""Penyimpanan klip: file mp4 biasa di folder lokal.

Sengaja tanpa storage cloud sama sekali. Satu-satunya layanan berbayar yang
tersisa di project ini adalah transkrip dan LLM — selebihnya berjalan di mesin
sendiri, dan hasil akhirnya berupa file yang bisa dibuka, dihapus, atau
disalin lewat file manager tanpa perantara apa pun.

Tidak dipecah jadi paket berisi beberapa provider karena implementasinya cuma
satu; lapisan pemilih untuk satu implementasi hanyalah indirection.
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
    # URL relatif ke server ini, dilayani route /clips. Disimpan begini ke
    # database supaya halaman Hasil tidak perlu tahu di mana file sebenarnya
    # berada — memindahkan CLIPS_DIR tidak membatalkan url job lama.
    return f"/clips/{job_id}/{clip_id}"


def open_clip(job_id: str, clip_id: str, byte_range: str | None = None):
    """(potongan byte, panjang, Content-Range).

    Header Range ditangani sendiri karena tanpanya pemutar video di browser
    tidak bisa menggeser posisi — videonya tetap terbuka, cuma hanya bisa
    diputar dari awal, dan itu tidak memunculkan error apa pun.
    """
    p = _path(job_id, clip_id)
    if not p.is_file():
        raise FileNotFoundError(p)

    total = p.stat().st_size
    mulai, henti = 0, total - 1
    if byte_range and (m := _RANGE.match(byte_range.strip())):
        a, b = m.group(1), m.group(2)
        # `bytes=-500` berarti 500 byte TERAKHIR, bukan mulai dari nol. Salah
        # menafsirkannya membuat pemutar gagal membaca moov atom di ekor file.
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


def delete_clip(job_id: str, clip_id: str) -> None:
    _path(job_id, clip_id).unlink(missing_ok=True)
    folder = Path(settings.CLIPS_DIR) / job_id
    # Folder job ikut dibuang begitu klip terakhirnya hilang, supaya tidak
    # meninggalkan folder kosong yang menumpuk.
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
