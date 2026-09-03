"""Provider Gemini langsung (bukan lewat OpenRouter), dengan rotasi banyak key.

Gemini menyediakan endpoint OpenAI-compatible, jadi badan request-nya sama
persis dengan OpenRouter dan seluruh logikanya dipakai bersama lewat _engine.

Rotasi key ada karena free tier Gemini dibatasi PER KEY (mis. 15 RPM / 1000 RPD
untuk flash-lite). Beberapa key gratis yang dipakai bergantian menaikkan atap
itu tanpa biaya, dan yang lebih penting: percobaan yang kena 429 otomatis
memakai key berikutnya, bukan mengulang ke key yang sedang habis kuota.
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
        model=settings.GEMINI_MODEL,
        # Layer OpenAI-compatible Gemini belum dipastikan menerima
        # response_format json_schema, jadi dipakai json_object yang aman.
        # Bentuk output tetap terjaga: prompt sudah menyebut tiap field dan
        # stage memvalidasi hasilnya sendiri.
        use_schema=False,
        attempts=attempts,
    )
