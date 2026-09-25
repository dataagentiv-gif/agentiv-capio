"""Regression checks for the reference engine adapter's visual contract."""
import pytest

from pipeline.reference_caption import CaptionEngine


@pytest.mark.parametrize("template,motion", [
    ("pembicara_samping", m) for m in ("soft_focus", "kinetic_words", "editorial_focus")
] + [("kotak_tengah", m) for m in ("single_word_float", "soft_phrase", "scatter_emphasis")])
@pytest.mark.parametrize("side", ["kiri", "kanan"])
def test_caption_stays_in_its_lane_with_long_word(template, motion, side):
    words = [{"i": 0, "w": "superkalifragilistikekspialidocious" * 4,
              "s": 0.0, "e": 1.0}]
    seg = {"start": 0., "end": 1.5}
    options = {"caption_motion": motion, "scatter_accent_color": "33FFAA"}
    engine = CaptionEngine(words, seg, template, options, {"speaker_side": side}, {0})
    left, top, right, bottom = engine.zone
    for t in (.03, .10, .25, .75, 1.42):
        bounds = engine.frame(t).getchannel("A").getbbox()
        if bounds:
            assert left <= bounds[0] < bounds[2] <= right
            assert top <= bounds[1] < bounds[3] <= bottom


def test_spoken_timing_and_scatter_accent():
    words = [{"i": 0, "w": "awal", "s": .4, "e": .8},
             {"i": 1, "w": "penting", "s": .9, "e": 1.3}]
    engine = CaptionEngine(words, {"start": 0., "end": 2.}, "kotak_tengah",
                           {"caption_motion": "scatter_emphasis", "scatter_accent_color": "33FFAA"},
                           {"speaker_side": "kiri"}, {1})
    assert engine.frame(.1).getchannel("A").getbbox() is None
    assert engine.frame(1.1).getchannel("A").getbbox() is not None
    assert any(item["color"] == (0x33, 0xFF, 0xAA) for item in engine.groups[0]["items"])
