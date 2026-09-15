"""Tes koneksi per provider untuk halaman Settings.

Key yang salah adalah penyebab kegagalan paling sering pada orang yang baru
memasang project ini, dan tanpa tombol tes kesalahannya baru muncul belasan
menit kemudian sebagai job gagal di tengah pipeline.

Tiap probe dibuat semurah mungkin: daftar model atau satu permintaan kecil,
bukan transkrip atau upload sungguhan.
"""
import httpx

import keypool
from llm import rute
from utils.logging import get

log = get(__name__)
TIMEOUT = 25.0


# Penjelasan khusus provider untuk kode yang artinya tidak lazim.
KHUSUS = {
    ("gemini-transcribe", 404): (
        "Model Gemini Transcribe tidak tersedia untuk key ini (404)."
    ),
}


def _per_key(pool: str, kirim, nama_pesan: str | None = None) -> tuple[bool, str]:
    """Uji TIAP key satu per satu, bukan cuma yang pertama.

    Satu key mati di antara beberapa key harus ketahuan, bukan tertutup oleh
    key lain yang kebetulan jalan — itu justru kegagalan yang paling
    membingungkan nanti: sebagian job jalan, sebagian tidak, tanpa pola.

    Hasilnya sekalian dicatat ke keypool supaya lampu status di halaman Setting
    ikut segar tanpa harus menunggu job berikutnya berjalan.
    """
    keys = keypool.keys(pool)
    if not keys:
        return False, "Key belum diisi"
    hasil = []
    for i, k in enumerate(keys):
        r = kirim(k)
        ok_i = r.status_code == 200
        pesan = _pesan(nama_pesan or pool, r.status_code, r.text)
        keypool.lapor(pool, i, ok_i, pesan)
        hasil.append(f"#{i + 1} {'OK' if ok_i else pesan}")
    return all("OK" in h for h in hasil), f"{len(keys)} key: " + ", ".join(hasil)


def _pesan(pool: str, code: int, badan: str) -> str:
    if code == 200:
        return "Terhubung"
    if (pool, code) in KHUSUS:
        return KHUSUS[(pool, code)]
    # 404 di sini hampir selalu soal NAMA MODEL, bukan key — dan itu perbedaan
    # yang mahal. Tanpa dibedakan, orangnya akan menghapus key yang baik-baik
    # saja lalu membuat key baru berkali-kali, sementara yang perlu diganti cuma
    # satu baris di kolom Model. Google memensiunkan nama model berversi untuk
    # akun baru sementara akun lama tetap bisa memakainya, jadi setelan yang
    # diwarisi dari mesin lain bisa mati di mesin ini saja.
    if code == 404:
        return ("Model tidak ditemukan (404) — key-nya kemungkinan besar tidak "
                "apa-apa, yang salah nama modelnya. Pakai nama beralias yang "
                "berakhiran -latest supaya tidak ikut pensiun.")
    if code == 429:
        # Dua hal yang sangat berbeda memakai kode yang sama. "plan and billing"
        # berarti model itu memang TIDAK punya jatah gratis sama sekali —
        # menunggu tidak akan menolong, modelnya yang harus diganti.
        if "billing" in badan.lower() or "plan" in badan.lower():
            return ("Model ini tidak punya jatah gratis (429). Menunggu tidak "
                    "menolong — pilih model kelas flash, atau aktifkan billing.")
        return "Kuota habis (429)"
    if code in (401, 403):
        return f"Key ditolak ({code})"
    return f"HTTP {code}: {badan[:100]}"


PROBES = {
    # Tes ASR Gemini harus memeriksa model transkrip, bukan model chat yang
    # kebetulan memakai key sama. Ketersediaan model bisa berbeda per project.
    "gemini-transcribe": lambda: _per_key(
        "gemini",
        lambda k: httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.5-transcribe",
            headers={"x-goog-api-key": k}, timeout=TIMEOUT,
        ),
        "gemini-transcribe",
    ),

    # Gemini diuji dengan panggilan chat sungguhan, bukan sekadar daftar model:
    # ketersediaan MODEL berbeda per key (Google menutup model lama untuk
    # project baru), dan itu tidak terlihat dari endpoint mana pun selain
    # mencoba memanggilnya.
    "gemini": lambda: _per_key("gemini", lambda k: httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        headers={"Authorization": f"Bearer {k}"},
        # Model yang BENAR-BENAR dipakai job, bukan kolom satuan yang lama.
        # Menguji nama lain dari yang dipakai membuat tombol ini berbohong
        # persis di kasus yang paling ingin ditangkapnya: nama model yang mati.
        json={"model": rute.daftar()[0],
              "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
        timeout=TIMEOUT)),
}


def run(provider: str) -> dict:
    probe = PROBES.get(provider)
    if probe is None:
        return {"ok": False, "message": f"Provider '{provider}' tidak dikenal"}
    try:
        ok, message = probe()
    except Exception as e:  # noqa: BLE001 — tes koneksi tidak boleh menjatuhkan API
        log.warning("tes %s gagal: %s", provider, e)
        ok, message = False, f"{type(e).__name__}: {e}"[:200]
    return {"ok": ok, "message": message}
