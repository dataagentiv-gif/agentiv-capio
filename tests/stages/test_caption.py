"""Kontrak Stage 5: file .ass dengan timestamp RELATIF terhadap awal klip.

Ini titik paling rawan di seluruh pipeline. Kalau timestamp ditulis absolut,
render tetap sukses tanpa error apa pun — caption-nya saja yang tidak pernah
muncul, dan penyebabnya baru ketahuan setelah menonton hasil render.
"""
from pipeline.stages.caption import _ts, build_ass


def words(pairs):
    return [{"i": i, "w": w, "s": s, "e": e} for i, (w, s, e) in enumerate(pairs)]


def dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def parse_times(line: str) -> tuple[str, str]:
    parts = line.split(",")
    return parts[1], parts[2]


def to_sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_ts_format():
    assert _ts(0) == "0:00:00.00"
    assert _ts(65.5) == "0:01:05.50"
    assert _ts(3725.25) == "1:02:05.25"
    # Waktu negatif bisa muncul saat lead-in mendorong start ke belakang nol.
    assert _ts(-3.0) == "0:00:00.00"


def test_timestamp_relatif_terhadap_awal_klip():
    w = words([("satu", 100.0, 100.4), ("dua", 100.5, 100.9)])
    lines = dialogues(build_ass(w, clip_start=100.0, clip_end=101.0))
    assert lines, "tidak ada event Dialogue yang dihasilkan"
    first_start = to_sec(parse_times(lines[0])[0])
    assert first_start < 1.0, f"timestamp masih absolut: {first_start}"


def test_event_tidak_tumpang_tindih():
    """libass menggambar dua event yang tumpang tindih sekaligus, bertumpuk."""
    w = words([(f"k{i}", i * 0.5, i * 0.5 + 0.4) for i in range(12)])
    lines = dialogues(build_ass(w, clip_start=0.0, clip_end=6.0))
    times = [(to_sec(a), to_sec(b)) for a, b in map(parse_times, lines)]
    for (_, end), (nxt_start, _) in zip(times, times[1:]):
        assert nxt_start >= end - 1e-6, f"event bertumpuk: {end} > {nxt_start}"


def test_satu_kata_menyala_per_event():
    w = words([("aku", 0.0, 0.3), ("kamu", 0.4, 0.7), ("dia", 0.8, 1.1)])
    lines = dialogues(build_ass(w, clip_start=0.0, clip_end=2.0))
    for ln in lines:
        assert ln.count(r"{\c&H00E5FF&}") == 1, f"highlight bukan satu kata: {ln}"


def test_highlight_bergeser_mengikuti_urutan_kata():
    w = words([("aku", 0.0, 0.3), ("kamu", 0.4, 0.7), ("dia", 0.8, 1.1)])
    lines = dialogues(build_ass(w, clip_start=0.0, clip_end=2.0))
    # Semua kata tampil di tiap event; yang berpindah hanya posisi highlight.
    for i, expected in enumerate(["aku", "kamu", "dia"]):
        assert r"{\c&H00E5FF&}" + expected in lines[i]


def test_event_tidak_melewati_akhir_klip():
    w = words([("a", 0.0, 0.3), ("b", 4.5, 4.9)])
    lines = dialogues(build_ass(w, clip_start=0.0, clip_end=5.0))
    for _, end in map(parse_times, lines):
        assert to_sec(end) <= 5.0 + 1e-6


def test_kurawal_di_transkrip_tidak_merusak_baris():
    """Kurawal mentah akan ditafsirkan libass sebagai blok override."""
    w = words([("{halo}", 0.0, 0.4), ("dunia", 0.5, 0.9)])
    ass = build_ass(w, clip_start=0.0, clip_end=2.0)
    for ln in dialogues(ass):
        text = ln.split(",,", 1)[1]
        assert "{halo}" not in text
        # Yang tersisa cuma blok override warna milik kita sendiri.
        assert text.count("{") == text.count(r"{\c")


def test_header_resolusi_cocok_dengan_output_render():
    ass = build_ass(words([("x", 0.0, 0.4)]), 0.0, 1.0)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass


def test_kata_kosong_tidak_bikin_crash():
    assert dialogues(build_ass([], 0.0, 10.0)) == []
