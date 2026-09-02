"""Provider Groq Whisper.

Kelebihannya kecepatan dan harga ($0.04/jam, transkrip 1 jam audio ~15 detik),
dan `segments` bawaannya sudah bertanda baca sehingga kalimat tidak perlu
diturunkan sendiri.

Kekurangan yang sudah terbukti di pemakaian: meleset pada campuran
Indonesia-Inggris, dan menolak IP datacenter dengan 403 — yang berarti bakal
jadi masalah kalau worker ini nanti dijalankan di VPS.
"""
from pathlib import Path

import keypool
from config.settings import settings
from utils.retry import retry

MODEL = "whisper-large-v3-turbo"
# Limit free tier Groq 25MB; disisakan margin supaya tidak mepet. Pada opus
# 24kbps ini baru tersentuh di sekitar 2.3 jam audio.
SIZE_LIMIT = 24 * 1024 * 1024


def check_config() -> None:
    if not settings.groq_keys:
        raise RuntimeError("Groq API key kosong — isi di halaman Setting")


@retry(attempts=3, backoff=5.0)
def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    from groq import Groq

    # Key diambil ulang di TIAP percobaan, bukan sekali di awal: percobaan yang
    # gagal karena kena batas kuota otomatis memakai key berikutnya, bukan
    # mengulang ke key yang sedang habis.
    idx, key = keypool.ambil("groq")
    try:
        return _panggil(Groq(api_key=key), path, offset, idx)
    except Exception as e:
        keypool.lapor("groq", idx, False, f"{type(e).__name__}: {e}")
        raise


def _panggil(klien, path: Path, offset: float, idx: int) -> tuple[list[dict], list[dict]]:
    with open(path, "rb") as f:
        resp = klien.audio.transcriptions.create(
            file=(path.name, f.read()),
            model=MODEL,
            response_format="verbose_json",
            # Tanpa granularity word, yang balik cuma level segmen dan caption
            # karaoke per kata mustahil dibuat.
            timestamp_granularities=["word", "segment"],
        )
    data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    words = [
        {"w": w["word"].strip(), "s": w["start"] + offset, "e": w["end"] + offset}
        for w in (data.get("words") or [])
        if w.get("word", "").strip()
    ]
    sentences = [
        {"text": s["text"].strip(), "s": s["start"] + offset, "e": s["end"] + offset}
        for s in (data.get("segments") or [])
        if s.get("text", "").strip()
    ]
    keypool.lapor("groq", idx, True, f"{len(words)} kata")
    return words, sentences
