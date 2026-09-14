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


# --- gaya kata aktif: blok ---

import re  # noqa: E402
from dataclasses import replace  # noqa: E402

from pipeline import layout as L  # noqa: E402
from pipeline.stages.caption import _pil, _tata  # noqa: E402

TIGA = words([("aku", 0.0, 0.3), ("kamu", 0.4, 0.7), ("dia", 0.8, 1.1)])
BLOK = {"active_word_style": "background"}
POS = re.compile(r"\\pos\((-?\d+),(-?\d+)\)")


def per_waktu(ass: str) -> dict[str, list[str]]:
    """Event dikelompokkan per tampilan (start). Di mode blok satu tampilan
    terdiri dari banyak event: satu blok + satu per kata."""
    grup: dict[str, list[str]] = {}
    for ln in dialogues(ass):
        grup.setdefault(parse_times(ln)[0], []).append(ln)
    return grup


def test_gaya_text_color_identik_dengan_jalur_lama():
    """Gaya bawaan tidak boleh mengubah satu karakter pun dari file .ass lama."""
    assert build_ass(TIGA, 0.0, 2.0, knob={"active_word_style": "text_color"}) \
        == build_ass(TIGA, 0.0, 2.0)


def test_satu_blok_per_tampilan():
    for evs in per_waktu(build_ass(TIGA, 0.0, 2.0, knob=BLOK)).values():
        assert sum("\\p1" in e for e in evs) == 1
        assert len(evs) == 1 + 3, "satu blok + satu event per kata"


def test_blok_di_bawah_kata():
    """Layer lebih tinggi digambar di atas. Terbalik, bloknya menutupi kata."""
    for e in dialogues(build_ass(TIGA, 0.0, 2.0, knob=BLOK)):
        assert e.startswith("Dialogue: 0,") == ("\\p1" in e)


def test_blok_sepusat_dengan_kata_aktif():
    """Inti pendekatannya: blok dan kata aktif memakai titik tengah yang sama."""
    for i, evs in enumerate(per_waktu(build_ass(TIGA, 0.0, 2.0, knob=BLOK)).values()):
        blok = next(e for e in evs if "\\p1" in e)
        kata = next(e for e in evs if "\\bord0" in e and "\\p1" not in e)
        assert kata.endswith(["aku", "kamu", "dia"][i])
        assert POS.search(blok).group(1) == POS.search(kata).group(1)


def test_kata_aktif_berwarna_teks_blok_dan_tanpa_outline():
    knob = {**BLOK, "active_word_text_color": "112233"}
    for evs in per_waktu(build_ass(TIGA, 0.0, 2.0, knob=knob)).values():
        aktif = [e for e in evs if "\\p1" not in e and "\\1c&H332211&" in e]
        assert len(aktif) == 1 and "\\bord0" in aktif[0]


def test_posisi_kata_tidak_bergeser_saat_sorotan_pindah():
    """Posisi dihitung sekali per grup; kalau per tampilan, kata ikut melompat."""
    posisi = [
        sorted(POS.search(e).groups() for e in evs if "\\p1" not in e)
        for evs in per_waktu(build_ass(TIGA, 0.0, 2.0, knob=BLOK)).values()
    ]
    assert all(p == posisi[0] for p in posisi)


def test_membesar_hanya_kata_aktif_dan_bloknya():
    knob = {"active_word_style": "background_scale"}
    for evs in per_waktu(build_ass(TIGA, 0.0, 2.0, knob=knob)).values():
        assert sum("\\t(" in e for e in evs) == 2


def test_baris_rata_tengah_simetris():
    lay = L.ambil("penuh")
    pusat, lebar = _tata(TIGA, lay, BLOK, "Poppins", 96, False, 18)
    kiri = pusat[0][0] - lebar[0] / 2
    kanan = pusat[-1][0] + lebar[-1] / 2
    assert abs((kiri + kanan) / 2 - L.OUT_W / 2) < 1


def test_rata_kanan_menempel_ke_margin_kanan():
    lay = L.ambil("samping")
    pusat, lebar = _tata(TIGA, lay, BLOK, "Lora", 64, False, 18)
    assert abs(pusat[-1][0] + lebar[-1] / 2 - (L.OUT_W - lay.margin_r)) < 1


def test_tumpuk_satu_kata_per_baris():
    lay = replace(L.ambil("penuh"), tumpuk=True)
    pusat, _ = _tata(TIGA, lay, BLOK, "Poppins", 96, False, 18)
    assert len({round(x) for x, _ in pusat}) == 1
    assert len({round(y) for _, y in pusat}) == 3


def test_baris_terlalu_lebar_dipecah():
    panjang = words([(w, i * 0.3, i * 0.3 + 0.2) for i, w in
                     enumerate(["pertanggungjawaban", "keanekaragaman", "ketidakadilan"])])
    pusat, _ = _tata(panjang, L.ambil("penuh"), BLOK, "Poppins", 160, False, 18)
    assert len({round(y) for _, y in pusat}) > 1


def test_radius_nol_berarti_sudut_siku():
    assert "b " not in _pil(200, 80, 0)


def test_radius_melebihi_setengah_tinggi_jadi_pil():
    """Radius yang kebablasan membuat kurva sudut saling menyilang."""
    assert _pil(200, 80, 999) == _pil(200, 80, 40)


def test_layout_tanpa_sorotan_tidak_dapat_blok():
    lay = replace(L.ambil("penuh"), sorot=False)
    assert "\\p1" not in build_ass(TIGA, 0.0, 2.0, lay=lay, knob=BLOK)
