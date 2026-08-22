"""Kontrak Stage 3: hanya segmen yang lolos validasi durasi boleh masuk refine.

Segmen di luar rentang tetap lolos validasi JSON tapi menghasilkan klip yang
terlalu pendek atau terlalu panjang saat render.
"""
from pipeline.stages.segment import _indexed_transcript, _validate

# 2 kata per detik selama 200 detik.
WORDS = [{"i": i, "w": f"k{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(400)]


def seg(a, b, score=80):
    return {"start_idx": a, "end_idx": b, "hook": "h", "reason": "r", "score": score}


def test_durasi_di_luar_rentang_dibuang():
    kandidat = [
        seg(0, 20),      # 10 detik  -> terlalu pendek
        seg(100, 220),   # 60 detik  -> lolos
        seg(230, 399),   # ~85 detik -> lolos
        seg(0, 399),     # ~200 detik -> terlalu panjang
    ]
    out = _validate(kandidat, WORDS, target=8)
    assert len(out) == 2
    for s in out:
        d = WORDS[s["end_idx"]]["e"] - WORDS[s["start_idx"]]["s"]
        assert 30 <= d <= 90


def test_end_idx_harus_lebih_besar_dari_start_idx():
    assert _validate([seg(200, 100), seg(50, 50)], WORDS, target=8) == []


def test_tumpang_tindih_dibuang_skor_tertinggi_menang():
    out = _validate([seg(0, 100, score=60), seg(50, 150, score=95)], WORDS, target=8)
    assert len(out) == 1
    assert out[0]["score"] == 95


def test_hasil_dibatasi_target_clips():
    kandidat = [seg(i * 130, i * 130 + 120, score=90 - i) for i in range(3)]
    assert len(_validate(kandidat, WORDS, target=2)) == 2


def test_hasil_urut_berdasarkan_waktu():
    kandidat = [seg(230, 350, score=70), seg(0, 120, score=99)]
    out = _validate(kandidat, WORDS, target=8)
    assert [s["start_idx"] for s in out] == sorted(s["start_idx"] for s in out)


def test_index_di_luar_jangkauan_di_clamp_bukan_bikin_crash():
    """LLM sesekali mengarang index melebihi panjang transkrip."""
    out = _validate([seg(100, 99_999)], WORDS, target=8)
    assert all(s["end_idx"] <= len(WORDS) - 1 for s in out)


def test_field_rusak_dilewati_diam_diam():
    kandidat = [
        {"start_idx": "bukan angka", "end_idx": 100, "score": 50},
        {"hook": "tanpa index sama sekali"},
        seg(100, 220),
    ]
    assert len(_validate(kandidat, WORDS, target=8)) == 1


def test_score_di_clamp_ke_0_100():
    out = _validate([seg(100, 220, score=999)], WORDS, target=8)
    assert out[0]["score"] == 100


def test_transkrip_ber_index_menandai_index_kata_pertama_tiap_baris():
    lines = _indexed_transcript(WORDS[:25]).splitlines()
    assert lines[0].startswith("[0] ")
    assert lines[1].startswith("[10] ")
    assert lines[2].startswith("[20] ")
