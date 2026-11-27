"""Kontrak Stage 3: hanya segmen yang lolos validasi durasi boleh masuk refine.

Segmen di luar rentang tetap lolos validasi JSON tapi menghasilkan klip yang
terlalu pendek atau terlalu panjang saat render.
"""
from pipeline.stages.segment import (
    _anchor_kalimat,
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


def test_index_di_luar_jangkauan_ditolak_bukan_bikin_crash():
    """LLM sesekali mengarang index melebihi panjang transkrip."""
    out = _validate([seg(100, 99_999)], WORDS, target=8)
    assert out == []


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
    assert lines[0].startswith("[0 @ ")
    assert lines[1].startswith("[10 @ ")
    assert lines[2].startswith("[20 @ ")


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


# --- label baris harus sejajar dengan kalimatnya ---
#
# Ini kesalahan yang paling lama tidak ketahuan di project ini, dan selama
# berbulan-bulan dikira kelemahan LLM pada masukan besar. _indexed_transcript
# dulu mengambil labelnya dari _anchors, yang membuang duplikat lewat set().
# Begitu DUA kalimat jatuh di kata yang sama, daftarnya jadi lebih pendek dari
# daftar kalimat — dan sejak titik itu tiap baris membawa label milik kalimat
# BERIKUTNYA, menumpuk sampai akhir transkrip.
#
# Terukur pada podcast 27 menit: 540 kalimat, 538 anchor, 518 baris (96%) salah
# label, meleset 3-20 detik ke depan. Sesudah diperbaiki: 0 salah.

BENTROK_WORDS = [
    {"i": i, "w": f"k{i}", "s": s, "e": s + 0.3}
    for i, s in enumerate([0.0, 0.4, 2.0, 2.4, 5.0, 5.4, 8.0, 8.4])
]
#: Kalimat #1 dan #2 sengaja jatuh di kata yang sama (keduanya mulai ~2.0s).
#: Ini lazim terjadi: ASR memberi dua kalimat pendek timestamp nyaris identik.
BENTROK_SENTENCES = [
    {"text": "Kalimat nol.", "s": 0.0, "e": 1.0},
    {"text": "Kalimat satu.", "s": 2.0, "e": 2.2},
    {"text": "Kalimat dua.", "s": 2.02, "e": 4.0},
    {"text": "Kalimat tiga.", "s": 5.0, "e": 7.0},
    {"text": "Kalimat empat.", "s": 8.0, "e": 9.0},
]


def test_jumlah_baris_sama_dengan_jumlah_kalimat_walau_ada_bentrokan():
    lines = _indexed_transcript(BENTROK_WORDS, BENTROK_SENTENCES).splitlines()
    assert len(lines) == len(BENTROK_SENTENCES)


def test_label_tidak_bergeser_sesudah_bentrokan():
    """Inti bugnya. Sebelum diperbaiki, kalimat "tiga" dan "empat" membawa label
    milik kalimat sesudahnya — dan klip yang keluar diambil dari menit yang
    salah tanpa satu pun error."""
    lines = _indexed_transcript(BENTROK_WORDS, BENTROK_SENTENCES).splitlines()
    for baris, harusnya in zip(lines, [0, 2, 2, 4, 6]):
        assert baris.startswith(f"[{harusnya} @"), baris


def test_label_menunjuk_kata_yang_benar_benar_mengucapkannya():
    """Diperiksa dari sisi isi, bukan dari angka: kata di posisi label harus
    mulai pada waktu yang sama dengan kalimatnya."""
    idx = _anchor_kalimat(BENTROK_WORDS, BENTROK_SENTENCES)
    for n, s in enumerate(BENTROK_SENTENCES):
        assert abs(BENTROK_WORDS[idx[n]]["s"] - s["s"]) < 0.5


def test_anchor_kalimat_sejajar_satu_satu_dengan_kalimat():
    assert len(_anchor_kalimat(BENTROK_WORDS, BENTROK_SENTENCES)) == len(BENTROK_SENTENCES)


def test_anchors_tetap_unik_untuk_batas_klip():
    """Dua peran yang berbeda dan keduanya benar: label baris boleh berulang,
    tapi daftar posisi yang sah jadi batas klip tidak boleh punya duplikat —
    _snap_idx dan _cari_hook memindainya satu per satu."""
    a = _anchors(BENTROK_WORDS, BENTROK_SENTENCES)
    assert a == sorted(set(a))
    assert a == [0, 2, 4, 6]


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

    assert _mmss(0) == "00:00.0"
    assert _mmss(65) == "01:05.0"
    assert _mmss(936) == "15:36.0"


def test_tiap_baris_mencantumkan_jam_mulai():
    lines = _indexed_transcript(SENT_WORDS, SENTENCES).splitlines()
    assert lines[0].startswith("[0 @ 00:00.0-00:01.1 | end_idx=2]")
    assert lines[1].startswith("[3 @ 00:03.0-00:04.9 | end_idx=7]")


# Kandidat pendek harus dikoreksi berdasarkan isi, bukan dilebarkan otomatis.
ANCHORS = list(range(0, 400, 20))


def test_kandidat_pendek_tidak_ditambahi_ucapan():
    rejected = []
    assert _validate([seg(100, 136), seg(392, 398)], WORDS, 8, ANCHORS, rejected) == []
    assert [r["reason"] for r in rejected] == ["too_short", "too_short"]
    assert all(r["duration"] < 30 for r in rejected)


def test_diagnostik_indeks_durasi_dan_overlap():
    rejected = []
    out = _validate([seg(-1, 100), seg(0, 399), seg(100, 220, 90), seg(110, 230, 80)], WORDS, 8, None, rejected)
    assert len(out) == 1
    assert {r["reason"] for r in rejected} == {"invalid_indices", "too_long", "overlap"}


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


def test_balasan_kosong_dicoba_ulang(monkeypatch, tmp_path):
    """Satu jawaban kosong dari LLM tidak boleh menggagalkan video panjang."""
    from pipeline.stages import segment

    balasan = iter([
        {"segments": []},
        {"segments": [seg(100, 220)]},
    ])
    panggilan = []

    def llm(prompt, schema):
        panggilan.append(prompt)
        return next(balasan)

    monkeypatch.setattr(segment, "call_llm", llm)
    out = segment.run({
        "words": WORDS,
        "sentences": [],
        "target_clips": 1,
        "workdir": tmp_path,
    })

    assert len(panggilan) == 2
    assert "KOREKSI SATU KALI" in panggilan[1]
    assert "jangan memaksakan jumlah" in panggilan[1]
    assert len(out["segments_raw"]) == 1


# --- hook menang atas index ---
#
# LLM mengembalikan dua hal yang menunjuk momen yang sama: `hook` (kalimat
# pembukanya) dan `start_idx` (angkanya). Pada transkrip panjang keduanya bisa
# bertentangan. Terjadi sungguhan pada podcast 2,4 jam — 3.528 kalimat jadi satu
# prompt, dan klip yang keluar berisi kalimat yang sama sekali lain dari hook
# yang dikutip; video pendek tidak pernah bermasalah. Kegagalannya senyap:
# klipnya tetap terlihat wajar, cuma diambil dari menit yang salah.

# 400 kata "k0..k399", batas kalimat tiap 20 kata.
KATA_UNIK = [
    {"i": i, "w": f"k{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(400)
]
ANCH = list(range(0, 400, 20))


def seg_hook(a, b, hook, score=90):
    return {"start_idx": a, "end_idx": b, "hook": hook, "reason": "r", "score": score}


def test_index_salah_dipindah_ke_posisi_hook():
    """Inti perbaikannya: isi menang atas aritmetika."""
    kandidat = [seg_hook(100, 300, "k200 k201 k202 k203 k204")]
    out = _validate(kandidat, KATA_UNIK, target=8, anchors=ANCH)
    assert out and out[0]["start_idx"] == 200, "klip tidak dipindah ke posisi hook"


def test_koreksi_hook_tidak_menggeser_kesimpulan():
    out = _validate([seg_hook(180, 300, "k200 k201 k202 k203 k204")],
                    KATA_UNIK, target=8, anchors=ANCH)
    assert out[0]["start_idx"] == 200
    assert out[0]["end_idx"] == 299


def test_hook_setelah_penutup_ditolak_untuk_koreksi_model():
    rejected = []
    assert _validate([seg_hook(0, 100, "k200 k201 k202 k203 k204")],
                     KATA_UNIK, 8, ANCH, rejected) == []
    assert rejected[0]["reason"] == "invalid_indices"


def test_index_yang_sudah_cocok_tidak_diganggu():
    """Video pendek tidak pernah bermasalah; jangan sampai jadi bermasalah."""
    out = _validate([seg_hook(100, 200, "k100 k101 k102 k103")],
                    KATA_UNIK, target=8, anchors=ANCH)
    assert out[0]["start_idx"] == 100


def test_hook_yang_tidak_ditemukan_membiarkan_index_apa_adanya():
    """Kalau hook tidak ada di transkrip sama sekali, menebak posisinya lebih
    berbahaya daripada mempercayai index."""
    out = _validate([seg_hook(100, 200, "kalimat yang tidak pernah diucapkan sama sekali")],
                    KATA_UNIK, target=8, anchors=ANCH)
    assert out[0]["start_idx"] == 100


def test_hook_terlalu_pendek_tidak_dipakai_menggeser():
    """Dua kata bisa cocok di banyak tempat secara kebetulan."""
    out = _validate([seg_hook(100, 200, "k380")], KATA_UNIK, target=8, anchors=ANCH)
    assert out[0]["start_idx"] == 100


def test_tanpa_anchors_tidak_ada_pemindahan():
    """Tanpa daftar kalimat tidak ada posisi sah untuk dituju."""
    out = _validate([seg_hook(0, 100, "k200 k201 k202 k203")], KATA_UNIK, target=8)
    assert out[0]["start_idx"] == 0


def test_koreksi_kandidat_panjang_mempertahankan_valid(monkeypatch, tmp_path):
    import json
    from pipeline.stages import segment
    calls = []
    replies = iter([{"segments": [seg(0, 100, 60), seg(150, 399)]},
                    {"segments": [seg(0, 120, 99), seg(150, 280, 70)]}])
    def llm(prompt, schema):
        calls.append(prompt)
        return next(replies)
    monkeypatch.setattr(segment, "call_llm", llm)
    out = segment.run({"words": WORDS, "target_clips": 3, "workdir": tmp_path})
    assert len(calls) == 2
    assert [(s["start_idx"], s["end_idx"]) for s in out["segments_raw"]] == [(0, 100), (150, 280)]
    report = json.loads((tmp_path / "segment_diagnostics.json").read_text())
    assert report[0]["rejected"][0]["reason"] == "too_long"
    assert report[1]["rejected"][0]["reason"] == "overlap"


def test_dua_balasan_kosong_tetap_berhenti(monkeypatch, tmp_path):
    import json
    import pytest
    from pipeline.stages import segment
    calls = []
    def llm(prompt, schema):
        calls.append(prompt)
        return {"segments": []}
    monkeypatch.setattr(segment, "call_llm", llm)
    with pytest.raises(RuntimeError, match="kandidat kosong"):
        segment.run({"words": WORDS, "target_clips": 5, "workdir": tmp_path})
    assert len(calls) == 2
    assert len(json.loads((tmp_path / "segment_diagnostics.json").read_text())) == 2


def test_target_tercapai_tidak_memanggil_koreksi(monkeypatch, tmp_path):
    from pipeline.stages import segment
    calls = []
    def llm(prompt, schema):
        calls.append(prompt)
        return {"segments": [seg(0, 100)]}
    monkeypatch.setattr(segment, "call_llm", llm)
    assert len(segment.run({"words": WORDS, "target_clips": 1, "workdir": tmp_path})["segments_raw"]) == 1
    assert len(calls) == 1


def test_kegagalan_koreksi_tetap_menghasilkan_kandidat_awal(monkeypatch, tmp_path):
    from pipeline.stages import segment
    calls = []
    def llm(prompt, schema):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("Gemini quota exhausted")
        return {"segments": [seg(0, 100)]}
    monkeypatch.setattr(segment, "call_llm", llm)
    assert len(segment.run({"words": WORDS, "target_clips": 5, "workdir": tmp_path})["segments_raw"]) == 1
    assert len(calls) == 2


def test_pembatalan_sebelum_koreksi_tidak_ditelan(monkeypatch, tmp_path):
    import pytest
    from pipeline.stages import segment
    from utils.ffmpeg_helpers import JobCancelled
    class Deadline:
        def check(self, stage):
            if calls:
                raise JobCancelled("cancel")
    calls = []
    def llm(prompt, schema):
        calls.append(prompt)
        return {"segments": [seg(0, 100)]}
    monkeypatch.setattr(segment, "call_llm", llm)
    with pytest.raises(JobCancelled):
        segment.run({"words": WORDS, "target_clips": 5, "workdir": tmp_path, "deadline": Deadline()})
    assert len(calls) == 1
    assert (tmp_path / "segment_diagnostics.json").exists()


def test_diagnostik_job_bertahan_di_data_dir(monkeypatch, tmp_path):
    import json
    from pipeline.stages import segment
    data = tmp_path / "data"
    monkeypatch.setattr(segment.settings, "DATA_DIR", data)
    monkeypatch.setattr(segment, "call_llm", lambda *args: {"segments": [seg(0, 100)]})
    segment.run({"job_id": "test-job", "words": WORDS, "target_clips": 1, "workdir": tmp_path})
    assert json.loads((data / "pipeline_diagnostics" / "test-job.json").read_text())[0]["accepted"]
