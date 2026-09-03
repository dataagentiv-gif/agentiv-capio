"""Kontrak Stage 3: hanya segmen yang lolos validasi durasi boleh masuk refine.

Segmen di luar rentang tetap lolos validasi JSON tapi menghasilkan klip yang
terlalu pendek atau terlalu panjang saat render.
"""
from pipeline.stages.segment import (
    _anchors,
    _indexed_transcript,
    _snap_idx,
    _validate,
)

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


def test_tanpa_kalimat_jatuh_ke_mode_per_kata():
    """Fallback kalau Whisper tidak mengembalikan level kalimat."""
    lines = _indexed_transcript(WORDS[:25], []).splitlines()
    assert lines[0].startswith("[0] ")
    assert lines[1].startswith("[10] ")
    assert lines[2].startswith("[20] ")


# --- transkrip per kalimat: tanda baca + jeda ---
#
# Ini inti perbaikan titik potong. Tanpa tanda baca, kalimat menggantung
# terlihat sama seperti kalimat selesai; tanpa durasi jeda, tarikan napas
# terlihat sama seperti penutup gagasan.

SENT_WORDS = [
    {"i": i, "w": f"k{i}", "s": s, "e": s + 0.3}
    for i, s in enumerate([0.0, 0.4, 0.8, 3.0, 3.4, 3.8, 4.2, 4.6])
]
SENTENCES = [
    {"text": "Kelas menengah menuju kehancuran.", "s": 0.0, "e": 1.1},
    {"text": "Karena ada satu fenomena baru.", "s": 3.0, "e": 4.9},
]


def test_baris_memakai_teks_bertanda_baca_dari_kalimat():
    lines = _indexed_transcript(SENT_WORDS, SENTENCES).splitlines()
    assert "Kelas menengah menuju kehancuran." in lines[0]
    assert "Karena ada satu fenomena baru." in lines[1]


def test_jeda_panjang_ditandai():
    """1.9 detik antar kalimat harus terbaca LLM sebagai penutup gagasan."""
    lines = _indexed_transcript(SENT_WORDS, SENTENCES).splitlines()
    assert "(jeda 1.9s)" in lines[0]


def test_jeda_pendek_tidak_ditandai():
    """Di bawah ambang itu tarikan napas — menandainya cuma buang token."""
    rapat = [
        {"text": "Kalimat satu.", "s": 0.0, "e": 1.0},
        {"text": "Langsung nyambung.", "s": 1.1, "e": 2.0},
    ]
    assert "jeda" not in _indexed_transcript(SENT_WORDS, rapat).splitlines()[0]


def test_index_baris_menunjuk_kata_pertama_kalimat():
    lines = _indexed_transcript(SENT_WORDS, SENTENCES).splitlines()
    assert lines[0].startswith("[0 @")
    assert lines[1].startswith("[3 @")  # kata pertama kalimat kedua ada di t=3.0


# --- snap index ke batas kalimat ---

def test_anchors_menemukan_kata_pertama_tiap_kalimat():
    assert _anchors(SENT_WORDS, SENTENCES) == [0, 3]


def test_start_ditarik_ke_awal_kalimat():
    # 2 lebih dekat ke anchor 3 daripada ke 0.
    assert _snap_idx(2, [0, 3], 7, "start") == 3


def test_end_ditarik_ke_akhir_kalimat():
    """Akhir kalimat pertama = satu kata sebelum kalimat kedua mulai."""
    assert _snap_idx(2, [0, 3], 7, "end") == 2  # anchors[1]-1 == 2


def test_end_kalimat_terakhir_jatuh_ke_kata_terakhir():
    assert _snap_idx(7, [0, 3], 7, "end") == 7


def test_validate_menarik_batas_ke_kalimat():
    """Penjaga terakhir: walau LLM mengembalikan angka di tengah kalimat,
    yang keluar dari stage ini tetap batas kalimat."""
    anchors = [0, 60, 120, 200, 300]
    out = _validate([seg(58, 197)], WORDS, target=8, anchors=anchors)
    assert out and out[0]["start_idx"] == 60
    assert out[0]["end_idx"] == 199  # 200 - 1


def test_tanpa_anchors_index_tidak_diubah():
    out = _validate([seg(100, 220)], WORDS, target=8)
    assert out[0]["start_idx"] == 100 and out[0]["end_idx"] == 220


# --- jam di tiap baris ---
#
# Tanpa jam, LLM tidak punya cara menaksir durasi: saat tiap baris masih 10
# kata, jumlah baris jadi penggaris implisit, tapi begitu baris berubah jadi
# kalimat dengan panjang berbeda-beda penggaris itu hilang — dan model memilih
# rentang 8 detik untuk target 30-90 detik.

def test_mmss_format():
    from pipeline.stages.segment import _mmss

    assert _mmss(0) == "00:00"
    assert _mmss(65) == "01:05"
    assert _mmss(936) == "15:36"


def test_tiap_baris_mencantumkan_jam_mulai():
    lines = _indexed_transcript(SENT_WORDS, SENTENCES).splitlines()
    assert lines[0].startswith("[0 @ 00:00]")
    assert lines[1].startswith("[3 @ 00:03]")


# --- melebarkan kandidat yang kependekan ---
#
# Terukur di uji beban 8 video: dari 20 kandidat yang dibuang, SEMUANYA
# kependekan — nol yang kepanjangan, nol karena tumpang tindih. Membuangnya
# salah keputusan: LLM sudah menemukan momennya, cuma kurang lebar
# membingkainya. Satu video kehilangan 11 momen dan pulang dengan 1 klip.

# 400 kata, 2 kata/detik. Batas kalimat tiap 20 kata (= 10 detik).
ANCHORS = list(range(0, 400, 20))


def test_segmen_kependekan_dilebarkan_bukan_dibuang():
    """18 detik dulu dibuang; sekarang harus jadi klip yang layak."""
    out = _validate([seg(100, 136)], WORDS, target=8, anchors=ANCHORS)
    assert out, "kandidat kependekan masih dibuang"
    d = WORDS[out[0]["end_idx"]]["e"] - WORDS[out[0]["start_idx"]]["s"]
    assert 30 <= d <= 90


def test_pelebaran_mempertahankan_awal():
    """Tiga detik pertama adalah kail; memundurkan awal berarti menimpanya."""
    out = _validate([seg(100, 120)], WORDS, target=8, anchors=ANCHORS)
    assert out[0]["start_idx"] == 100
    assert out[0]["end_idx"] > 120


def test_awal_digeser_hanya_kalau_ujung_mentok():
    """Momen di ujung video tidak punya ruang maju, jadi awalnya yang mundur."""
    out = _validate([seg(392, 398)], WORDS, target=8, anchors=ANCHORS)
    assert out, "segmen di akhir video tidak berhasil dilebarkan"
    assert out[0]["start_idx"] < 392


def test_pelebaran_tidak_melewati_batas_atas():
    kandidat = [seg(0, 10), seg(200, 208)]
    for s in _validate(kandidat, WORDS, target=8, anchors=ANCHORS):
        d = WORDS[s["end_idx"]]["e"] - WORDS[s["start_idx"]]["s"]
        assert d <= 90, f"hasil pelebaran {d:.1f}s melewati batas"


def test_yang_kepanjangan_tetap_dibuang():
    """Pelebaran cuma untuk yang kurang; yang kelewat panjang tidak disentuh."""
    assert _validate([seg(0, 399)], WORDS, target=8, anchors=ANCHORS) == []


def test_tanpa_anchors_perilaku_lama_dipertahankan():
    """Tanpa daftar kalimat tidak ada acuan untuk melebarkan."""
    assert _validate([seg(100, 136)], WORDS, target=8) == []


# --- sebaran skor ---
#
# Skor menentukan DUA keputusan di _validate: pemenang saat tumpang tindih, dan
# siapa yang dipotong saat kandidat lebih banyak dari target. Skor yang
# berdekatan membuat keduanya praktis acak, dan itu tidak terlihat dari mana pun
# kecuali angka ini. Terukur sebelum patokan nilai ditambahkan ke prompt: 56
# klip seluruhnya jatuh di rentang 78-96.

def test_sebaran_menyebut_rentang():
    from pipeline.stages.segment import _sebaran

    assert _sebaran([78, 90, 96]) == "78-96 (rentang 18)"


def test_sebaran_skor_seragam_terlihat_nol():
    """Inilah gejala yang dicari: rentang 0 berarti skor tidak membedakan
    apa pun, dan pemilihan kandidat jadi asal."""
    from pipeline.stages.segment import _sebaran

    assert "rentang 0" in _sebaran([88, 88, 88])


def test_sebaran_kosong_tidak_bikin_crash():
    from pipeline.stages.segment import _sebaran

    assert _sebaran([]) == "-"


def test_prompt_menyebut_patokan_nilai():
    """Regresi: prompt sempat cuma menulis '0-100, seberapa yakin kamu', dan
    model membalas dengan skor yang menumpuk di ujung atas."""
    from pipeline.stages.segment import PROMPT

    assert "90-100" in PROMPT and "30-49" in PROMPT
    assert "SELURUH RENTANG" in PROMPT
