"""Pemilih provider transkrip.

Stage 2 memanggil dari sini dan tidak tahu provider mana yang aktif — ganti
provider cukup ubah ASR_PROVIDER di .env, kode stage tidak disentuh.

Kontrak yang dijamin sama untuk semua provider:
    transcribe(path, offset) -> (words, sentences)
    words     : [{"w", "s", "e"}]      dipakai caption karaoke (Stage 5)
    sentences : [{"text", "s", "e"}]   bertanda baca, dipakai LLM (Stage 3)
"""
from pathlib import Path

from asr import angka
from config.settings import settings

PROVIDERS = ("groq", "elevenlabs")


def _impl():
    name = settings.ASR_PROVIDER.strip().lower()
    if name == "groq":
        from asr import client_groq as m
    elif name == "elevenlabs":
        from asr import client_elevenlabs as m
    else:
        raise RuntimeError(
            f"ASR_PROVIDER='{settings.ASR_PROVIDER}' tidak dikenal. "
            f"Pilihan: {', '.join(PROVIDERS)}"
        )
    return m


def check_config() -> None:
    """Dipanggil saat worker start supaya key yang bolong ketahuan di detik
    pertama, bukan setelah video selesai diunduh."""
    _impl().check_config()


def size_limit() -> int:
    """Batas ukuran file sebelum audio perlu dipecah. Beda jauh antar provider:
    Groq 25MB, Scribe 3GB."""
    return _impl().SIZE_LIMIT


def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    """Transkrip, lalu angka yang dieja diubah jadi digit.

    Normalisasi dilakukan di sini, bukan di masing-masing client, karena ini
    kebutuhan CAPTION dan bukan sifat provider: siapa pun yang mengeja angka
    menghasilkan caption yang pecah dua tampilan. Pada transkrip yang sudah
    memakai digit, langkah ini tidak mengubah apa pun.

    Kalimat dibentuk ulang dari kata hasil normalisasi supaya teks yang dibaca
    LLM di Stage 3 sama dengan yang tampil di caption — kalau dibiarkan
    berbeda, index kata yang ditunjuk LLM tidak lagi menunjuk kata yang sama.
    """
    words, sentences = _impl().transcribe(path, offset)
    rapi = angka.normalkan(words)
    if len(rapi) != len(words):
        from asr.client_elevenlabs import sentences_from_words

        sentences = sentences_from_words(rapi)
    return rapi, sentences


__all__ = ["PROVIDERS", "check_config", "size_limit", "transcribe"]
