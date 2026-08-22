"""Stage 8: judul, caption, hashtag — satu panggilan LLM batch untuk semua klip.

Input  : ctx[segments_final]
Output : {clip_id: {title, caption, hashtags[]}}
"""
import json

from llm.client import call_llm
from utils.logging import get

log = get(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "caption": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "caption", "hashtags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

PROMPT = """Buatkan judul, caption, dan hashtag untuk klip-klip video pendek berikut.

Untuk tiap klip:
- title: maksimal 60 karakter, bikin penasaran, tanpa clickbait bohong. Jangan \
pakai tanda kutip.
- caption: 1-2 kalimat untuk kolom deskripsi, boleh diakhiri satu pertanyaan \
yang memancing komentar.
- hashtags: 3-6 tag relevan, tanpa tanda pagar, huruf kecil semua.

Balas untuk SEMUA klip, pakai `id` yang persis sama seperti di bawah.

Klip:
{clips}"""


def _fallback(seg: dict) -> dict:
    """Dipakai saat LLM gagal total. Job tetap `done`, bukan `failed` (PRD
    Bagian 3): klip video-nya sendiri sudah jadi dan tetap berguna.
    """
    hook = (seg.get("hook") or "").strip()
    return {"title": hook[:60] or seg["id"], "caption": "", "hashtags": []}


def run(ctx: dict) -> dict:
    segments = ctx["segments_final"]
    listing = "\n".join(
        f"- id: {s['id']}\n  hook: {s.get('hook', '')}\n  alasan: {s.get('reason', '')}"
        for s in segments
    )

    try:
        result = call_llm(PROMPT.format(clips=listing), SCHEMA)
        items = result.get("clips", []) if isinstance(result, dict) else result
        by_id = {str(c.get("id")): c for c in items if isinstance(c, dict)}
    except Exception as e:  # noqa: BLE001
        log.warning("metadata gagal setelah retry (%s) — pakai fallback dari hook", e)
        by_id = {}

    out = {}
    for seg in segments:
        c = by_id.get(seg["id"])
        if not c or not str(c.get("title", "")).strip():
            out[seg["id"]] = _fallback(seg)
            continue
        out[seg["id"]] = {
            "title": str(c["title"]).strip()[:100],
            "caption": str(c.get("caption", "")).strip(),
            "hashtags": [
                str(h).lstrip("#").strip().lower()
                for h in (c.get("hashtags") or [])
                if str(h).strip()
            ][:6],
        }

    (ctx["workdir"] / "metadata.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("metadata: %d klip (%d dari LLM)", len(out), len(by_id))
    return {"metadata": out}
