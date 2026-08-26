"""Provider ElevenLabs Scribe.

Jauh lebih akurat untuk Bahasa Indonesia (~2.4% WER vs ~7.7% milik Whisper) dan
tidak memblokir IP datacenter. Lebih mahal ($0.22/jam vs $0.04), tapi caption di
produk ini dibakar ke dalam video — kesalahan transkrip terlihat penonton, jadi
selisih harganya kecil dibanding harga kesalahannya.

Limitnya 3GB / 10 jam, jadi cabang chunking praktis tidak pernah terpakai.
"""
import re
from pathlib import Path

import httpx

from config.settings import settings
from utils.logging import get
from utils.retry import retry

log = get(__name__)

ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
# Praktis tanpa batas untuk kebutuhan kita (limit asli 3GB), jadi audio tidak
# pernah dipecah seperti pada Groq.
SIZE_LIMIT = 2 * 1024 * 1024 * 1024

# Akhir kalimat, termasuk yang diikuti kutip atau kurung penutup.
_END = re.compile(r"[.!?…]+[\"'\)\]]*$")
# Ambang cadangan saat transkrip sama sekali tanpa tanda baca.
_PAUSE_SPLIT = 0.6


def check_config() -> None:
    if not settings.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY kosong — isi di .env")


def _pack(group: list[dict]) -> dict:
    return {
        "text": " ".join(w["w"] for w in group).strip(),
        "s": group[0]["s"],
        "e": group[-1]["e"],
    }


def sentences_from_words(words: list[dict]) -> list[dict]:
    """Turunkan kalimat dari daftar kata.

    Scribe tidak mengembalikan pembagian kalimat sama sekali — cuma kata dan
    satu blok teks utuh. Padahal Stage 3 membutuhkan kalimat bertanda baca
    untuk menentukan titik potong, jadi kalimatnya dibentuk di sini.

    Pemisahnya tanda baca akhir kalimat. Kalau transkrip ternyata tidak
    mengandung tanda baca sama sekali, dipakai jeda bicara sebagai pengganti —
    tanpa cadangan itu seluruh transkrip jadi satu kalimat raksasa dan Stage 3
    kehilangan semua titik potongnya.
    """
    if not words:
        return []

    out: list[dict] = []
    cur: list[dict] = []
    ada_tanda_baca = False
    for w in words:
        cur.append(w)
        if _END.search(w["w"]):
            ada_tanda_baca = True
            out.append(_pack(cur))
            cur = []
    if cur:
        out.append(_pack(cur))

    # Syaratnya ADANYA tanda baca, bukan banyaknya kalimat. Memakai jumlah
    # kalimat membuat transkrip pendek yang memang cuma satu kalimat — dan
    # tanda bacanya benar — ikut dipecah paksa oleh jeda.
    if ada_tanda_baca:
        return out

    log.warning("transkrip tanpa tanda baca — kalimat dipecah berdasarkan jeda")
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else None
        if gap is None or gap >= _PAUSE_SPLIT:
            out.append(_pack(cur))
            cur = []
    return out


@retry(attempts=3, backoff=5.0)
def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    with open(path, "rb") as f:
        r = httpx.post(
            ENDPOINT,
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            files={"file": (path.name, f.read(), "audio/ogg")},
            data={
                "model_id": settings.ELEVENLABS_MODEL,
                "timestamps_granularity": "word",
                # Diarisasi dimatikan: kita tidak memakai speaker_id, dan
                # menyalakannya menambah latensi tanpa manfaat.
                "diarize": "false",
            },
            timeout=900.0,
        )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    words = [
        {"w": w["text"].strip(), "s": w["start"] + offset, "e": w["end"] + offset}
        # `type` bisa word / spacing / audio_event. Yang bukan `word` bukan
        # ucapan, jadi tidak boleh masuk caption.
        for w in (data.get("words") or [])
        if w.get("type") == "word" and w.get("text", "").strip()
    ]
    return words, sentences_from_words(words)
