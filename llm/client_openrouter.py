"""Provider OpenRouter. Satu key, model diambil dari OPENROUTER_MODEL."""
from config.settings import settings
from llm._engine import LLMError, call

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    if not settings.OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY kosong — isi di .env")
    return call(
        prompt,
        response_schema,
        endpoint=ENDPOINT,
        get_key=lambda: settings.OPENROUTER_API_KEY,
        model=settings.OPENROUTER_MODEL,
        # OpenRouter meneruskan response_format json_schema ke provider di
        # belakangnya, dan ini sudah jalur yang dipakai sejak awal.
        use_schema=True,
        attempts=attempts,
        label="openrouter",
    )
