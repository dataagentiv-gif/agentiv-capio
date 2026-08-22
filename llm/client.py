"""Adapter OpenRouter (endpoint OpenAI-compatible).

Stage 3 (segment) dan Stage 8 (metadata) sama-sama lewat sini, jadi ganti model
cukup ubah OPENROUTER_MODEL di .env — kode stage tidak disentuh.
"""
import json
import re

import httpx

from config.settings import settings

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class LLMError(RuntimeError):
    pass


def _extract_json(text: str):
    """Model kadang membungkus JSON dalam code fence walau diminta raw."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: ambil blok kurung terluar. Menangani kasus model menambah
        # kalimat pengantar sebelum JSON-nya.
        for open_c, close_c in (("[", "]"), ("{", "}")):
            i, j = cleaned.find(open_c), cleaned.rfind(close_c)
            if i != -1 and j > i:
                return json.loads(cleaned[i : j + 1])
        raise


def call_llm(prompt: str, response_schema: dict | None = None, attempts: int = 3):
    """Panggil LLM, kembalikan hasil yang sudah di-parse jadi objek Python.

    Retry 2x (total 3 percobaan). Pesan error parsing disuntikkan balik ke prompt
    sebagai feedback, sesuai PRD Bagian 3 — sekadar mengulang prompt yang sama
    biasanya menghasilkan kesalahan yang sama.
    """
    if not settings.OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY kosong")

    body = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    if response_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": response_schema,
            },
        }

    last_err, last_raw = "", ""
    for attempt in range(attempts):
        if last_err:
            body["messages"] = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        f"Output di atas ditolak parser: {last_err}\n"
                        "Balas ULANG dengan JSON valid saja, tanpa penjelasan, "
                        "tanpa code fence."
                    ),
                },
            ]
        try:
            r = httpx.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                json=body,
                timeout=180.0,
            )
            r.raise_for_status()
            last_raw = r.json()["choices"][0]["message"]["content"]
            return _extract_json(last_raw)
        except httpx.HTTPError as e:
            last_err, last_raw = f"HTTP error: {e}", ""
            if attempt == attempts - 1:
                raise LLMError(f"OpenRouter gagal setelah {attempts}x: {e}") from e
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt == attempts - 1:
                raise LLMError(
                    f"JSON invalid setelah {attempts}x. Error terakhir: {last_err}"
                ) from e
