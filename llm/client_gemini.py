"""Provider Gemini langsung (bukan lewat OpenRouter), dengan rotasi banyak key.

Gemini menyediakan endpoint OpenAI-compatible, jadi badan request-nya sama
persis dengan OpenRouter dan seluruh logikanya dipakai bersama lewat _engine.

Rotasi key ada karena free tier Gemini dibatasi PER KEY (mis. 15 RPM / 1000 RPD
untuk flash-lite). Beberapa key gratis yang dipakai bergantian menaikkan atap
itu tanpa biaya, dan yang lebih penting: percobaan yang kena 429 otomatis
memakai key berikutnya, bukan mengulang ke key yang sedang habis kuota.
"""
import itertools

from config.settings import settings
from llm._engine import LLMError, call
from utils.logging import get

log = get(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# next() pada itertools.count bersifat atomik di CPython, jadi tidak perlu lock
# hanya untuk menaikkan sebuah penghitung.
_counter = itertools.count()


def _next_key() -> str:
    """Ambil key berikutnya, berputar (x+1) tiap dipanggil."""
    keys = settings.gemini_keys
    if not keys:
        raise LLMError("GEMINI_API_KEYS kosong — isi di .env (format: key1,key2,key3)")
    i = next(_counter) % len(keys)
    # Yang di-log indeksnya, tidak pernah key-nya.
    log.debug("gemini pakai key #%d dari %d", i + 1, len(keys))
    return keys[i]


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    keys = settings.gemini_keys
    if not keys:
        raise LLMError("GEMINI_API_KEYS kosong — isi di .env (format: key1,key2,key3)")

    # Dengan banyak key, sediakan percobaan yang cukup supaya tiap key sempat
    # dicoba saat satu di antaranya kena rate limit. Dibatasi 6 supaya kegagalan
    # yang sebenarnya (JSON ngawur) tidak diulang belasan kali.
    tries = min(max(attempts, len(keys)), 6)

    return call(
        prompt,
        response_schema,
        endpoint=ENDPOINT,
        get_key=_next_key,
        model=settings.GEMINI_MODEL,
        # Layer OpenAI-compatible Gemini belum dipastikan menerima
        # response_format json_schema, jadi dipakai json_object yang aman.
        # Bentuk output tetap terjaga: prompt sudah menyebut tiap field dan
        # stage memvalidasi hasilnya sendiri.
        use_schema=False,
        attempts=tries,
        label="gemini",
    )
