"""Caption motion per template; geometri video tetap di composition.py."""
from dataclasses import replace

from pipeline import layout, metrik
from pipeline.stages.caption import _clean, _group, _ts, build_ass


def title_lines(title: str, hook: str, limit: int = 34) -> str:
    """Judul maksimum dua baris; kata ekstrem tidak pernah meluber."""
    value = " ".join((title if title and len(title) <= 72 else hook).split())
    words = value.split()
    lines = [""]
    for word in words:
        word = word[:limit - 1] + "…" if len(word) > limit else word
        if len(lines[-1]) + len(word) + bool(lines[-1]) > limit:
            if len(lines) == 2:
                break
            lines.append("")
        lines[-1] = f"{lines[-1]} {word}".strip()
    return "\\N".join(_clean(line) for line in lines if line)


def _event(a, b, text, x, y, size, *, font="Poppins", bold=True,
           width=820, color="FFFFFF", extra="", layer=0):
    """ASS event dengan ukuran nyata terukur agar kata panjang tetap aman."""
    parts = [_clean(part) for part in text] if isinstance(text, list) else [_clean(text)]
    size = max(6, int(size))
    while size > 6 and max(metrik.lebar(part, font, size, bold) for part in parts) > width:
        size -= 2
    place = "" if r"\move" in extra else f"\\pos({x},{y})"
    tag = (f"\\an5{place}\\fn{font}\\b{1 if bold else 0}\\fs{size}"
           f"\\1c&H{layout._bgr(color)}&{extra}")
    return (f"Dialogue: {layer},{_ts(max(0, a))},{_ts(max(a + 0.02, b))},"
            f"Cap,,0,0,0,,{{{tag}}}{r'\N'.join(parts)}")


def _span(groups, gi, start, end):
    group = groups[gi]
    a = max(0, group[0]["s"] - start)
    next_start = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else group[-1]["e"] + 0.35
    return a, min(end - start, next_start - start)


def _focus(group, emphasized):
    """Satu kata dominan per grup, juga saat Gemini hanya memilih sebagian grup."""
    return next((w for w in group if w["i"] in emphasized),
                max(group, key=lambda w: (len(w["w"]), -w["i"])))


def _motion(words, start, end, template_id, options, crop, emphasized):
    motion = options["caption_motion"]
    side = crop.get("speaker_side", "kiri")
    x = 780 if side == "kiri" else 300
    lines = []
    if template_id == "pembicara_samping":
        header = layout.header_ass(replace(layout.ambil("penuh"), tebal=True), {"font": "Poppins"})
        groups = _group(words, 3 if motion == "soft_focus" else 4, 24)
        for gi, group in enumerate(groups):
            a, b = _span(groups, gi, start, end)
            if b <= a:
                continue
            if motion == "soft_focus":
                phrase = [" ".join(w["w"] for w in group[:2]),
                          " ".join(w["w"] for w in group[2:])]
                phrase = [part for part in phrase if part]
                lines.append(_event(a, b, phrase, x, 990, 135, font="Lora", width=440,
                                    extra=r"\bord8\blur8\3c&H888888&\fad(130,130)"))
                lines.append(_event(a, b, phrase, x, 990, 135, font="Lora", width=440,
                                    extra=r"\bord2\blur1\3c&H222222&\fad(130,130)", layer=1))
            elif motion == "kinetic_words":
                for j, w in enumerate(group):
                    wa = max(a, w["s"] - start)
                    yy = 750 + j * 145
                    xx = x + (-30 if j % 2 else 25)
                    extra = (rf"\move({xx},{yy+55},{xx},{yy},0,170)"
                             r"\blur3\t(0,170,\blur0)\fad(80,100)\bord3\shad3")
                    lines.append(_event(wa, b, w["w"].upper(), xx, yy, 160, font="Anton",
                                        width=430, extra=extra))
            else:
                key = _focus(group, emphasized)
                for j, w in enumerate(group):
                    wa = max(a, w["s"] - start)
                    important = w is key
                    yy = 745 + j * 145
                    lines.append(_event(wa, b, w["w"].upper() if important else w["w"],
                                        x, yy, 153 if important else 76, font="Poppins",
                                        width=440, color="FFFFFF" if important else "E1E1E1",
                                        extra=r"\fad(100,100)\bord4\shad4"))
    else:
        header = layout.header_ass(replace(layout.ambil("penuh"), tebal=True), {"font": "Lora"})
        groups = _group(words, 1 if motion == "single_word_float" else 3, 24)
        for gi, group in enumerate(groups):
            a, b = _span(groups, gi, start, end)
            if b <= a:
                continue
            phrase = " ".join(w["w"] for w in group)
            if motion == "single_word_float":
                lines.append(_event(a, b, phrase, 540, 1110, 160, font="Lora", width=850,
                                    extra=r"\blur5\t(0,220,\blur0)\fad(190,130)\bord3\shad3"))
            elif motion == "soft_phrase":
                wrapped = [" ".join(w["w"] for w in group[:2]),
                           " ".join(w["w"] for w in group[2:])]
                lines.append(_event(a, b, [part for part in wrapped if part], 540, 1100, 140,
                                    font="Lora", width=880,
                                    extra=r"\blur4\t(0,180,\blur0)\fad(170,140)\bord4\shad4"))
            else:
                key = _focus(group, emphasized)
                support = [w for w in group if w is not key]
                zones = [(310, 790), (770, 880), (340, 1050)]
                for j, w in enumerate(support):
                    xx, yy = zones[j]
                    lines.append(_event(max(a, w["s"] - start), b, w["w"], xx, yy, 122,
                                        font="Poppins", width=390,
                                        extra=r"\blur3\t(0,160,\blur0)\fad(120,100)\bord2\shad2"))
                color = options["scatter_accent_color"].lstrip("#")
                lines.append(_event(max(a, key["s"] - start), b, key["w"],
                                    540, 1210, 165, font="Archivo Black", width=840,
                                    color=color,
                                    extra=r"\blur5\t(0,170,\blur0)\fad(130,120)\bord4\shad4", layer=1))
    return header + "\n".join(lines) + "\n"


def build(words, seg, template_id, options, crop, emphasized=()):
    if template_id == "mentahan":
        return ""
    if template_id in ("full_screen", "blur_atas_bawah"):
        blur = template_id == "blur_atas_bawah"
        # Job lama membawa kedua knob ini; pilihan baru tidak lagi menampilkannya.
        legacy_blur = blur and ("hook_title_style" in options or "spoken_layout" in options)
        spoken = options.get("spoken_layout", "phrase")
        single = blur and spoken == "single_word"
        base_size = 150 if single else (108 if blur else 96)
        longest = max((len(w["w"]) for w in words), default=1)
        safe_size = min(base_size, max(6, int(850 / (longest * 0.6))))
        lay = replace(layout.ambil("penuh"), margin_v=250 if blur else 330,
                      ukuran=safe_size, kata=1 if single else 3,
                      tebal=True, warna_pasif="FFFFFF")
        knob = {"font": "Archivo Black" if blur else "Poppins",
                "ukuran": lay.ukuran, "kata": lay.kata, "upper": blur,
                "active_word_style": options["caption_style"],
                "aktif": options["active_text_color"].lstrip("#"),
                "active_word_text_color": options["active_text_color"].lstrip("#"),
                "active_word_background_color": options.get("active_background_color", "#FFE500").lstrip("#"),
                "active_word_border_radius": 18, "active_word_padding_x": 18,
                "active_word_padding_y": 8,
                "active_word_glow": blur}
        ass = build_ass(words, seg["start"], seg["end"], lay, knob)
        if blur:
            title = title_lines(seg.get("hook_title", ""), seg.get("hook", ""))
            lines = title.split(r"\N")[:2]
            if legacy_blur:
                bold = options.get("hook_title_style") == "bold_caps"
                if bold:
                    lines = [line.upper() for line in lines]
                for j, line in enumerate(lines):
                    ass += _event(0, seg["end"] - seg["start"], line, 540, 185 + j * 115,
                                  114 if bold else 86, font="Archivo Black" if bold else "Poppins",
                                  width=900, extra=r"\bord3\shad3") + "\n"
            else:
                sizes = []
                for line in lines:
                    size = 86
                    while size > 6 and metrik.lebar(line, "Poppins", size, True) > 840:
                        size -= 2
                    sizes.append(size)
                if options["hook_block"] == "white" and lines:
                    box_w = min(900, max(metrik.lebar(line, "Poppins", size, True)
                                         for line, size in zip(lines, sizes)) + 60)
                    box_h = 86 + (len(lines) - 1) * 115 + 56
                    x, y = round(540 - box_w / 2), 185 - 43 - 28
                    duration = seg["end"] - seg["start"]
                    ass += (f"Dialogue: 0,{_ts(0)},{_ts(duration)},Cap,,0,0,0,,"
                            f"{{\\an7\\pos({x},{y})\\p1\\1c&HFFFFFF&\\bord0\\shad0}}"
                            f"m 0 0 l {round(box_w)} 0 {round(box_w)} {box_h} 0 {box_h}{{\\p0}}\n")
                for j, (line, size) in enumerate(zip(lines, sizes)):
                    ass += _event(0, seg["end"] - seg["start"], line, 540, 185 + j * 115,
                                  size, font="Poppins", width=840,
                                  color="000000" if options["hook_block"] == "white" else "FFFFFF",
                                  extra=r"\bord0\shad0" if options["hook_block"] == "white" else r"\bord3\shad3",
                                  layer=1) + "\n"
        return ass
    return _motion(words, seg["start"], seg["end"], template_id, options, crop, set(emphasized))
