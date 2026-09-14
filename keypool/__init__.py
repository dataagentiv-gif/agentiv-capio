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

POOLS = ("elevenlabs", "gemini")
_lokal = itertools.count()
# Status per key tidak perlu abadi: begitu worker dijalankan lagi, hasil lama
# tidak lagi menggambarkan keadaan sekarang.
TTL = 24 * 3600


def keys(pool: str) -> list[str]:
    """Daftar key satu pool. Nama pool = nama properti di settings, jadi
    menambah provider tidak menambah percabangan di sini."""
    return getattr(settings, f"{pool}_keys")


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

    # Key mana yang dipakai berikutnya ditanyakan ke ROUTER, bukan dihitung
    # dari penghitung putar lama. Sejak pemilihan pasangan (key, model) pindah
    # ke llm/rute.py, penghitung itu tidak pernah maju lagi — dan panel ini akan
    # menunjuk key #1 selamanya sambil terlihat meyakinkan.
    berikut, catatan = 0, {}
    try:
        from llm import rute

        urut = rute.urutan(pool, rute.daftar() if pool == "gemini" else [""],
                           len(daftar))
        berikut = urut[0][1] if urut else 0
    except Exception as e:  # noqa: BLE001
        log.debug("keypool %s tidak bisa menanyakan urutan: %s", pool, e)

    try:
        r = _redis()
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


# Nama env var penyimpan tiap pool. Dipisahkan dari kode pemakainya supaya
# menambah provider baru cukup menambah satu baris di sini.
ENV_FIELD = {p: f"{p.upper()}_API_KEYS" for p in POOLS}


def _simpan(pool: str, daftar: list[str]) -> None:
    from config import env_store

    # Nilai kosong diabaikan env_store.write ("kosong = jangan diubah"), jadi
    # menghapus key TERAKHIR ditangani terpisah lewat penulisan langsung.
    if daftar:
        env_store.write({ENV_FIELD[pool]: ",".join(daftar)})
    else:
        env_store._tulis_env(env_store.ENV_PATH, {ENV_FIELD[pool]: ""})
        env_store.reload()


def tambah(pool: str, mentah: str) -> tuple[int, str]:
    """Tambah satu key atau lebih. Kembalikan (jumlah ditambah, pesan).

    Koma tetap diterima dan dipecah: menempel beberapa key sekaligus itu wajar,
    dan menolaknya hanya memaksa orang menambah satu per satu tanpa alasan.
    """
    ada = keys(pool)
    baru, lewat = [], 0
    for k in str(mentah).replace("\n", ",").split(","):
        k = k.strip()
        if not k:
            continue
        if k in ada or k in baru:
            lewat += 1
            continue
        baru.append(k)

    if not baru:
        return 0, "Key itu sudah ada" if lewat else "Tidak ada key yang bisa ditambahkan"

    _simpan(pool, ada + baru)
    pesan = f"{len(baru)} key ditambahkan"
    return len(baru), pesan + (f", {lewat} dilewati karena sudah ada" if lewat else "")


def hapus(pool: str, index: int) -> tuple[bool, str]:
    ada = keys(pool)
    if not 0 <= index < len(ada):
        return False, "Key tidak ditemukan"
    sisa = ada[:index] + ada[index + 1:]
    _simpan(pool, sisa)
    # Status per key disimpan per INDEKS, jadi setelah daftar bergeser catatan
    # lama akan menempel pada key yang salah. Lebih baik dikosongkan.
    try:
        r = _redis()
        for i in range(len(ada)):
            r.delete(f"keypool:{pool}:{i}")
    except Exception:  # noqa: BLE001
        pass
    return True, f"Key #{index + 1} dihapus"
