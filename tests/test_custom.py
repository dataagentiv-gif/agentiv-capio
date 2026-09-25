import json
import subprocess

import pytest

from api.template_preview import render
from pipeline.custom import output_size
from pipeline.templates import resolve


def test_custom_defaults_and_validation():
    options = resolve("custom", {})
    assert output_size(options) == (1080, 1920)
    assert options["caption"] is True
    with pytest.raises(ValueError):
        resolve("custom", {"output_ratio": "4:3"})
    with pytest.raises(ValueError):
        resolve("custom", {"caption_words": 5})
    with pytest.raises(ValueError):
        resolve("custom", {"caption": "false"})


@pytest.mark.parametrize("ratio,size", [("9:16", (1080, 1920)), ("1:1", (1080, 1080)),
                                         ("16:9", (1920, 1080))])
def test_custom_preview_dimensions(tmp_path, ratio, size):
    data = render("custom", resolve("custom", {"output_ratio": ratio,
                                                   "video_mode": "panel",
                                                   "background": "blur",
                                                   "hook": True,
                                                   "hook_block": "white"}))
    path = tmp_path / "custom.mp4"
    path.write_bytes(data)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if "width" in s)
    assert (video["width"], video["height"]) == size
