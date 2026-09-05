"""Provider OpenRouter, dengan rotasi banyak key.

Rotasi bekerja sama seperti pada Gemini dan Groq: key diambil bergantian, dan
percobaan yang kena batas kuota otomatis memakai key berikutnya alih-alih
mengulang ke key yang sedang habis. Seluruh logikanya ada di _engine.call_pool.
"""
from config.settings import settings
from llm._engine import call_pool

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    return call_pool(
        prompt,
        response_schema,
        pool="openrouter",
        nama="OpenRouter",
        endpoint=ENDPOINT,
        models=[settings.OPENROUTER_MODEL],
        # OpenRouter meneruskan response_format json_schema ke provider di
        # belakangnya, dan ini sudah jalur yang dipakai sejak awal.
        use_schema=True,
        attempts=attempts,
    )
