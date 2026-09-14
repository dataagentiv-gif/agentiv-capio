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
from utils.logging import get

log = get(__name__)

PROVIDERS = ("elevenlabs",)


def nama() -> str:
    """Provider yang BENAR-BENAR dipakai.

    Nilai yang tidak dikenal jatuh ke provider yang ada, bukan ditolak. Groq
    sudah dibuang, tapi .env milik client yang update lewat `docker compose
    pull` masih bisa berisi ASR_PROVIDER=groq. Menolak membuat check_config
    worker melempar saat start, dan `restart: unless-stopped` mengulanginya
    selamanya — padahal provider yang tersisa jalan normal.
    """
    n = settings.ASR_PROVIDER.strip().lower()
    return n if n in PROVIDERS else PROVIDERS[0]


def _impl():
    # Diperingatkan di sini, bukan di nama(): nama() ikut dipanggil strip
    # status yang di-polling halaman, dan log-nya akan banjir.
    if nama() != settings.ASR_PROVIDER.strip().lower():
        log.warning("ASR_PROVIDER='%s' tidak dikenal — memakai %s",
                    settings.ASR_PROVIDER, nama())
    from asr import client_elevenlabs as m
    return m


def check_config() -> None:
    """Dipanggil saat worker start supaya key yang bolong ketahuan di detik
    pertama, bukan setelah video selesai diunduh."""
    _impl().check_config()


def size_limit() -> int:
    """Batas ukuran file sebelum audio perlu dipecah. Tiap provider punya
    batasnya sendiri (Scribe 3GB)."""
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


__all__ = ["PROVIDERS", "check_config", "nama", "size_limit", "transcribe"]
