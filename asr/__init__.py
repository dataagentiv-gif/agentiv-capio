"""Pemilih provider transkrip.

Stage 2 memanggil dari sini dan tidak tahu provider mana yang aktif — ganti
provider cukup ubah ASR_PROVIDER di .env, kode stage tidak disentuh.

Kontrak yang dijamin sama untuk semua provider:
    transcribe(path, offset) -> (words, sentences)
    words     : [{"w", "s", "e"}]      dipakai caption karaoke (Stage 5)
    sentences : [{"text", "s", "e"}]   bertanda baca, dipakai LLM (Stage 3)
"""
from pathlib import Path

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
    return _impl().transcribe(path, offset)


__all__ = ["PROVIDERS", "check_config", "size_limit", "transcribe"]
