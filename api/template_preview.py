"""Cuplikan netral yang lewat motion dan render produksi yang sama."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from pipeline.motion import build
from pipeline.stages.render import _render_templates
from pipeline.templates import resolve
from utils.ffmpeg_helpers import Deadline

_CACHE: dict[str, bytes] = {}


def render(template_id: str, adjustments: dict) -> bytes:
    options = resolve(template_id, adjustments)
    key = hashlib.sha1(json.dumps([template_id, options], sort_keys=True).encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        source = workdir / "source.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x555e68:s=1920x1080:r=12:d=6",
            "-vf", "drawbox=x=200:y=200:w=480:h=700:color=0x8a929a:t=fill,"
                   "drawbox=x=300:y=90:w=270:h=270:color=0xb3bbc2:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source),
        ], check=True, timeout=90)
        words = [
            {"i": i, "w": w, "s": i * 0.48, "e": (i + 1) * 0.48}
            for i, w in enumerate("Ini contoh caption bergerak dengan kata penting lalu muncul lebih jelas lagi".split())
        ]
        seg = {"id": "p", "start": 0.0, "end": 6.0,
               "hook": "Ini contoh caption bergerak", "hook_title": "Contoh topik utama"}
        crop = {"x": 0, "w": 608, "fx": 0.32, "fy": 0.38, "speaker_side": "kiri"}
        captions = {}
        if template_id != "mentahan":
            (workdir / "p.ass").write_text(build(words, seg, template_id, options, crop, {2, 5, 9}), encoding="utf-8")
            captions["p"] = workdir / "p.ass"
        ctx = {"template_id": template_id, "adjustments": options, "source": source,
               "workdir": workdir, "meta": {"width": 1920, "height": 1080},
               "segments_final": [seg], "crops": {"p": crop}, "captions": captions,
               "deadline": Deadline(180)}
        result = _render_templates(ctx)["rendered"]["p"].read_bytes()
    if len(_CACHE) >= 32:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = result
    return result
