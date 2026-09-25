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

CUSTOM_DEFAULTS = {
    "output_ratio": "9:16", "video_mode": "full", "panel_ratio": "16:9",
    "panel_size": "medium", "panel_radius": "rounded", "fit_mode": "crop",
    "focus_mode": "face", "background": "black", "background_color": "101820",
    "caption": True, "caption_position": 0.78, "caption_font": "Poppins",
    "caption_size": "medium", "caption_words": 3, "caption_upper": False,
    "caption_style": "text_color", "active_text_color": "FFE500",
    "active_background_color": "FFE500", "hook": False, "hook_block": "none",
}
CUSTOM_ENUMS = {
    "output_ratio": {"9:16", "1:1", "16:9"}, "video_mode": {"full", "panel"},
    "panel_ratio": {"9:16", "1:1", "16:9"}, "panel_size": {"small", "medium", "large"},
    "panel_radius": {"square", "rounded"}, "fit_mode": {"crop", "contain"},
    "focus_mode": {"face", "center"}, "background": {"black", "solid", "blur"},
    "caption_font": {"Poppins", "Archivo Black", "Anton", "Lora"},
    "caption_size": {"small", "medium", "large"}, "caption_style": STYLES,
    "hook_block": {"none", "white"},
}


def resolve(template_id: str, adjustments: dict | None) -> dict:
    """Tolak seluruh konfigurasi yang tidak bermakna, termasuk warna dormant."""
    if template_id == "custom":
        if not isinstance(adjustments, dict):
            raise ValueError("adjustments harus berupa objek")
        result = {**CUSTOM_DEFAULTS, **adjustments}
        extra = set(result) - set(CUSTOM_DEFAULTS)
        if extra:
            raise ValueError(f"Adjustment tidak berlaku untuk Custom: {', '.join(sorted(extra))}")
        for key, allowed in CUSTOM_ENUMS.items():
            if result[key] not in allowed:
                raise ValueError(f"{key} tidak dikenal untuk Custom")
        if not isinstance(result["caption"], bool) or not isinstance(result["hook"], bool):
            raise ValueError("caption dan hook harus boolean")
        if not isinstance(result["caption_upper"], bool):
            raise ValueError("caption_upper harus boolean")
        if result["caption_words"] not in {1, 2, 3, 4}:
            raise ValueError("caption_words harus 1 sampai 4")
        try:
            result["caption_position"] = max(0.08, min(0.92, float(result["caption_position"])))
        except (TypeError, ValueError):
            raise ValueError("caption_position harus angka 0.08 sampai 0.92") from None
        for key in ("background_color", "active_text_color", "active_background_color"):
            if not isinstance(result[key], str) or not HEX.fullmatch(result[key]):
                raise ValueError(f"{key} harus warna #RRGGBB")
            result[key] = result[key].lstrip("#").upper()
        return result
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
