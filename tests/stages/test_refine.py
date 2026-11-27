"""Kontrak Stage 4: batas digeser ke jeda alami, tapi tidak pernah sampai
melanggar rentang durasi.
"""
import re

from pipeline.stages.refine import _PTS, _snap
from utils.ffmpeg_helpers import _SIL

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


# --- hening terpanjang menang atas hening terdekat ---
#
# Hening 1.5 detik adalah penutup gagasan; hening 0.3 detik cuma tarikan napas.
# Memilih berdasarkan kedekatan membuat tarikan napas yang kebetulan lebih dekat
# mengalahkan batas yang sebenarnya — dan klip terasa terpotong di tengah.

def test_hening_panjang_menang_walau_lebih_jauh():
    # Keduanya di dalam drift, jadi yang diuji benar-benar skornya:
    #   dekat+pendek : 0.3 - 0.5*0.1 = 0.25
    #   jauh+panjang : 1.5 - 0.5*0.9 = 1.05  <- menang
    sils = [(49.9, 50.2), (50.9, 52.4)]
    assert _snap(50.0, sils, [], "end", DRIFT) == 50.9


def test_hening_pendek_menang_kalau_yang_panjang_terlalu_jauh():
    """Durasi tidak boleh mengalahkan jarak yang keterlaluan.
       dekat+pendek : 0.35 - 0.5*0.05 =  0.325  <- menang
       jauh+panjang : 0.50 - 0.5*1.10 = -0.05
    """
    sils = [(49.7, 50.05), (50.6, 51.1)]
    assert _snap(50.0, sils, [], "start", DRIFT) == 50.05


def test_di_antara_dua_hening_sama_panjang_yang_terdekat_menang():
    # Durasi identik (1.0s), keduanya di dalam drift -> jarak jadi penentu.
    sils = [(48.5, 49.5), (49.7, 50.7)]
    assert _snap(50.0, sils, [], "start", DRIFT) == 49.5


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


def test_refine_menjaga_ucapan_dan_tetangga(monkeypatch, tmp_path):
    from pipeline.stages import refine
    from utils.ffmpeg_helpers import Deadline
    words = [{"s": 8.0, "e": 9.8}, {"s": 10.0, "e": 10.4},
             {"s": 69.6, "e": 70.0}, {"s": 70.2, "e": 72.0}]
    monkeypatch.setattr(refine, "silences", lambda *args: [])
    for cuts in ([10.5, 69.5], [9.0, 71.0]):
        monkeypatch.setattr(refine, "_scene_cuts", lambda *args: cuts)
        out = refine.run({"segments_raw": [{"start_idx": 1, "end_idx": 2}],
                          "words": words, "workdir": tmp_path, "deadline": Deadline(10),
                          "meta": {"duration": 100}, "audio": tmp_path / "audio", "source": tmp_path / "source"})
        clip = out["segments_final"][0]
        assert 9.8 <= clip["start"] <= 10.0
        assert 70.0 <= clip["end"] <= 70.2
        assert 30 <= clip["end"] - clip["start"] <= 90


def test_refine_padding_tidak_melanggar_batas_90(monkeypatch, tmp_path):
    from pipeline.stages import refine
    from utils.ffmpeg_helpers import Deadline
    monkeypatch.setattr(refine, "silences", lambda *args: [])
    monkeypatch.setattr(refine, "_scene_cuts", lambda *args: [])
    out = refine.run({"segments_raw": [{"start_idx": 0, "end_idx": 1}],
                      "words": [{"s": 1.0, "e": 1.4}, {"s": 90.6, "e": 91.0}],
                      "workdir": tmp_path, "deadline": Deadline(10), "meta": {"duration": 100},
                      "audio": tmp_path / "audio", "source": tmp_path / "source"})
    assert (out["segments_final"][0]["start"], out["segments_final"][0]["end"]) == (1.0, 91.0)


def test_scene_window_membatasi_input_sebelum_filter(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pipeline.stages import refine
    def ff(args, deadline, **kwargs):
        assert args.index("-t") < args.index("-i")
        assert args[args.index("-t") + 1] == "3.000"
        return SimpleNamespace(stderr="pts_time:0\npts_time:1.3")
    monkeypatch.setattr(refine, "ff", ff)
    assert refine._scene_cuts(tmp_path / "source.mp4", 10, None) == [9.8]
