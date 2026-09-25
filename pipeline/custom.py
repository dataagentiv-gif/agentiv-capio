"""Small, validated Custom geometry adapter built on CAPIO's existing ASS path."""
from dataclasses import replace
from pathlib import Path
import re

from pipeline import layout
from pipeline.stages.caption import build_ass

RATIOS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
PANEL_SCALE = {"small": .72, "medium": .84, "large": .94}


def output_size(options: dict) -> tuple[int, int]:
    return RATIOS[options["output_ratio"]]


def panel_size(options: dict, out_w: int, out_h: int) -> tuple[int, int]:
    ratio = {"9:16": 9 / 16, "1:1": 1., "16:9": 16 / 9}[options["panel_ratio"]]
    scale = PANEL_SCALE[options["panel_size"]]
    if out_w / out_h > ratio:
        h = int(out_h * scale) & ~1
        w = int(h * ratio) & ~1
    else:
        w = int(out_w * scale) & ~1
        h = int(w / ratio) & ~1
    return max(2, w), max(2, h)


def caption_ass(words: list[dict], seg: dict, options: dict, out_w: int, out_h: int) -> str:
    """Reuse the full-screen caption builder, retargeting its canvas and knobs."""
    if not options["caption"]:
        return ""
    lay = replace(
        layout.ambil("penuh"),
        ukuran={"small": 72, "medium": 96, "large": 120}[options["caption_size"]],
        kata=options["caption_words"],
        margin_v=round((1 - options["caption_position"]) * out_h),
        margin_l=round(out_w * .07), margin_r=round(out_w * .07),
    )
    knob = {
        "font": options["caption_font"], "ukuran": lay.ukuran,
        "kata": options["caption_words"], "upper": options["caption_upper"],
        "active_word_style": options["caption_style"],
        "active_text_color": options["active_text_color"],
        "active_background_color": options["active_background_color"],
        "aktif": options["active_text_color"],
        "active_word_text_color": options["active_text_color"],
        "active_word_background_color": options["active_background_color"],
        "active_word_border_radius": 18, "active_word_padding_x": 18,
        "active_word_padding_y": 8, "active_word_glow": False,
    }
    ass = build_ass(words, seg["start"], seg["end"], lay, knob)
    # build_ass's reference layout is 1080x1920.  Custom can render on a
    # square or landscape canvas too; explicit ASS positions do not follow
    # PlayRes changes, so scale them to the largest canvas that fits without
    # changing the caption's proportions.
    sx, sy = out_w / 1080, out_h / 1920
    scale = min(sx, sy)
    if abs(sx - 1) > 0.001 or abs(sy - 1) > 0.001:
        def pos(match):
            return r"\pos(%d,%d)" % (round(int(match.group(1)) * sx),
                                      round(int(match.group(2)) * sy))
        ass = re.sub(r"\\pos\((\d+),(\d+)\)", pos, ass)
        ass = re.sub(r"\\fs(\d+(?:\.\d+)?)",
                     lambda m: r"\fs" + str(round(float(m.group(1)) * scale)), ass)
    ass = ass.replace("PlayResX: 1080", f"PlayResX: {out_w}")
    ass = ass.replace("PlayResY: 1920", f"PlayResY: {out_h}")
    if options["hook"]:
        title = seg.get("hook_title") or seg.get("hook") or ""
        title = " ".join(title.split())
        words_title = title.split()
        lines, current = [], ""
        for word in words_title:
            if current and len(current) + len(word) + 1 > 28:
                lines.append(current); current = ""
            current = f"{current} {word}".strip()
        if current: lines.append(current)
        lines = lines[:2]
        if options["hook_block"] == "white" and lines:
            box_w = round(out_w * .86)
            box_h = 110 + max(0, len(lines) - 1) * 86
            ass += (f"Dialogue: 0,0:00:00.00,{seg['end'] - seg['start']:.2f},Cap,,0,0,0,,"
                    f"{{\\an7\\pos({(out_w-box_w)//2},{round(out_h*.06)})\\p1\\1c&HFFFFFF&\\bord0}}"
                    f"m 0 0 l {box_w} 0 {box_w} {box_h} 0 {box_h}{{\\p0}}\n")
        for i, line in enumerate(lines):
            color = "000000" if options["hook_block"] == "white" else "FFFFFF"
            ass += (f"Dialogue: 1,0:00:00.00,{seg['end'] - seg['start']:.2f},Cap,,0,0,0,,"
                    f"{{\\an8\\pos({out_w//2},{round(out_h*.10)+i*90})\\fnPoppins"
                    f"\\fs{max(32, round(out_w*.08))}\\b1\\1c&H{color}&"
                    f"\\bord{0 if options['hook_block']=='white' else 3}"
                    f"\\shad{0 if options['hook_block']=='white' else 3}}}{line}\n")
    return ass
