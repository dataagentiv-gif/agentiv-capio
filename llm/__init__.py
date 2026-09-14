"""Pintu masuk LLM. Stage memanggil `call_llm` dari sini.

Providernya cuma Gemini sejak OpenRouter dibuang. LLM_PROVIDER yang masih
tertulis di .env lama diabaikan (config/settings.py memakai extra="ignore"),
jadi tidak ada .env yang perlu disunting setelah update.
"""
from llm._engine import LLMError


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    # Import di dalam fungsi supaya tidak ada import melingkar dengan _engine.
    from llm.client_gemini import call_llm as impl

    return impl(prompt, response_schema, attempts)


__all__ = ["LLMError", "call_llm"]
