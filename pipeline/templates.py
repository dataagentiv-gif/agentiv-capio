"""Kontrak tunggal library template; nilai yang tersimpan selalu lengkap."""
import re

TEMPLATES = {
    "mentahan": {"title": "Mentahan", "description": "Potongan asli tanpa crop dan caption.",
                 "visual": {"canvas": "source", "caption_zone": None}, "defaults": {}},
    "full_screen": {"title": "Full Screen", "description": "Video vertikal penuh dengan caption aktif.",
                    "visual": {"canvas": "1080x1920", "panel_height": 1920, "caption_zone": "bawah"},
                    "defaults": {"caption_style": "text_color", "active_text_color": "FFE500"}},
    "pembicara_samping": {"title": "Pembicara di samping", "description": "Pembicara dan caption editorial berseberangan.",
                           "visual": {"canvas": "1080x1920", "panel_height": 800, "caption_zone": "lawan_pembicara",
                                      "background": "hitam", "gradient": [0.36, 0.84]},
                           "defaults": {"caption_motion": "soft_focus"},
                           "motion_options": ["soft_focus", "kinetic_words", "editorial_focus"]},
    "blur_atas_bawah": {"title": "Blur atas-bawah", "description": "Judul di atas, ucapan di bawah.",
                        "visual": {"canvas": "1080x1920", "panel_height": 930, "background": "blur_source",
                                   "caption_zone": "blur_bawah", "hook_zone": "blur_atas"},
                        "defaults": {"hook_block": "none", "caption_style": "text_color",
                                     "active_text_color": "FFE500"}},
    "kotak_tengah": {"title": "Kotak tengah", "description": "Kartu video dengan caption di dalamnya.",
                     "visual": {"canvas": "1080x1920", "panel_height": 950, "radius": 64,
                                "background": "hitam", "caption_zone": "dalam_kartu"},
                     "defaults": {"caption_motion": "single_word_float"},
                     "motion_options": ["single_word_float", "soft_phrase", "scatter_emphasis"]},
}
STYLES = {"text_color", "background", "background_scale"}
MOTIONS = {key: set(value["motion_options"]) for key, value in TEMPLATES.items()
           if "motion_options" in value}
HEX = re.compile(r"#?[0-9a-fA-F]{6}\Z")


def resolve(template_id: str, adjustments: dict | None) -> dict:
    """Tolak seluruh konfigurasi yang tidak bermakna, termasuk warna dormant."""
    if template_id not in TEMPLATES:
        raise ValueError("Template tidak dikenal atau Custom belum tersedia")
    if not isinstance(adjustments, dict):
        raise ValueError("adjustments harus berupa objek")
    result = {**TEMPLATES[template_id]["defaults"], **adjustments}
    allowed = set(TEMPLATES[template_id]["defaults"])
    style = result.get("caption_style")
    motion = result.get("caption_motion")
    if template_id in ("full_screen", "blur_atas_bawah"):
        if style not in STYLES:
            raise ValueError("Gaya caption tidak dikenal")
        if style != "text_color":
            allowed.add("active_background_color")
            result.setdefault("active_background_color", "FFE500")
            if "active_text_color" not in adjustments:
                result["active_text_color"] = "000000"
    if template_id in MOTIONS and motion not in MOTIONS[template_id]:
        raise ValueError("Motion caption tidak sesuai template")
    if template_id == "blur_atas_bawah" and result["hook_block"] not in {"none", "white"}:
        raise ValueError("Blok hook tidak dikenal")
    if template_id == "kotak_tengah" and motion == "scatter_emphasis":
        allowed.add("scatter_accent_color")
        result.setdefault("scatter_accent_color", "FFE500")
    extra = set(result) - allowed
    if extra:
        raise ValueError(f"Adjustment tidak berlaku untuk {template_id}: {', '.join(sorted(extra))}")
    for key, value in result.items():
        if key.endswith("_color"):
            if not isinstance(value, str) or not HEX.fullmatch(value):
                raise ValueError(f"{key} harus warna #RRGGBB")
            result[key] = value.lstrip("#").upper()
    return result
