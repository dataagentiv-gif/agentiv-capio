"""Mesin bersama untuk provider yang bicara protokol OpenAI chat/completions.

OpenRouter dan Gemini dua-duanya menyediakan endpoint OpenAI-compatible, jadi
badan request, cara baca response, dan loop retry-nya identik. Yang benar-benar
berbeda cuma tiga hal, dan itulah yang jadi parameter di sini: URL endpoint,
dari mana API key diambil, dan apakah provider-nya menerima response_format
bertipe json_schema.
"""
import json
import re
import time

import httpx

from utils.logging import get

log = get(__name__)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class LLMError(RuntimeError):
    pass


# Jeda sebelum percobaan berikutnya, untuk kegagalan yang sifatnya sementara.
# Terukur di pemakaian: tanpa jeda, tiga percobaan terhadap Gemini yang sedang
# 503 habis dalam 4 DETIK dan seluruh job gagal — padahal gangguannya biasanya
# berlangsung lebih lama dari itu. Menggempur server yang sedang penuh secepat
# itu bukan cuma sia-sia, tapi memperparah keadaannya.
JEDA = (3, 8, 20, 30, 30)


def _tunggu(sementara: bool, attempt: int, label: str) -> None:
    if not sementara:
        return
    detik = JEDA[min(attempt, len(JEDA) - 1)]
    log.info("%s: gangguan sementara, tunggu %ds sebelum coba lagi", label, detik)
    time.sleep(detik)


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


def call(
    prompt: str,
    response_schema: dict | None,
    *,
    endpoint: str,
    get_key,
    model: str,
    use_schema: bool,
    attempts: int = 3,
    label: str = "llm",
):
    """Panggil LLM, kembalikan hasil yang sudah di-parse jadi objek Python.

    `get_key` adalah callable yang dipanggil ULANG di tiap percobaan. Itulah yang
    membuat rotasi key Gemini bekerja: percobaan gagal karena kena rate limit
    otomatis memakai key berikutnya, tanpa logika khusus di sini.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    if response_schema:
        body["response_format"] = (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
            if use_schema
            # Provider yang belum dipastikan menerima json_schema cukup diminta
            # JSON bebas. Bentuknya tetap terjaga karena prompt sudah menyebut
            # tiap field, stage memvalidasi hasilnya sendiri, dan error parsing
            # disuntikkan balik ke prompt di percobaan berikutnya.
            else {"type": "json_object"}
        )

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
                endpoint,
                headers={"Authorization": f"Bearer {get_key()}"},
                json=body,
                timeout=180.0,
            )
            r.raise_for_status()
            last_raw = r.json()["choices"][0]["message"]["content"]
            return _extract_json(last_raw)

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            last_err, last_raw = f"HTTP {code}", ""
            log.warning(
                "%s percobaan %d/%d gagal: HTTP %d %s",
                label, attempt + 1, attempts, code, e.response.text[:200],
            )
            if attempt == attempts - 1:
                raise LLMError(f"{label} gagal setelah {attempts}x: HTTP {code}") from e
            _tunggu(code >= 500 or code == 429, attempt, label)

        except httpx.HTTPError as e:
            last_err, last_raw = f"koneksi: {e}", ""
            if attempt == attempts - 1:
                raise LLMError(f"{label} gagal setelah {attempts}x: {e}") from e
            _tunggu(True, attempt, label)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            log.warning("%s percobaan %d/%d: JSON invalid — %s", label, attempt + 1, attempts, last_err)
            if attempt == attempts - 1:
                raise LLMError(
                    f"{label}: JSON invalid setelah {attempts}x. Terakhir: {last_err}"
                ) from e
            # Tanpa jeda: kegagalan ini soal ISI balasan, bukan kondisi server.
            # Percobaan ulangnya membawa pesan error sebagai umpan balik, dan
            # menundanya tidak menambah peluang berhasil sama sekali.
