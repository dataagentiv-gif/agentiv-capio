"""Provider Gemini langsung (bukan lewat OpenRouter), dengan rotasi banyak key.

Gemini menyediakan endpoint OpenAI-compatible, jadi badan request-nya sama
persis dengan OpenRouter dan seluruh logikanya dipakai bersama lewat _engine.

Rotasi key ada karena free tier Gemini dibatasi PER KEY (mis. 15 RPM / 1000 RPD
untuk flash-lite). Beberapa key gratis yang dipakai bergantian menaikkan atap
itu tanpa biaya, dan yang lebih penting: percobaan yang kena 429 otomatis
memakai key berikutnya, bukan mengulang ke key yang sedang habis kuota.
"""
import keypool
from config.settings import settings
from llm._engine import LLMError, call
from utils.logging import get

log = get(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

class _Pemakai:
    """Menyimpan indeks key yang terakhir diambil, supaya hasil panggilan bisa
    dilaporkan ke keypool tanpa mengubah tanda tangan get_key milik _engine.

    Satu instance per panggilan call_llm, jadi tidak ada state yang menetap
    antar panggilan maupun antar thread.
    """

    def __init__(self):
        self.idx = -1

    def __call__(self) -> str:
        if not settings.gemini_keys:
            raise LLMError("Gemini API key kosong — isi di halaman Setting")
        self.idx, key = keypool.ambil("gemini")
        # Yang di-log indeksnya, tidak pernah key-nya.
        log.debug("gemini pakai key #%d dari %d", self.idx + 1, len(settings.gemini_keys))
        return key


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    keys = settings.gemini_keys
    if not keys:
        raise LLMError("Gemini API key kosong — isi di halaman Setting")

    # Dengan banyak key, sediakan percobaan yang cukup supaya tiap key sempat
    # dicoba saat satu di antaranya kena rate limit. Dibatasi 6 supaya kegagalan
    # yang sebenarnya (JSON ngawur) tidak diulang belasan kali.
    tries = min(max(attempts, len(keys)), 6)

    pemakai = _Pemakai()
    try:
        hasil = call(
            prompt,
            response_schema,
            endpoint=ENDPOINT,
            get_key=pemakai,
            model=settings.GEMINI_MODEL,
            # Layer OpenAI-compatible Gemini belum dipastikan menerima
            # response_format json_schema, jadi dipakai json_object yang aman.
            # Bentuk output tetap terjaga: prompt sudah menyebut tiap field dan
            # stage memvalidasi hasilnya sendiri.
            use_schema=False,
            attempts=tries,
            label="gemini",
        )
    except Exception as e:
        if pemakai.idx >= 0:
            keypool.lapor("gemini", pemakai.idx, False, f"{type(e).__name__}: {e}")
        raise
    if pemakai.idx >= 0:
        keypool.lapor("gemini", pemakai.idx, True, "OK")
    return hasil
