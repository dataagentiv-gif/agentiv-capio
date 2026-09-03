"""Stage 2: transkrip dengan timestamp per kata.

Input  : ctx[audio], ctx[workdir], ctx[deadline], ctx[meta]
Output : words.json     -> [{"i", "w", "s", "e"}]        caption karaoke (Stage 5)
         sentences.json -> [{"text", "s", "e"}]          bahan LLM (Stage 3)

Provider mana yang dipakai ditentukan ASR_PROVIDER di .env; stage ini tidak
tahu-menahu soal Groq maupun ElevenLabs.
"""
import json
import math
from pathlib import Path

import asr
from config.settings import settings
from utils.ffmpeg_helpers import ffmpeg
from utils.logging import get

log = get(__name__)

CHUNK_SEC = 1200.0  # 20 menit


def _chunks(audio: Path, workdir: Path, duration: float, deadline) -> tuple[list, list]:
    """Cabang untuk audio melebihi batas provider.

    Pada Groq (25MB, opus 24kbps) ini baru kena di ~2.3 jam audio; pada Scribe
    (3GB) praktis tidak pernah. Karena itu sengaja dibiarkan sederhana: potong
    tepat 20 menit tanpa menyesuaikan ke jeda bicara. Satu kata terpotong di
    batas chunk tiap 20 menit tidak mengubah hasil seleksi momen.
    """
    words: list[dict] = []
    sentences: list[dict] = []
    n = math.ceil(duration / CHUNK_SEC)
    log.info("audio melebihi batas provider, dipecah jadi %d chunk", n)
    for i in range(n):
        off = i * CHUNK_SEC
        part = workdir / f"chunk{i}.ogg"
        ffmpeg(
            [
                # Nama diambil dari argumen, bukan ditulis literal: cabang ini
                # cuma hidup pada audio >2,3 jam, jadi kaitan diam-diam ke satu
                # nama file akan rusak tanpa ketahuan sampai ada yang benar-benar
                # memproses podcast panjang.
                "-ss", f"{off:.3f}", "-i", audio.name,
                "-t", f"{min(CHUNK_SEC, duration - off):.3f}",
                "-c:a", "libopus", "-b:a", "24k", "-ac", "1", "-ar", "16000",
                part.name,
            ],
            deadline,
            cwd=workdir,
            cap=300,
        )
        w, s = asr.transcribe(part, off)
        words += w
        sentences += s
        part.unlink(missing_ok=True)
    return words, sentences


def run(ctx: dict) -> dict:
    audio: Path = ctx["audio"]
    workdir: Path = ctx["workdir"]
    duration = float(ctx["meta"]["duration"])

    # Diperiksa di luar pemanggilan ber-retry: key kosong adalah salah
    # konfigurasi, bukan kegagalan sementara, dan me-retry-nya hanya menunda
    # pesan error yang sudah pasti.
    asr.check_config()

    if audio.stat().st_size <= asr.size_limit():
        words, sentences = asr.transcribe(audio, 0.0)
    else:
        words, sentences = _chunks(audio, workdir, duration, ctx["deadline"])

    if not words:
        raise RuntimeError("Transkrip kosong — audio kemungkinan tanpa suara")

    # Re-index setelah semua chunk digabung; `i` inilah yang dipakai LLM di
    # Stage 3 untuk menunjuk batas segmen.
    words.sort(key=lambda w: w["s"])
    words = [
        {"i": i, "w": w["w"], "s": w["s"], "e": w["e"]} for i, w in enumerate(words)
    ]
    sentences.sort(key=lambda s: s["s"])

    (workdir / "words.json").write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8"
    )
    (workdir / "sentences.json").write_text(
        json.dumps(sentences, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(
        "transkrip [%s]: %d kata, %d kalimat, %.0f detik",
        settings.ASR_PROVIDER, len(words), len(sentences), words[-1]["e"],
    )
    return {"words": words, "sentences": sentences}
