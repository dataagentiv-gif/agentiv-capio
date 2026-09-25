"""Smoke render nyata: jalur produksi, sumber 16:9 dengan audio."""
import json
import subprocess

import pytest

from pipeline.motion import build
from pipeline.reference_caption import CaptionEngine, MOTIONS, render_overlay
from pipeline.stages.render import _render_templates
from pipeline.templates import MOTIONS, TEMPLATES, resolve
from tests.fixtures.make_fixture import build as source_fixture
from utils.ffmpeg_helpers import Deadline

CASES = [(template_id, {"caption_motion": motion} if motion else {})
         for template_id in TEMPLATES
         for motion in (sorted(MOTIONS[template_id]) if template_id in MOTIONS else [None])]
CASES += [
    ("full_screen", {"caption_style": "background", "active_background_color": "#FF3300"}),
    ("full_screen", {"caption_style": "background_scale"}),
    ("blur_atas_bawah", {"hook_block": "white", "caption_style": "background"}),
    ("blur_atas_bawah", {"hook_block": "none", "caption_style": "background_scale"}),
    ("kotak_tengah", {"caption_motion": "scatter_emphasis", "scatter_accent_color": "#33FFAA"}),
]


@pytest.mark.parametrize("template_id,adjustments", CASES)
def test_template_video_audio_dan_dimensi(tmp_path, template_id, adjustments):
    source = source_fixture()
    options = resolve(template_id, adjustments)
    words = [{"i": i, "w": word, "s": i * 0.38, "e": (i + 1) * 0.38}
             for i, word in enumerate("Ini contoh kata penting untuk diuji".split())]
    seg = {"id": "c1", "start": 0.0, "end": 2.5,
           "hook": "Ini contoh kata penting", "hook_title": "Contoh kata penting"}
    crop = {"x": 656, "w": 608, "fx": 0.35, "fy": 0.4, "speaker_side": "kiri"}
    captions = {}
    if template_id != "mentahan":
        if options.get("caption_motion") in MOTIONS:
            path = render_overlay(CaptionEngine(words, seg, template_id, options, crop, {3}),
                                  tmp_path / "c1.mov", Deadline(300))
        else:
            path = tmp_path / "c1.ass"
            path.write_text(build(words, seg, template_id, options, crop, {3}), encoding="utf-8")
        captions["c1"] = path
    ctx = {"template_id": template_id, "adjustments": options, "source": source,
           "meta": {"width": 1920, "height": 1080}, "workdir": tmp_path,
           "segments_final": [seg], "crops": {"c1": crop}, "captions": captions,
           "deadline": Deadline(300)}
    output = _render_templates(ctx)["rendered"]["c1"]
    data = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
         "-of", "json", str(output)], check=True, capture_output=True, text=True).stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == ((1920, 1080) if template_id == "mentahan" else (1080, 1920))
    assert any(s["codec_type"] == "audio" for s in data["streams"])
