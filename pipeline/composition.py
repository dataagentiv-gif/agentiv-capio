"""Geometri template dan filter FFmpeg; tidak berisi keputusan motion caption."""
from types import SimpleNamespace
from pathlib import Path
from pipeline.templates import TEMPLATES

W, H = 1080, 1920
FONT_DIR = str(Path(__file__).resolve().parents[1] / "assets" / "fonts").replace("\\", "/").replace(":", "\\:")


def _panel(src_w, src_h, out_w, out_h, crop, face_x=0.5):
    """Isi panel tanpa stretch; source sempit mendapat bar hitam."""
    target = out_w / out_h
    if src_w / src_h < target:
        return (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    cw = max(2, min(src_w, int(src_h * target)) & ~1)
    fx = crop.get("fx")
    cx = max(0, min(src_w - cw, int((0.5 if fx is None else fx) * src_w - cw * face_x))) & ~1
    return f"crop={cw}:{src_h}:{cx}:0,scale={out_w}:{out_h},setsar=1"


def filters(template_id, crop, src_w, src_h, ass, workdir, deadline):
    """Kembalikan filter dan apakah ia memakai -filter_complex."""
    if template_id == "mentahan":
        return "", False
    if template_id == "custom":
        return _custom_filters(crop, src_w, src_h, ass, workdir, deadline)
    subtitle = f",subtitles={ass}:fontsdir='{FONT_DIR}'" if ass else ""
    if template_id == "full_screen":
        return _panel(src_w, src_h, W, H, crop) + subtitle, False
    if template_id == "blur_atas_bawah":
        panel_h = TEMPLATES[template_id]["visual"]["panel_height"]
        sharp = _panel(src_w, src_h, W, panel_h, crop)
        graph = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,gblur=sigma=35,eq=brightness=-0.22[back];"
            f"[fg]{sharp}[panel];"
            f"[back][panel]overlay=0:{(H-panel_h)//2}{subtitle}[outv]"
        )
        return graph, True
    if template_id == "pembicara_samping":
        visual = TEMPLATES[template_id]["visual"]
        panel_h, radius = visual["panel_height"], 0
        side = crop.get("speaker_side", "kiri")
        face_x = (0.28 if side == "kiri" else 0.72) if crop.get("fx") is not None else 0.5
        dark = "kanan" if side == "kiri" else "kiri"
        opacity = tuple(visual["gradient"])
    elif template_id == "kotak_tengah":
        visual = TEMPLATES[template_id]["visual"]
        panel_h, radius, dark, opacity = visual["panel_height"], visual["radius"], "kanan", None
        face_x = 0.5
    else:
        raise ValueError("Template render tidak dikenal")
    from pipeline.stages.render import _mask

    top = (H - panel_h) // 2
    lay = SimpleNamespace(radius=radius, redup=opacity, redup_sisi=dark)
    mask = _mask(workdir, lay, {"bw": W, "bh": panel_h, "bx": 0, "by": top}, deadline)
    # Dua input filter tidak bisa digabung sebagai rantai -vf biasa.
    base = (_panel(src_w, src_h, W, panel_h, crop, face_x)
            + f",pad={W}:{H}:0:{top}:black[v];movie={mask}[m];"
            + f"[v][m]overlay=0:0{subtitle}[outv]")
    return base, True


def _custom_filters(crop, src_w, src_h, ass, workdir, deadline):
    from pipeline.custom import output_size, panel_size
    options = crop.get("custom_options") or {}
    out_w, out_h = output_size(options)
    subtitle = f",subtitles={ass}:fontsdir='{FONT_DIR}'" if ass else ""
    fx = crop.get("fx") if options["focus_mode"] == "face" else None
    fit = options["fit_mode"]
    bg = options["background_color"]
    if options["background"] == "black":
        bg = "000000"
    color = f"color=c=0x{bg}:s={out_w}x{out_h}:r=30"
    x_expr = f"{fx}*iw-{out_w}/2" if fx is not None else f"(iw-{out_w})/2"
    x_expr = x_expr.replace(",", "\\,")
    source = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h}:" \
             f"max(0\\,min(iw-{out_w}\\,{x_expr})):" \
             f"max(0\\,min(ih-{out_h}\\,(ih-{out_h})/2))[fill]"
    if fit == "contain":
        front = (f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                 f"format=rgba[front]")
    else:
        front = source.replace("[fill]", "[front]")
    if options["video_mode"] == "full":
        if fit == "crop":
            return source.replace("[fill]", f"{subtitle}[outv]"), True
        if options["background"] == "blur":
            graph = (f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                     f"gblur=sigma=35[back];{front};[back][front]overlay=(W-w)/2:(H-h)/2{subtitle}[outv]")
        else:
            graph = f"{color}[back];{front};[back][front]overlay=(W-w)/2:(H-h)/2{subtitle}[outv]"
        return graph, True
    panel_w, panel_h = panel_size(options, out_w, out_h)
    px, py = (out_w - panel_w) // 2, (out_h - panel_h) // 2
    if fit == "crop":
        panel_x = f"{fx}*iw-{panel_w}/2" if fx is not None else f"(iw-{panel_w})/2"
        panel_x = panel_x.replace(",", "\\,")
        panel = (f"[0:v]scale={panel_w}:{panel_h}:force_original_aspect_ratio=increase,"
                 f"crop={panel_w}:{panel_h}:max(0\\,min(iw-{panel_w}\\,{panel_x})):"
                 f"max(0\\,min(ih-{panel_h}\\,(ih-{panel_h})/2))[front]")
    else:
        panel = (f"[0:v]scale={panel_w}:{panel_h}:force_original_aspect_ratio=decrease,"
                 f"pad={panel_w}:{panel_h}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgba[front]")
    if options["background"] == "blur":
        base = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},gblur=sigma=35[back]"
    else:
        base = f"{color}[back]"
    if options["panel_radius"] == "rounded":
        from PIL import Image, ImageDraw
        mask_path = workdir / f"custom-mask-{panel_w}x{panel_h}.png"
        if not mask_path.exists():
            mask = Image.new("L", (panel_w, panel_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, panel_w - 1, panel_h - 1),
                                                    radius=max(12, min(panel_w, panel_h) // 16), fill=255)
            mask.save(mask_path)
        graph = f"{base};{panel};movie={mask_path.name}[pm];[front][pm]alphamerge[panel];[back][panel]overlay={px}:{py}{subtitle}[outv]"
    else:
        graph = f"{base};{panel};[back][front]overlay={px}:{py}{subtitle}[outv]"
    return graph, True
