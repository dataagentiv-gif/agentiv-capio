"""Provider Groq Whisper.

Kelebihannya kecepatan dan harga ($0.04/jam, transkrip 1 jam audio ~15 detik),
dan `segments` bawaannya sudah bertanda baca sehingga kalimat tidak perlu
diturunkan sendiri.

Kekurangan yang sudah terbukti di pemakaian: meleset pada campuran
Indonesia-Inggris, dan menolak IP datacenter dengan 403 — yang berarti bakal
jadi masalah kalau worker ini nanti dijalankan di VPS.
"""
from pathlib import Path

from config.settings import settings
from utils.retry import retry

MODEL = "whisper-large-v3-turbo"
# Limit free tier Groq 25MB; disisakan margin supaya tidak mepet. Pada opus
# 24kbps ini baru tersentuh di sekitar 2.3 jam audio.
SIZE_LIMIT = 24 * 1024 * 1024


def _client():
    from groq import Groq

    return Groq(api_key=settings.GROQ_API_KEY)


def check_config() -> None:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY kosong — isi di .env")


@retry(attempts=3, backoff=5.0)
def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    with open(path, "rb") as f:
        resp = _client().audio.transcriptions.create(
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
    return words, sentences
