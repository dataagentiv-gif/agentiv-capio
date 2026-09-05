"""Pemilihan pasangan (key, model) berjenjang untuk Gemini.

Urutannya DIPAKU di kode, bukan disetel dari UI. Alasannya bukan menyembunyikan
sesuatu: urutan ini hasil pengujian pada transkrip sungguhan lewat jalur kode
produksi, dan setelan yang bisa diputar sembarangan hanya akan menghasilkan
kombinasi yang lebih buruk tanpa ada yang tahu — mutu klip turun perlahan, tanpa
satu pun error.

Aturannya sederhana dan itu disengaja:

1. Tier teratas dipakai TERUS, di seluruh key, selama masih ada satu key yang
   kuotanya belum habis untuk model itu.
2. Baru setelah SEMUA key habis untuk tier itu, turun ke tier berikutnya.
3. Kuota gratis Gemini dihitung per key DAN per model, jadi "habis" dicatat per
   pasangan — bukan per model saja. Satu key yang habis tidak boleh menjatuhkan
   model itu untuk key lain.

Soal pulihnya: TIDAK ada penjadwalan dan tidak ada tebakan kapan Google
me-reset kuota. Tanda "habis" cuma diberi umur pendek. Begitu umurnya lewat,
pasangan itu otomatis dianggap layak dicoba lagi — jadi tier teratas dicoba
ulang sendiri secara berkala tanpa ada yang menjadwalkannya.

Ongkos pemulihannya satu panggilan gagal per pasangan per jam. Panggilan yang
kena 429 dijawab server dalam ratusan milidetik dan tidak memotong kuota apa
pun, jadi pada job yang berjalan menit-menitan ini tidak terasa. Menebak jam
reset Google akan lebih hemat di atas kertas, tapi menuntut zona waktu Pasifik
beserta DST-nya — dan tebakan yang meleset menahan tier teratas jauh lebih lama
daripada satu panggilan gagal.
"""
import time

import keypool
from utils.logging import get

log = get(__name__)

#: Urut menurut mutu, bukan menurut kecepatan. Diuji pada transkrip podcast
#: 27 menit lewat jalur kode produksi. Yang menentukan urutan: berapa klip
#: benar-benar keluar dari yang diminta, dan berapa persen start_idx cocok
#: dengan hook yang ditulis model itu sendiri.
TIER = [
    "gemini-3.5-flash",         # 5,0/5 klip · index 100% · 26 detik
    "gemini-3.5-flash-lite",    # 3,3/5 klip · index  93% ·  2 detik
    "gemini-flash-lite-latest", # 4,0/5 klip · index  85% ·  3 detik — alias,
                                # satu-satunya yang tidak bisa ikut pensiun
]


#: Nilai GEMINI_MODEL yang dulu ditulis .env.example, jadi ia ada di HAMPIR
#: SEMUA .env yang beredar tanpa satu pun pemiliknya pernah memilihnya.
#: Memperlakukannya sebagai pilihan sadar membuat seluruh sistem tier ini mati
#: sejak lahir — dan matinya senyap, karena satu model itu memang jalan.
BAWAAN_LAMA = "gemini-flash-lite-latest"


def daftar() -> list[str]:
    """Daftar model yang berlaku, urut menurut prioritas.

    GEMINI_MODELS (jamak) menggantikan TIER sepenuhnya — itu pilihan sadar.
    GEMINI_MODEL (tunggal, warisan) hanya DIDAHULUKAN, bukan menggantikan:
    pilihannya dihormati sebagai tier teratas, tapi tier di bawahnya tetap ada
    sebagai cadangan saat kuotanya habis.
    """
    from config.settings import settings

    if settings.gemini_models_kustom and settings.GEMINI_MODELS.strip():
        return settings.gemini_models_kustom

    tunggal = (settings.GEMINI_MODEL or "").strip()
    if tunggal and tunggal != BAWAAN_LAMA:
        return [tunggal] + [m for m in TIER if m != tunggal]
    return TIER

#: Umur tanda "habis". Bukan ramalan kapan kuota pulih — ini jarak antar
#: percobaan ulang. Pendek supaya tier teratas cepat dipakai lagi begitu
#: kuotanya kembali, panjang supaya tidak tiap job membuang panggilan.
UMUR_HABIS = 3600


def _kunci(pool: str, model: str, idx: int) -> str:
    return f"llm:habis:{pool}:{model}:{idx}"


def tandai_habis(pool: str, model: str, idx: int) -> None:
    """Catat bahwa kuota pasangan ini sudah habis.

    Hanya untuk kuota yang benar-benar habis, BUKAN rate limit sesaat. Rate
    limit pulih dalam hitungan detik dan menandainya sejam akan membuang tier
    teratas untuk masalah yang sudah beres sebelum job berikutnya mulai.
    """
    try:
        keypool._redis().setex(_kunci(pool, model, idx), UMUR_HABIS, "1")
        log.info("model %s key #%d ditandai habis selama %ds",
                 model, idx + 1, UMUR_HABIS)
    except Exception as e:  # noqa: BLE001 — status bukan alasan menggagalkan job
        log.debug("gagal menandai habis: %s", e)


def _habis(pool: str, model: str, idx: int) -> bool:
    try:
        return bool(keypool._redis().exists(_kunci(pool, model, idx)))
    except Exception:  # noqa: BLE001
        # Redis tidak terjangkau: anggap semuanya masih layak dicoba. Salah
        # menganggap habis jauh lebih merugikan daripada satu panggilan gagal —
        # yang pertama menurunkan mutu tiap klip diam-diam.
        return False


def urutan(pool: str, models: list[str], jml_key: int) -> list[tuple[str, int]]:
    """Pasangan (model, index key) urut sesuai prioritas.

    Seluruh key untuk tier teratas lebih dulu, baru turun tier — itu inti
    aturannya. Pasangan yang sedang bertanda habis dipindah ke BELAKANG, bukan
    dibuang: kalau ternyata semuanya bertanda habis, job tetap harus punya
    sesuatu untuk dicoba, dan tandanya sendiri cuma dugaan berumur sejam.
    """
    layak, lelah = [], []
    for m in models:
        for i in range(max(1, jml_key)):
            (lelah if _habis(pool, m, i) else layak).append((m, i))
    return layak + lelah


def status(pool: str, models: list[str], jml_key: int) -> dict:
    """Ringkasan untuk halaman Setting: model mana yang sedang dipakai, dan
    kenapa yang di atasnya tidak."""
    baris = []
    for t, m in enumerate(models):
        habis = sum(1 for i in range(max(1, jml_key)) if _habis(pool, m, i))
        baris.append({
            "model": m, "tier": t + 1,
            "habis": habis, "total": max(1, jml_key),
            "siap": habis < max(1, jml_key),
        })
    aktif = next((b["model"] for b in baris if b["siap"]), models[0] if models else "")
    return {"aktif": aktif, "tier": baris, "pada": time.time()}
