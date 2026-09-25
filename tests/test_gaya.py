"""Adjustment job baru selalu hanya milik template yang dipilih."""
import pytest
from pydantic import ValidationError

from api.schemas import JobCreate

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def job(template_id, **adjustments):
    return JobCreate(url=URL, template_id=template_id, adjustments=adjustments)


def test_warna_blok_tersimpan_untuk_gaya_blok():
    assert job("full_screen", caption_style="background", active_background_color="#FF0000").adjustments["active_background_color"] == "FF0000"


def test_warna_blok_ditolak_untuk_gaya_teks():
    with pytest.raises(ValidationError):
        job("full_screen", active_background_color="#FF0000")


def test_sisi_pembicara_bukan_adjustment():
    with pytest.raises(ValidationError):
        job("pembicara_samping", speaker_side="kanan")


def test_parameter_global_lama_ditolak():
    with pytest.raises(ValidationError):
        job("full_screen", ukuran=120)
