"""Gemini hanya menunjuk indeks transkrip, tidak boleh menulis ulang caption."""
from llm import call_llm
from utils.logging import get

log = get(__name__)
SCHEMA = {"type": "object", "properties": {"indices": {"type": "array", "items": {"type": "integer"}}},
          "required": ["indices"], "additionalProperties": False}


def choose(words: list[dict], start: float, end: float) -> set[int]:
    eligible = [w for w in words if w["e"] > start and w["s"] < end]
    if not eligible:
        return set()
    fallback = {w["i"] for w in eligible if len(w["w"]) >= 7}
    if not fallback:
        fallback = {eligible[0]["i"]}
    listing = "\n".join(f"{w['i']}: {w['w']} ({w['s']:.2f}-{w['e']:.2f})" for w in eligible)
    try:
        result = call_llm(
            "Pilih 1-4 indeks kata paling penting secara makna untuk penekanan visual. "
            "HANYA kembalikan indeks asli yang tertera, jangan menulis ulang teks.\n" + listing,
            SCHEMA, attempts=1,
        )
        valid = {w["i"] for w in eligible if start <= w["s"] < end and w["e"] > w["s"]}
        indices = result.get("indices", [])
        if not isinstance(indices, list) or not 1 <= len(indices) <= 4 or any(type(i) is not int or i not in valid for i in indices):
            raise ValueError("indeks atau waktu anotasi tidak sah")
        return set(indices)
    except Exception as exc:  # noqa: BLE001 - anotasi bukan syarat job selesai
        log.warning("anotasi emphasis gagal: %s; memakai fallback", exc)
        return set(list(fallback)[:4])
