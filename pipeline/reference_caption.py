"""Adapt the six approved reference caption engines to CAPIO transcript cues.

The reference presets were fitted at 576x1024 (editorial: 1024x576).
This module keeps their font, timing, colour and FX values while fitting the
finished footprint into CAPIO's fixed speaker lane or rounded video card.
"""
from __future__ import annotations

import io
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from pipeline.stages.caption import _group
from pipeline.templates import TEMPLATES

W, H, FPS = 1080, 1920, 30
MOTIONS = {"soft_focus", "kinetic_words", "editorial_focus",
           "single_word_float", "soft_phrase", "scatter_emphasis"}
FONT_FILES = {"serif": "georgiab.ttf", "condensed": "impact.ttf", "sans": "arialbd.ttf"}


def font_path(name: str) -> Path:
    directory = os.environ.get("CAPIO_REFERENCE_FONT_DIR")
    if not directory and os.name == "nt":
        directory = str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
    if not directory:
        directory = "/app/reference-fonts"
    path = Path(directory) / FONT_FILES[name]
    if not path.is_file():
        raise RuntimeError(f"Font engine wajib tidak ada: {path}. Set CAPIO_REFERENCE_FONT_DIR.")
    return path


def verify_fonts() -> None:
    for name in FONT_FILES:
        font_path(name)


def _ease(p: float) -> float:
    return 1 - (1 - max(0., min(1., p))) ** 3


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(bytes.fromhex(value.lstrip("#")))


def _bbox(font, text: str) -> tuple[int, int]:
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


class CaptionEngine:
    def __init__(self, words: list[dict], seg: dict, template_id: str, options: dict,
                 crop: dict, emphasized=()):
        self.motion = options["caption_motion"]
        if self.motion not in MOTIONS:
            raise ValueError("Motion engine tidak dikenal")
        self.template_id = template_id
        self.duration = seg["end"] - seg["start"]
        self.accent = _rgb(options.get("scatter_accent_color", "FFE500"))
        self.side = crop.get("speaker_side", "kiri")
        self.emphasized = set(emphasized)
        self.font_file = font_path("condensed" if self.motion == "kinetic_words" else
                                   "sans" if self.motion == "editorial_focus" else "serif")
        if template_id == "kotak_tengah":
            panel = TEMPLATES[template_id]["visual"]["panel_height"]
            top = (H - panel) // 2
            self.zone = (74, top + 56, W - 74, top + panel - 56)
        else:
            panel = TEMPLATES[template_id]["visual"]["panel_height"]
            top = (H - panel) // 2
            self.zone = ((590, top + 65, 1020, top + panel - 65) if self.side == "kiri"
                         else (60, top + 65, 490, top + panel - 65))
        relevant = [w for w in words if w["e"] > seg["start"] and w["s"] < seg["end"]]
        count = {"soft_focus": 3, "kinetic_words": 2, "editorial_focus": 4,
                 "single_word_float": 1, "soft_phrase": 3, "scatter_emphasis": 3}[self.motion]
        self.groups = []
        for group in _group(relevant, count, 28):
            start = max(0., group[0]["s"] - seg["start"])
            end = min(self.duration, group[-1]["e"] - seg["start"] + 0.2)
            if end > start:
                self.groups.append({"start": start, "end": end, "words": group})
        for i, group in enumerate(self.groups[:-1]):
            group["end"] = min(group["end"], self.groups[i + 1]["start"])
        self._font_cache = {}
        for group in self.groups:
            group["items"] = self._layout(group, seg["start"])
            for item in group["items"]:
                item["layer"] = self._glyph(item)
                self._fit_layer(item)

    def _font(self, size: int):
        size = max(12, int(size))
        if size not in self._font_cache:
            self._font_cache[size] = ImageFont.truetype(self.font_file, size)
        return self._font_cache[size]

    def _fit(self, text: str, size: int, max_w: int, peak: float, pad: int) -> int:
        while size > 12 and (_bbox(self._font(size), text)[0] + 2 * pad) * peak > max_w:
            size -= 2
        return max(12, size)

    def _layout(self, group: dict, clip_start: float) -> list[dict]:
        words = group["words"]
        motion = self.motion
        left, top, right, bottom = self.zone
        width, height = right - left, bottom - top
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        focus = next((w for w in words if w["i"] in self.emphasized),
                     max(words, key=lambda w: (len(w["w"]), -w["i"])))
        items = []

        if motion in {"soft_focus", "soft_phrase", "editorial_focus"}:
            if motion == "soft_focus":
                pieces = [words[:2], words[2:]]
            else:
                focus_index = words.index(focus)
                pieces = [words[:focus_index], [focus], words[focus_index + 1:]]
            pieces = [part for part in pieces if part]
            for j, part in enumerate(pieces):
                hero = focus in part and motion != "soft_focus"
                text = " ".join(w["w"] for w in part)
                size = (62 if motion == "soft_focus" else
                        (155 if hero else 101) if motion == "soft_phrase" else
                        (94 if hero else 73))
                if motion == "editorial_focus" and hero:
                    text = text.upper()
                pad = 75 if motion == "soft_focus" else 30
                size = self._fit(text, size, width, 1.16, pad)
                items.append({"text": text, "size": size, "hero": hero,
                              "enter": max(group["start"], part[0]["s"] - clip_start),
                              "color": (255, 255, 255), "pad": pad})
            line_heights = [max(_bbox(self._font(i["size"]), i["text"])[1] + 22,
                                round(i["size"] * 1.14)) for i in items]
            total = sum(line_heights) + 12 * max(0, len(items) - 1)
            if total > height:
                ratio = height / total
                for item in items:
                    item["size"] = max(12, int(item["size"] * ratio))
                line_heights = [round(item["size"] * 1.17) for item in items]
                total = sum(line_heights) + 12 * max(0, len(items) - 1)
            y = cy - total // 2
            for j, item in enumerate(items):
                w, _ = _bbox(self._font(item["size"]), item["text"])
                if motion == "editorial_focus":
                    offset = 0 if item["hero"] else (30 if self.side == "kanan" else -30)
                    item["x"] = max(left + item["pad"], min(right - item["pad"] - w, cx - w // 2 + offset))
                else:
                    item["x"] = cx - w // 2
                item["y"] = y + (line_heights[j] - item["size"]) // 2
                y += line_heights[j] + 12
            return items

        for j, w in enumerate(words):
            hero = w is focus
            text = w["w"].upper() if motion == "kinetic_words" else w["w"]
            if motion == "kinetic_words":
                size, peak, pad = (150 if hero else 115), 1.10, 20
            elif motion == "single_word_float":
                size, peak, pad = 101, 1.035, 18
            else:
                size, peak, pad = (89 if hero else 78), 1.06, 18
            if motion == "scatter_emphasis":
                max_w = width * (0.60 if not hero else 0.75)
            else:
                max_w = width
            size = self._fit(text, size, int(max_w), peak, pad)
            tw, th = _bbox(self._font(size), text)
            if motion == "scatter_emphasis":
                positions = [(left + width * .27, top + height * .24),
                             (left + width * .72, top + height * .50),
                             (left + width * .32, top + height * .76)]
                x, y = positions[j % 3]
            elif motion == "kinetic_words":
                x, y = cx, cy + (j - (len(words) - 1) / 2) * 165
            else:
                x, y = cx, cy
            x = max(left + pad + tw * peak / 2,
                    min(right - pad - tw * peak / 2, x))
            y = max(top + pad + th * peak / 2,
                    min(bottom - pad - th * peak / 2, y))
            items.append({"text": text, "size": size, "hero": hero,
                          "enter": max(group["start"], w["s"] - clip_start),
                          "color": self.accent if hero and motion == "scatter_emphasis" else (250, 248, 242),
                          "pad": pad, "x": x - tw / 2, "y": y - th / 2})
        return items

    def _glyph(self, item: dict) -> Image.Image:
        font = self._font(item["size"])
        box = font.getbbox(item["text"])
        w, h = box[2] - box[0], box[3] - box[1]
        pad = item["pad"]
        layer = Image.new("RGBA", (w + pad * 2, h + pad * 2))
        pos = (pad - box[0], pad - box[1])
        d = ImageDraw.Draw(layer)
        if self.motion == "soft_focus":
            # V7 broad bloom, medium glow, tight glow and sharp white core.
            for radius, opacity in ((32, 64), (14, 115), (4, 190)):
                light = Image.new("RGBA", layer.size)
                ImageDraw.Draw(light).text(pos, item["text"], font=font,
                                           fill=(255, 252, 245, opacity))
                layer.alpha_composite(light.filter(ImageFilter.GaussianBlur(radius)))
            d = ImageDraw.Draw(layer)
            d.text(pos, item["text"], font=font, fill=(255, 255, 255, 255))
        else:
            shadow = Image.new("RGBA", layer.size)
            sd = ImageDraw.Draw(shadow)
            stroke = 3 if self.motion == "kinetic_words" else 2
            sd.text((pos[0], pos[1] + 3), item["text"], font=font,
                    fill=(0, 0, 0, 155), stroke_width=stroke + 1,
                    stroke_fill=(0, 0, 0, 170))
            layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
            ImageDraw.Draw(layer).text(pos, item["text"], font=font,
                                       fill=item["color"] + (255,),
                                       stroke_width=stroke, stroke_fill=(18, 15, 15, 255))
        return layer

    def _fit_layer(self, item: dict) -> None:
        """Fit the complete FX patch at peak scale, including long unbroken words."""
        left, top, right, bottom = self.zone
        layer = item["layer"]
        peak = {"soft_focus": 1.04, "kinetic_words": 1.10,
                "editorial_focus": 1.12, "single_word_float": 1.035,
                "soft_phrase": 1.04, "scatter_emphasis": 1.06}[self.motion]
        ratio = min(1., (right - left) / (layer.width * peak),
                    (bottom - top) / (layer.height * peak))
        if ratio < 1:
            old_w, old_h = layer.size
            item["layer"] = layer.resize((max(1, int(old_w * ratio)),
                                            max(1, int(old_h * ratio))), Image.Resampling.LANCZOS)
            old_pad = item["pad"]
            item["pad"] *= ratio
            item["x"] += (old_w - item["layer"].width) / 2 - old_pad + item["pad"]
            item["y"] += (old_h - item["layer"].height) / 2 - old_pad + item["pad"]

    def frame(self, t: float) -> Image.Image:
        canvas = Image.new("RGBA", (W, H))
        for group in self.groups:
            if not group["start"] <= t < group["end"]:
                continue
            remaining = group["end"] - t
            exit_ms = {"soft_focus": .12, "kinetic_words": .08, "editorial_focus": .14,
                       "single_word_float": .10, "soft_phrase": .11, "scatter_emphasis": .12}[self.motion]
            fade_out = min(1., remaining / exit_ms)
            for item in group["items"]:
                if t < item["enter"]:
                    continue
                enter_ms = {"soft_focus": .18, "kinetic_words": .19 if item["hero"] else .12,
                            "editorial_focus": .22 if item["hero"] else .16,
                            "single_word_float": .17, "soft_phrase": .15,
                            "scatter_emphasis": .17}[self.motion]
                p = _ease((t - item["enter"]) / enter_ms)
                peak = {"soft_focus": 1.04, "kinetic_words": 1.10,
                        "editorial_focus": 1.12, "single_word_float": 1.035,
                        "soft_phrase": 1.04, "scatter_emphasis": 1.06}[self.motion]
                start_scale = .98 if self.motion == "soft_focus" else .88
                scale = start_scale + (peak - start_scale) * math.sin(math.pi * min(p, .65) / 1.3)
                if p >= .65:
                    scale = 1 + (peak - 1) * (1 - (p - .65) / .35)
                layer = item["layer"]
                if self.motion in {"soft_focus", "editorial_focus"} and p < 1:
                    layer = layer.filter(ImageFilter.GaussianBlur((1 - p) * (9 if self.motion == "soft_focus" else 7)))
                if scale != 1:
                    layer = layer.resize((max(1, round(layer.width * scale)),
                                          max(1, round(layer.height * scale))), Image.Resampling.BICUBIC)
                alpha = min(1., p * 1.5) * fade_out
                if alpha < 1:
                    layer.putalpha(layer.getchannel("A").point(lambda v: round(v * alpha)))
                x = round(item["x"] - item["pad"] - (layer.width - item["layer"].width) / 2)
                y = round(item["y"] - item["pad"] - (layer.height - item["layer"].height) / 2
                          + (1 - p) * (8 if self.motion in {"kinetic_words", "scatter_emphasis"} else 7))
                left, top, right, bottom = self.zone
                x = max(left, min(right - layer.width, x))
                y = max(top, min(bottom - layer.height, y))
                canvas.alpha_composite(layer, (x, y))
        return canvas

def render_overlay(engine: CaptionEngine, output: Path, deadline) -> Path:
    """Stream lossless RGBA PNG frames into a transparent MOV, without frame files."""
    command = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
               "-f", "image2pipe", "-framerate", str(FPS), "-vcodec", "png", "-i", "pipe:0",
               "-c:v", "qtrle", "-pix_fmt", "argb", str(output)]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        try:
            for n in range(math.ceil(engine.duration * FPS)):
                deadline.check("caption engine")
                buf = io.BytesIO()
                engine.frame(n / FPS).save(buf, format="PNG")
                proc.stdin.write(buf.getvalue())
            proc.stdin.close()
            error = proc.stderr.read().decode(errors="replace")
            if proc.wait() or not output.is_file():
                raise RuntimeError(f"Render caption engine gagal: {error[-500:]}")
        except Exception:
            proc.kill()
            proc.wait()
            raise
    return output
