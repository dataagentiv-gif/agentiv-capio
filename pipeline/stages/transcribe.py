"""Stage 2: transkrip Groq Whisper dengan timestamp per kata.

Input  : ctx[audio], ctx[workdir], ctx[deadline]
Output : words.json -> [{"i": 0, "w": "jadi", "s": 12.34, "e": 12.51}]
"""
import json
import math
from pathlib import Path

from config.settings import settings
from utils.ffmpeg_helpers import ffmpeg
from utils.logging import get
from utils.retry import retry

log = get(__name__)

MODEL = "whisper-large-v3-turbo"
# Limit Groq free tier 25MB; disisakan margin supaya tidak mepet.
SIZE_LIMIT = 24 * 1024 * 1024
CHUNK_SEC = 1200.0  # 20 menit


def _client():
    from groq import Groq

    return Groq(api_key=settings.GROQ_API_KEY)


@retry(attempts=3, backoff=5.0)
def _transcribe_file(path: Path, offset: float) -> list[dict]:
    """Satu panggilan Groq. Kembalikan list kata dengan timestamp absolut."""
    with open(path, "rb") as f:
        resp = _client().audio.transcriptions.create(
            file=(path.name, f.read()),
            model=MODEL,
            response_format="verbose_json",
            # Tanpa timestamp_granularities word, yang balik cuma level segmen
            # dan caption karaoke per kata mustahil dibuat.
            timestamp_granularities=["word", "segment"],
        )
    data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    return [
        {"w": w["word"].strip(), "s": w["start"] + offset, "e": w["end"] + offset}
        for w in (data.get("words") or [])
        if w.get("word", "").strip()
    ]


def _chunks(audio: Path, workdir: Path, duration: float, deadline) -> list[dict]:
    """Cabang untuk audio > limit. Pada 24kbps ini baru kena di ~2.3 jam audio,
    jadi sengaja dibiarkan sederhana: potong tepat 20 menit tanpa snap ke silence.
    Satu kata terpotong di batas chunk tiap 20 menit tidak mengubah hasil seleksi.
    """
    words: list[dict] = []
    n = math.ceil(duration / CHUNK_SEC)
    log.info("audio > %d MB, dipecah jadi %d chunk", SIZE_LIMIT // 1_000_000, n)
    for i in range(n):
        off = i * CHUNK_SEC
        part = workdir / f"chunk{i}.ogg"
        ffmpeg(
            [
                "-ss", f"{off:.3f}", "-i", "audio.ogg",
                "-t", f"{min(CHUNK_SEC, duration - off):.3f}",
                "-c:a", "libopus", "-b:a", "24k", "-ac", "1", "-ar", "16000",
                part.name,
            ],
            deadline,
            cwd=workdir,
            cap=300,
        )
        words += _transcribe_file(part, off)
        part.unlink(missing_ok=True)
    return words


def run(ctx: dict) -> dict:
    audio: Path = ctx["audio"]
    workdir: Path = ctx["workdir"]
    deadline = ctx["deadline"]
    duration = float(ctx["meta"]["duration"])

    # Diperiksa di luar _transcribe_file: key yang kosong adalah salah
    # konfigurasi, bukan kegagalan sementara, dan me-retry-nya 3x dengan backoff
    # hanya menunda pesan error yang sudah pasti.
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY kosong — isi di .env")

    if audio.stat().st_size <= SIZE_LIMIT:
        words = _transcribe_file(audio, 0.0)
    else:
        words = _chunks(audio, workdir, duration, deadline)

    if not words:
        raise RuntimeError("Transkrip kosong — audio kemungkinan tanpa suara")

    # Re-index setelah semua chunk digabung; `i` inilah yang dipakai LLM di
    # Stage 3 untuk menunjuk batas segmen.
    words.sort(key=lambda w: w["s"])
    for i, w in enumerate(words):
        w["i"] = i
    words = [{"i": w["i"], "w": w["w"], "s": w["s"], "e": w["e"]} for w in words]

    (workdir / "words.json").write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8"
    )
    log.info("transkrip: %d kata, %.0f detik", len(words), words[-1]["e"])
    return {"words": words}
