"""Pemilih provider LLM.

Stage memanggil `call_llm` dari sini dan tidak tahu provider mana yang aktif —
ganti provider cukup ubah LLM_PROVIDER di .env, kode stage tidak disentuh.
"""
from config.settings import settings
from llm._engine import LLMError

PROVIDERS = ("openrouter", "gemini")


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    name = settings.LLM_PROVIDER.strip().lower()
    # Import di dalam fungsi supaya modul provider yang tidak dipakai tidak ikut
    # dimuat, dan supaya tidak ada import melingkar dengan _engine.
    if name == "gemini":
        from llm.client_gemini import call_llm as impl
    elif name == "openrouter":
        from llm.client_openrouter import call_llm as impl
    else:
        raise LLMError(
            f"LLM_PROVIDER='{settings.LLM_PROVIDER}' tidak dikenal. "
            f"Pilihan: {', '.join(PROVIDERS)}"
        )
    return impl(prompt, response_schema, attempts)


__all__ = ["LLMError", "PROVIDERS", "call_llm"]
