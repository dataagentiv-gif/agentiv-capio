"""Small, validated Custom geometry adapter built on CAPIO's existing ASS path."""
from dataclasses import replace
from pathlib import Path
import re

from pipeline import layout
from pipeline.stages.caption import _ts, build_ass

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
        ukuran=options.get("caption_px") or {"small": 72, "medium": 96, "large": 120}[options["caption_size"]],
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
        "pasif": options.get("caption_color", "FFFFFF"), "italic": options.get("caption_italic", False),
        "outline": options.get("caption_outline", 6), "shadow": options.get("caption_shadow", 2),
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
        ass += _hook(seg, options, out_w, out_h)
    return ass


def _ev(layer: int, end: str, tags: str, text: str) -> str:
    """Satu event ASS di awal klip; tags tanpa kurung kurawal maupun garis miring awal."""
    return f"Dialogue: {layer},0:00:00.00,{end},Cap,,0,0,0,,{{\\{tags}}}{text}\n"


def _rect(w: int, h: int) -> str:
    return f"m 0 0 l {w} 0 {w} {h} 0 {h}{{\\p0}}"


def _hook(seg: dict, options: dict, out_w: int, out_h: int) -> str:
    title = " ".join((seg.get("hook_title") or seg.get("hook") or "").split())
    if not title:
        return ""
    framed = options["hook_block"] == "frame"
    limit = 28
    if framed:
        # Kartu berbingkai menjaga judul tetap dua baris yang seimbang: judul
        # panjang membuat hurufnya mengecil, bukan menambah baris.
        words = title.split()
        if len(title) <= 30 or len(words) < 2:
            lines = [title]
        else:
            cut = min(range(1, len(words)), key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))))
            lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        limit = max(30, *(len(line) for line in lines))
    else:
        lines, current = [], ""
        for word in title.split():
            if current and len(current) + len(word) + 1 > limit:
                lines.append(current)
                current = ""
            current = f"{current} {word}".strip()
        if current:
            lines.append(current)
        lines = lines[:2]
    span = seg["end"] - seg["start"]
    end = _ts(min(options.get('hook_seconds') or span, span))
    top = round(out_h * options.get("hook_position", .06))
    out = ""
    if framed:
        # Kartu putih dengan bingkai berwarna di belakangnya, teks hitam rata kiri.
        # Angka diukur dari referensi 1080x1920 lalu diskalakan ke lebar kanvas.
        k = out_w / 1080
        shrink = min(1, 30 / limit)
        box_w, pad, size, step = round(800 * k), round(32 * k), round(76 * k * shrink), round(54 * k * shrink)
        box_h = round(2 * pad + 27 * k + step * len(lines))
        x = (out_w - box_w) // 2
        frame = options.get("hook_frame_color", "800010")
        bgr = frame[4:6] + frame[2:4] + frame[0:2]
        fl, ft, fr, fb = round(16 * k), round(18 * k), round(15 * k), round(26 * k)
        out += _ev(0, end, f"an7\\pos({x - fl},{top - ft})\\p1\\1c&H{bgr}&\\bord0\\shad0",
                   _rect(box_w + fl + fr, box_h + ft + fb))
        out += _ev(1, end, f"an7\\pos({x},{top})\\p1\\1c&HFFFFFF&\\bord0\\shad0", _rect(box_w, box_h))
        for i, line in enumerate(lines):
            # \an7 menaruh puncak kotak baris (termasuk ruang aksen) di titik pos,
            # jadi digeser naik supaya puncak huruf jatuh pada padding atas.
            out += _ev(2, end, f"an7\\pos({x + pad},{top + pad - round(16 * k) + i * step})\\fnPoppins\\fs{size}"
                               f"\\b1\\i0\\1c&H000000&\\bord0\\shad0", line)
        return out
    white = options["hook_block"] == "white"
    if white and lines:
        box_w = round(out_w * .86)
        box_h = 110 + max(0, len(lines) - 1) * 86
        out += _ev(0, end, f"an7\\pos({(out_w - box_w) // 2},{top})\\p1\\1c&HFFFFFF&\\bord0", _rect(box_w, box_h))
    for i, line in enumerate(lines):
        out += _ev(1, end, f"an8\\pos({out_w // 2},{top + round(out_h * .04) + i * 90})\\fnPoppins"
                           f"\\fs{max(32, round(out_w * .08))}\\b1\\i0\\1c&H{'000000' if white else 'FFFFFF'}&"
                           f"\\bord{0 if white else 3}\\shad{0 if white else 3}", line)
    return out
