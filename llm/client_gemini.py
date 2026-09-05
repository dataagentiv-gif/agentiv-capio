"""Provider Gemini langsung (bukan lewat OpenRouter), dengan rotasi banyak key.

Gemini menyediakan endpoint OpenAI-compatible, jadi badan request-nya sama
persis dengan OpenRouter dan seluruh logikanya dipakai bersama lewat _engine.

Rotasi ada di DUA sumbu, karena kuota gratis Gemini dihitung per key DAN per
model. Yang kedua terbukti sendiri: kuota yang habis pulih seketika hanya
dengan berpindah model, tanpa menunggu reset harian. Jadi 3 key x 3 model
memberi sembilan jatah yang berdiri sendiri, dan percobaan yang kena 429 atau
503 otomatis memakai pasangan berikutnya alih-alih mengulang ke yang sedang
habis atau sedang penuh.
"""
from config.settings import settings
from llm._engine import call_pool

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    return call_pool(
        prompt,
        response_schema,
        pool="gemini",
        nama="Gemini",
        endpoint=ENDPOINT,
        models=settings.gemini_models,
        # Layer OpenAI-compatible Gemini belum dipastikan menerima
        # response_format json_schema, jadi dipakai json_object yang aman.
        # Bentuk output tetap terjaga: prompt sudah menyebut tiap field dan
        # stage memvalidasi hasilnya sendiri.
        use_schema=False,
        attempts=attempts,
    )
