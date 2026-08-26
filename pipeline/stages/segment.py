"""Stage 3: seleksi momen oleh LLM.

Input  : ctx[words], ctx[target_clips], ctx[workdir]
Output : segments_raw.json -> [{start_idx, end_idx, hook, reason, score}]
"""
import json
from pathlib import Path

from config.settings import settings
from llm import call_llm
from utils.logging import get

log = get(__name__)

# Kata per baris transkrip ber-index. 10 kata (~3 detik) cukup halus untuk
# menandai batas momen, dan jauh lebih hemat token daripada memberi nomor pada
# setiap kata — untuk video 1 jam selisihnya ribuan token.
WORDS_PER_LINE = 10

SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_idx": {"type": "integer"},
                    "end_idx": {"type": "integer"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_idx", "end_idx", "hook", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

PROMPT = """Kamu editor video short-form. Di bawah ini transkrip lengkap sebuah \
video, dipecah per baris. Angka dalam kurung siku di awal baris adalah index \
kata pertama pada baris itu.

Tugas: pilih {n} momen paling layak dijadikan klip pendek berdiri sendiri.

Kriteria momen yang bagus:
- Punya kail pembuka yang bikin orang berhenti scroll di 3 detik pertama.
- Utuh: ada pembuka, isi, dan penutup. Bukan potongan kalimat menggantung.
- Bisa dipahami tanpa menonton sisa video.
- Ada opini tajam, cerita konkret, angka mengejutkan, atau pembalikan asumsi.

Aturan keras:
- Durasi tiap klip WAJIB antara {min_s:.0f} dan {max_s:.0f} detik. Rata-rata \
{wps:.1f} kata per detik, jadi pilih rentang sekitar {min_w}-{max_w} kata.
- end_idx harus lebih besar dari start_idx.
- Antar klip tidak boleh tumpang tindih.
- Index tertinggi yang tersedia adalah {max_idx}.

Isi tiap field:
- start_idx / end_idx: index kata awal dan akhir klip.
- hook: kalimat pembuka klip, disalin apa adanya dari transkrip.
- reason: satu kalimat, kenapa momen ini layak jadi klip.
- score: 0-100, seberapa yakin kamu klip ini bakal perform.

Transkrip:
{transcript}"""


def _indexed_transcript(words: list[dict]) -> str:
    lines = []
    for i in range(0, len(words), WORDS_PER_LINE):
        chunk = words[i : i + WORDS_PER_LINE]
        lines.append(f"[{chunk[0]['i']}] " + " ".join(w["w"] for w in chunk))
    return "\n".join(lines)


def _validate(raw: list[dict], words: list[dict], target: int) -> list[dict]:
    """Buang kandidat yang melanggar kontrak, lalu buang yang tumpang tindih.

    Dijalankan di sini, sebelum Stage 4, karena segmen di luar rentang durasi
    tetap lolos validasi JSON tapi menghasilkan klip yang terlalu pendek atau
    terlalu panjang saat render.
    """
    last = len(words) - 1
    ok = []
    for s in raw:
        try:
            a, b = int(s["start_idx"]), int(s["end_idx"])
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(0, min(a, last)), max(0, min(b, last))
        if b <= a:
            log.warning("segmen dibuang (end_idx <= start_idx): %s-%s", a, b)
            continue
        dur = words[b]["e"] - words[a]["s"]
        if not (settings.MIN_CLIP_SEC <= dur <= settings.MAX_CLIP_SEC):
            log.warning("segmen dibuang (durasi %.1fs di luar rentang): %s-%s", dur, a, b)
            continue
        ok.append(
            {
                "start_idx": a,
                "end_idx": b,
                "hook": str(s.get("hook", "")).strip(),
                "reason": str(s.get("reason", "")).strip(),
                "score": max(0, min(100, int(s.get("score", 0)))),
            }
        )

    # Skor tertinggi menang saat tumpang tindih.
    chosen: list[dict] = []
    for s in sorted(ok, key=lambda x: -x["score"]):
        if any(s["start_idx"] <= c["end_idx"] and c["start_idx"] <= s["end_idx"] for c in chosen):
            continue
        chosen.append(s)
        if len(chosen) >= target:
            break
    return sorted(chosen, key=lambda x: x["start_idx"])


def run(ctx: dict) -> dict:
    words: list[dict] = ctx["words"]
    workdir: Path = ctx["workdir"]
    target = int(ctx["target_clips"])

    total_dur = words[-1]["e"] - words[0]["s"]
    wps = len(words) / total_dur if total_dur > 0 else 2.5

    prompt = PROMPT.format(
        n=target,
        min_s=settings.MIN_CLIP_SEC,
        max_s=settings.MAX_CLIP_SEC,
        wps=wps,
        min_w=int(settings.MIN_CLIP_SEC * wps),
        max_w=int(settings.MAX_CLIP_SEC * wps),
        max_idx=len(words) - 1,
        transcript=_indexed_transcript(words),
    )

    result = call_llm(prompt, SCHEMA)
    raw = result.get("segments", []) if isinstance(result, dict) else result
    segments = _validate(raw, words, target)

    if not segments:
        raise RuntimeError(
            f"Tidak ada segmen lolos validasi dari {len(raw)} kandidat LLM. "
            f"Cek rentang durasi {settings.MIN_CLIP_SEC}-{settings.MAX_CLIP_SEC}s."
        )

    (workdir / "segments_raw.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("segment: %d kandidat -> %d lolos", len(raw), len(segments))
    return {"segments_raw": segments}
