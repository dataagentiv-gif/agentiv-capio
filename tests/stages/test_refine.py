"""Kontrak Stage 4: batas digeser ke jeda alami, tapi tidak pernah sampai
melanggar rentang durasi.
"""
import re

from pipeline.stages.refine import _PTS, _SIL, _snap

DRIFT = 1.2
# (mulai, selesai) tiap hening.
SILS = [(9.5, 10.2), (68.0, 69.1), (200.0, 201.0)]


def test_start_digeser_ke_akhir_hening():
    """Klip harus MULAI sesaat setelah jeda selesai, bukan saat jeda dimulai."""
    assert _snap(10.4, SILS, [], "start", DRIFT) == 10.2


def test_end_digeser_ke_awal_hening():
    """Klip harus BERHENTI tepat saat jeda berikutnya dimulai."""
    assert _snap(67.6, SILS, [], "end", DRIFT) == 68.0


def test_potongan_visual_menang_atas_jeda_audio():
    """Pergantian shot adalah batas yang lebih kuat daripada jeda bicara."""
    assert _snap(10.4, SILS, [10.35], "start", DRIFT) == 10.35


def test_tidak_ada_kandidat_dalam_drift_maka_tidak_digeser():
    """Batas yang tidak di-snap masih menghasilkan klip layak; batas yang
    di-snap ke hening yang jauh justru merusak."""
    assert _snap(50.0, SILS, [], "start", DRIFT) == 50.0


def test_kandidat_di_luar_drift_diabaikan():
    assert _snap(10.4, SILS, [14.0], "start", DRIFT) == 10.2


def test_kandidat_terdekat_yang_dipilih():
    assert _snap(10.0, [(5.0, 9.4)], [9.6, 12.0], "start", DRIFT) == 9.6


def test_tanpa_hening_sama_sekali_batas_dipakai_apa_adanya():
    assert _snap(42.0, [], [], "start", DRIFT) == 42.0


def test_parser_silencedetect_membaca_format_stderr_ffmpeg():
    stderr = (
        "[Parsed_silencedetect_0 @ 0000021a] silence_start: 9.5\n"
        "[Parsed_silencedetect_0 @ 0000021a] silence_end: 10.2 | silence_duration: 0.7\n"
    )
    assert _SIL.findall(stderr) == [("start", "9.5"), ("end", "10.2")]


def test_parser_scene_membaca_pts_time():
    stderr = (
        "[Parsed_metadata_2 @ 00000218] frame:0    pts:1000000 pts_time:1\n"
        "[Parsed_metadata_2 @ 00000218] lavfi.scene_score=1.000000\n"
        "[Parsed_metadata_2 @ 00000218] frame:9    pts:1300000 pts_time:1.3\n"
    )
    assert _PTS.findall(stderr) == ["1", "1.3"]


def test_regex_silence_toleran_terhadap_spasi():
    assert _SIL.findall("silence_start:0\n")[0] == ("start", "0")
