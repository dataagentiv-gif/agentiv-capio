"""Rotasi beberapa API key, dengan status yang bisa dibaca lintas proses.

Kenapa lewat Redis dan bukan sekadar penghitung di memori: yang MEMAKAI key
adalah worker, sementara yang MENAMPILKAN statusnya adalah proses API. Keduanya
proses terpisah, jadi penghitung di memori worker tidak akan pernah terlihat di
halaman Setting. Redis sudah ada di sistem ini, dan INCR memberi urutan yang
disepakati kedua proses tanpa penguncian apa pun.

Kalau Redis sedang tidak bisa dihubungi, rotasi jatuh ke penghitung lokal.
Kehilangan tampilan status jauh lebih ringan daripada menggagalkan job yang
sedang berjalan hanya karena panel status tidak bisa ditulis.
"""
import itertools
import json
import time

from config.settings import settings
from utils.logging import get

log = get(__name__)

POOLS = ("groq", "gemini")
_lokal = itertools.count()
# Status per key tidak perlu abadi: begitu worker dijalankan lagi, hasil lama
# tidak lagi menggambarkan keadaan sekarang.
TTL = 24 * 3600


def keys(pool: str) -> list[str]:
    return settings.groq_keys if pool == "groq" else settings.gemini_keys


def _redis():
    from jobqueue.client import connection

    return connection()


def ambil(pool: str) -> tuple[int, str]:
    """Key berikutnya beserta indeksnya (0-based). Berputar x+1 tiap dipanggil."""
    daftar = keys(pool)
    if not daftar:
        raise RuntimeError(f"Tidak ada API key untuk {pool} — isi di halaman Setting")
    try:
        n = _redis().incr(f"keypool:{pool}:n")
    except Exception as e:  # noqa: BLE001 — jangan gagalkan job karena panel status
        log.debug("keypool %s pakai penghitung lokal: %s", pool, e)
        n = next(_lokal)
    i = (n - 1) % len(daftar)
    return i, daftar[i]


def lapor(pool: str, idx: int, ok: bool, pesan: str = "") -> None:
    """Catat hasil pemakaian satu key, untuk ditampilkan di halaman Setting."""
    try:
        _redis().setex(
            f"keypool:{pool}:{idx}", TTL,
            json.dumps({"ok": ok, "pesan": pesan[:160], "pada": time.time()}),
        )
    except Exception as e:  # noqa: BLE001
        log.debug("keypool %s gagal mencatat status: %s", pool, e)


def _mask(k: str) -> str:
    return f"{k[:6]}••••{k[-4:]}" if len(k) > 14 else "••••"


def status(pool: str) -> dict:
    """Ringkasan untuk UI: tiap key, mana yang berikutnya dipakai, hasil terakhir."""
    daftar = keys(pool)
    if not daftar:
        return {"pool": pool, "jumlah": 0, "keys": []}

    berikut, catatan = 0, {}
    try:
        r = _redis()
        n = int(r.get(f"keypool:{pool}:n") or 0)
        berikut = n % len(daftar)
        for i in range(len(daftar)):
            mentah = r.get(f"keypool:{pool}:{i}")
            if mentah:
                catatan[i] = json.loads(mentah)
    except Exception as e:  # noqa: BLE001
        log.debug("keypool %s status tidak terbaca: %s", pool, e)

    return {
        "pool": pool,
        "jumlah": len(daftar),
        "keys": [
            {
                "index": i,
                "mask": _mask(k),
                # `berikutnya` = yang akan dipakai pada panggilan berikutnya.
                # Ini bukan "sedang dipakai": satu panggilan LLM selesai dalam
                # hitungan detik, jadi menampilkan yang sedang berjalan hampir
                # selalu sudah basi saat halaman digambar.
                "berikutnya": i == berikut,
                **(catatan.get(i) or {}),
            }
            for i, k in enumerate(daftar)
        ],
    }
