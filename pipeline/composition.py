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
