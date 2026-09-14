"""Transkrip lewat Gemini (asr/client_gemini.py).

Modul ini tetap ada sebagai titik masuk stabil untuk worker dan Stage 2 —
keduanya memanggil `asr.check_config()` / `asr.transcribe()` tanpa tahu
implementasinya. ASR_PROVIDER yang masih tertulis di .env lama (elevenlabs,
groq) diabaikan tanpa error — config/settings.py memakai extra="ignore".

Kontrak yang dijamin:
    transcribe(path, offset) -> (words, sentences)
    words     : [{"w", "s", "e"}]      dipakai caption karaoke (Stage 5)
    sentences : [{"text", "s", "e"}]   bertanda baca, dipakai LLM (Stage 3)
"""
import re
import unicodedata
from pathlib import Path

from asr import angka
from utils.logging import get

log = get(__name__)


def rasio_non_latin(teks: str) -> float:
    """Persen huruf yang bukan aksara Latin.

    Dihitung dari HURUF saja, bukan seluruh karakter: angka, spasi, dan tanda
    baca sama di semua bahasa dan cuma mengencerkan angkanya. Tanda paling
    jelas bahwa model berhenti mentranskrip lalu mengarang — pernah menulis
    teks Jepang (Groq, sudah dibuang), pernah menulis aksara Gujarat di atas
    efek suara (Gemini, ditolak _sah() di client_gemini.py).
    """
    huruf = [c for c in teks if c.isalpha()]
    if not huruf:
        return 0.0
    asing = sum(1 for c in huruf if "LATIN" not in unicodedata.name(c, ""))
    return asing / len(huruf) * 100


# --- kalimat dari kata ---
#
# Gemini Transcribe tidak mengembalikan pembagian kalimat sama sekali — cuma
# kata dan timestamp-nya. Padahal Stage 3 memakai kalimat bertanda baca untuk
# menentukan titik potong, jadi kalimatnya diturunkan di sini. Kalau penurunan
# ini rusak, tidak ada yang error: seluruh transkrip jadi satu kalimat raksasa
# dan Stage 3 diam-diam kehilangan semua titik potongnya.

# Akhir kalimat, termasuk yang diikuti kutip atau kurung penutup.
_END = re.compile(r"[.!?…]+[\"'\)\]]*$")
# Ambang cadangan saat transkrip sama sekali tanpa tanda baca.
_PAUSE_SPLIT = 0.6


def _pack(group: list[dict]) -> dict:
    return {
        "text": " ".join(w["w"] for w in group).strip(),
        "s": group[0]["s"],
        "e": group[-1]["e"],
    }


def sentences_from_words(words: list[dict]) -> list[dict]:
    """Turunkan kalimat dari daftar kata.

    Pemisahnya tanda baca akhir kalimat. Kalau transkrip ternyata tidak
    mengandung tanda baca sama sekali, dipakai jeda bicara sebagai pengganti —
    tanpa cadangan itu seluruh transkrip jadi satu kalimat raksasa.
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


def _impl():
    from asr import client_gemini as m

    return m


def check_config() -> None:
    """Dipanggil saat worker start supaya key yang bolong ketahuan di detik
    pertama, bukan setelah video selesai diunduh."""
    _impl().check_config()


def size_limit() -> int:
    """Batas ukuran file sebelum audio perlu dipecah."""
    return _impl().SIZE_LIMIT


def duration_limit() -> float:
    """Batas durasi satu request; tak hingga kalau provider tidak membatasi."""
    return getattr(_impl(), "MAX_DURATION_SEC", float("inf"))


def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    """Transkrip, lalu angka yang dieja diubah jadi digit.

    Normalisasi dilakukan di sini, bukan di client, karena ini kebutuhan
    CAPTION: siapa pun yang mengeja angka menghasilkan caption yang pecah dua
    tampilan. Pada transkrip yang sudah memakai digit, langkah ini tidak
    mengubah apa pun.

    Kalimat dibentuk ulang dari kata hasil normalisasi supaya teks yang dibaca
    LLM di Stage 3 sama dengan yang tampil di caption — kalau dibiarkan
    berbeda, index kata yang ditunjuk LLM tidak lagi menunjuk kata yang sama.
    """
    words, sentences = _impl().transcribe(path, offset)
    rapi = angka.normalkan(words)
    if len(rapi) != len(words):
        sentences = sentences_from_words(rapi)
    return rapi, sentences


__all__ = ["check_config", "duration_limit", "rasio_non_latin",
           "sentences_from_words", "size_limit", "transcribe"]
