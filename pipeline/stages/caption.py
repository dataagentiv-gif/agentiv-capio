"""Stage 5: generator file .ass (caption karaoke burned-in).

Input  : ctx[words], ctx[segments_final], ctx[workdir]
Output : {clip_id}.ass di workdir

Dipakai event Dialogue terpisah per kata, bukan tag \\k. Tiga alasan:
- \\k adalah progressive fill (SecondaryColour -> PrimaryColour), jadi setiap
  kata yang sudah lewat TETAP ter-highlight. Short-form butuh yang sedang
  diucapkan saja yang menyala.
- Durasi \\k dihitung centisecond kumulatif dari awal baris, sehingga
  pembulatannya menumpuk dan jumlahnya wajib pas dengan durasi baris.
- Efek lain (pop skala, warna per state) tidak bisa dikaitkan ke \\k tanpa \\t
  dengan offset yang dihitung tangan — pembukuan yang sama beratnya, tapi jauh
  lebih sulit di-debug daripada file yang bisa dibaca mata.
"""
from pathlib import Path

from utils.logging import get

log = get(__name__)

MAX_WORDS = 4       # kata per tampilan
MAX_CHARS = 22      # pecah lebih awal kalau katanya panjang-panjang
GROUP_TAIL = 0.4    # berapa lama tampilan terakhir bertahan setelah kata selesai

#: Gaya kata aktif. `text_color` jalur lama; dua sisanya menggambar blok.
GAYA_AKTIF = ("text_color", "background", "background_scale")
#: Kata aktif di `background_scale` membesar ke sini dalam POP_MS milidetik.
#: Cukup untuk terasa hidup, belum sampai terlihat melompat.
SKALA = 108
POP_MS = 80
#: Seberapa dalam descender ikut tertutup blok, sebagai pecahan kedalamannya.
#: 0 = blok cuma setinggi huruf kapital, 1 = seluruh ekor huruf g/p/y masuk.
# ponytail: satu angka untuk semua font, dikalibrasi dari render Poppins,
# Anton, dan Lora. Jadikan per font kalau suatu font baru terlihat meleset.
BLOK_EKOR = 0.6

# &HBBGGRR& untuk override \c (kebalikan urutan RGB).
ACTIVE = r"{\c&H00E5FF&}"   # kuning keemasan
IDLE = r"{\c&HFFFFFF&}"     # putih

# MarginV 420 pada tinggi 1920 menaruh baseline sekitar 22% dari bawah — di atas
# jempol dan di atas UI player, tapi belum masuk area wajah.
HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,96,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t: float) -> str:
    """Format .ass: satu digit jam, dua digit centisecond."""
    t = max(0.0, t)
    h, rest = divmod(t, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w: str) -> str:
    """Kurung kurawal adalah pembuka blok override di .ass; kalau lolos mentah,
    satu kata aneh di transkrip bisa menelan seluruh baris caption.
    """
    return w.replace("{", "(").replace("}", ")").replace("\\", "/").strip()


def _kata(w: str, besar: bool) -> str:
    teks = _clean(w)
    return teks.upper() if besar else teks


def _group(words: list[dict], maks_kata: int = MAX_WORDS,
           maks_char: int = MAX_CHARS) -> list[list[dict]]:
    groups, cur, chars = [], [], 0
    for w in words:
        cur.append(w)
        chars += len(w["w"]) + 1
        if len(cur) >= maks_kata or chars >= maks_char:
            groups.append(cur)
            cur, chars = [], 0
    if cur:
        groups.append(cur)
    return groups


def _keadaan(groups: list[list[dict]], clip_start: float, clip_end: float):
    """(index grup, index kata aktif, start relatif, end relatif) per tampilan."""
    span = clip_end - clip_start
    for gi, g in enumerate(groups):
        next_start = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else None
        for i, w in enumerate(g):
            if i + 1 < len(g):
                # Berakhir saat kata berikutnya mulai, bukan saat kata ini
                # selesai — menutup celah antar kata supaya tampilan tidak
                # berkedip mati-nyala di sela-sela ucapan.
                end = g[i + 1]["s"]
            else:
                end = w["e"] + GROUP_TAIL
                if next_start is not None:
                    end = min(end, next_start)

            start_rel = w["s"] - clip_start
            end_rel = min(end - clip_start, span)
            if end_rel > start_rel:
                yield gi, i, start_rel, end_rel


def _angka(nilai, bawaan: int) -> int:
    """Knob piksel blok: 0..60, dan nol itu nilai sungguhan (sudut siku)."""
    try:
        return max(0, min(60, int(float(nilai))))
    except (TypeError, ValueError, OverflowError):
        return bawaan


def build_ass(words: list[dict], clip_start: float, clip_end: float,
              lay=None, knob: dict | None = None) -> str:
    """Bangun isi file .ass. `words` pakai waktu SOURCE; di sini digeser jadi
    relatif terhadap clip_start, karena render memakai input seek (-ss sebelum
    -i) yang me-rebase pts filtergraph ke nol.

    `lay` menentukan hal yang harus sepakat dengan geometri video — posisi,
    perataan, penumpukan. `knob` menentukan hal yang berdiri sendiri: font,
    ukuran, warna kata aktif, huruf besar, gaya kata aktif.
    """
    knob = knob or {}
    if lay is None:
        from pipeline import layout as _l
        lay = _l.ambil("penuh")

    from pipeline import layout as _l
    lines = [_l.header_ass(lay, knob)]
    groups = _group(words, int(knob.get("kata") or lay.kata), MAX_CHARS)
    keadaan = _keadaan(groups, clip_start, clip_end)

    # Layout yang tidak menyorot tidak pernah dapat blok: blok adalah bentuk
    # sorotan, bukan hiasan yang berdiri sendiri.
    if lay.sorot and knob.get("active_word_style") in GAYA_AKTIF[1:]:
        lines += _blok(groups, keadaan, lay, knob)
        return "\n".join(lines) + "\n"

    pasif = "{\\c&H" + _l._bgr(knob.get("pasif") or lay.warna_pasif) + "&}"
    # Layout yang tidak menyorot memakai warna yang sama untuk kata aktif —
    # bukan menghapus tag warnanya, supaya bentuk baris tetap identik dan
    # tidak ada cabang khusus di perakitan teks di bawah.
    warna_aktif = _l._bgr(knob.get("aktif") or "FFE500")
    aktif = (
        "{\\c&H" + warna_aktif + "&"
        + ("\\3c&H" + warna_aktif + "&\\bord5\\blur5" if knob.get("active_word_glow") else "")
        + "}"
        if lay.sorot else pasif
    )
    if knob.get("active_word_glow"):
        pasif = "{\\r}"
    besar = bool(knob.get("upper"))
    # Penumpukan vertikal cuma soal pemisah baris: \N di .ass memaksa baris
    # baru, sementara spasi biasa membiarkan teks mengalir mendatar.
    pisah = "\\N" if lay.tumpuk else " "

    for gi, i, start_rel, end_rel in keadaan:
        text = pisah.join(
            (aktif + _kata(x["w"], besar) + pasif) if j == i
            else _kata(x["w"], besar)
            for j, x in enumerate(groups[gi])
        )
        lines.append(
            f"Dialogue: 0,{_ts(start_rel)},{_ts(end_rel)},Cap,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


# --- gaya kata aktif: blok ---
#
# libass tidak punya latar per kata yang bersudut tumpul. BorderStyle 3 memang
# memberi kotak, tapi siku dan paddingnya satu angka untuk dua sumbu. Jadi
# bloknya digambar sebagai vector drawing (\p1), dan itu menuntut posisi
# piksel tiap kata — yang di jalur lama diurus libass tanpa pernah terlihat.
#
# Karena itu di sini posisi TIAP KATA dihitung sendiri (pipeline/metrik.py) dan
# tiap kata jadi event dengan \an5\pos-nya sendiri. Blok ditaruh di titik tengah
# yang sama persis. Kalau ukuran hasil hitungan meleset beberapa piksel, yang
# berubah cuma lebar padding di kiri-kanan — blok tidak pernah bergeser dari
# katanya. Posisinya juga dihitung sekali per grup, jadi kata-kata tidak ikut
# bergeser saat sorotan berpindah.

def _tata(g: list[dict], lay, knob: dict, font: str, ukuran: int, besar: bool,
          pad_x: int) -> tuple[list[tuple[float, float]], list[float]]:
    """(titik tengah tiap kata, lebar tiap kata) dalam piksel keluaran."""
    from pipeline import layout as _l
    from pipeline import metrik

    lebar = [metrik.lebar(_kata(w["w"], besar), font, ukuran, lay.tebal) for w in g]
    tinggi_baris = metrik.vertikal(font, ukuran, lay.tebal)[0]
    # Spasi biasa ditambah padding DUA SISI, bukan satu. Blok cuma nongol di
    # kata yang aktif, tapi kata mana pun bisa jadi aktif berikutnya — jadi tiap
    # jarak antar kata harus punya ruang pad_x di KEDUA ujungnya supaya blok
    # tidak pernah menutupi kata sebelah, siapa pun yang sedang menyala. Ketahuan
    # dari rendering: dengan cuma satu pad_x, gap yang terlihat cuma selebar
    # spasi kosong (~13px di ukuran 112) — kata sebelahnya terlihat menempel ke
    # blok. Di mode membesar, ruang pembesarannya ikut dipesan untuk SEMUA jarak
    # di grup — kalau cuma di sekitar kata aktif, kata lain bergeser tiap
    # sorotan pindah.
    jarak = metrik.lebar(" ", font, ukuran, lay.tebal) + 2 * pad_x
    if knob.get("active_word_style") == "background_scale":
        jarak += (SKALA / 100 - 1) * (max(lebar) / 2 + pad_x)

    ruang = _l.OUT_W - lay.margin_l - lay.margin_r
    lebar_baris = lambda idx: sum(lebar[k] for k in idx) + jarak * (len(idx) - 1)  # noqa: E731
    baris: list[list[int]] = []
    for k in range(len(g)):
        if baris and not lay.tumpuk and lebar_baris(baris[-1] + [k]) <= ruang:
            baris[-1].append(k)
        else:
            baris.append([k])

    # Alignment .ass bernomor numpad: baris bawah 1-3, tengah 4-6, atas 7-9.
    kolom, lantai = (lay.align - 1) % 3, (lay.align - 1) // 3
    total = tinggi_baris * len(baris)
    atas = {0: _l.OUT_H - lay.margin_v - total,
            1: (_l.OUT_H - total) / 2,
            2: lay.margin_v}[lantai]

    pusat: list[tuple[float, float]] = [(0.0, 0.0)] * len(g)
    for b, idx in enumerate(baris):
        w = lebar_baris(idx)
        x = {0: lay.margin_l,
             1: lay.margin_l + (ruang - w) / 2,
             2: _l.OUT_W - lay.margin_r - w}[kolom]
        y = atas + (b + 0.5) * tinggi_baris
        for k in idx:
            pusat[k] = (x + lebar[k] / 2, y)
            x += lebar[k] + jarak
    return pusat, lebar


def _pil(w: float, h: float, r: float) -> str:
    """Path persegi bersudut tumpul, titik asal di kiri atas.

    Seperempat lingkaran didekati satu kurva bezier dengan titik kendali sejauh
    0.5523r dari ujungnya — selisihnya dari lingkaran sungguhan di bawah satu
    piksel pada radius mana pun yang masuk akal di sini.
    """
    w, h = round(w), round(h)
    r = round(max(0.0, min(r, w / 2, h / 2)))
    if not r:
        return f"m 0 0 l {w} 0 {w} {h} 0 {h}"
    c = round(r * 0.5523)
    return (
        f"m {r} 0 l {w - r} 0 b {w - r + c} 0 {w} {r - c} {w} {r} "
        f"l {w} {h - r} b {w} {h - r + c} {w - r + c} {h} {w - r} {h} "
        f"l {r} {h} b {r - c} {h} 0 {h - r + c} 0 {h - r} "
        f"l 0 {r} b 0 {r - c} {r - c} 0 {r} 0"
    )


def _blok(groups: list[list[dict]], keadaan, lay, knob: dict) -> list[str]:
    from config.settings import settings
    from pipeline import layout as _l
    from pipeline import metrik

    font = knob.get("font") or "Poppins"
    ukuran = int(knob.get("ukuran") or lay.ukuran)
    besar = bool(knob.get("upper"))
    pad_x = _angka(knob.get("active_word_padding_x"), settings.ACTIVE_WORD_PADDING_X)
    pad_y = _angka(knob.get("active_word_padding_y"), settings.ACTIVE_WORD_PADDING_Y)
    radius = _angka(knob.get("active_word_border_radius"),
                    settings.ACTIVE_WORD_BORDER_RADIUS)
    warna_blok = _l._bgr(knob.get("active_word_background_color")
                         or settings.ACTIVE_WORD_BACKGROUND_COLOR)
    warna_teks = _l._bgr(knob.get("active_word_text_color")
                         or settings.ACTIVE_WORD_TEXT_COLOR)
    pop = (f"\\fscx100\\fscy100\\t(0,{POP_MS},\\fscx{SKALA}\\fscy{SKALA})"
           if knob.get("active_word_style") == "background_scale" else "")

    _, geser, cap, turun = metrik.vertikal(font, ukuran, lay.tebal)
    # Simetris terhadap tengah huruf kapital, bukan terhadap titik \an5 —
    # lihat metrik.vertikal. Ekor huruf kecil masuk lewat BLOK_EKOR.
    tinggi = cap + 2 * turun * BLOK_EKOR + 2 * pad_y

    tata: dict[int, tuple] = {}
    out = []
    for gi, i, a, b in keadaan:
        if gi not in tata:
            tata[gi] = _tata(groups[gi], lay, knob, font, ukuran, besar, pad_x)
        pusat, lebar = tata[gi]
        waktu = f"{_ts(a)},{_ts(b)}"

        cx, cy = pusat[i]
        out.append(
            f"Dialogue: 0,{waktu},Cap,,0,0,0,,"
            f"{{\\an5\\pos({cx:.0f},{cy + geser:.0f})\\bord0\\shad0\\blur0"
            f"\\1c&H{warna_blok}&\\1a&H00&{pop}\\p1}}"
            f"{_pil(lebar[i] + 2 * pad_x, tinggi, radius)}{{\\p0}}"
        )
        for j, x in enumerate(groups[gi]):
            px, py = pusat[j]
            tag = f"\\an5\\pos({px:.0f},{py:.0f})"
            if j == i:
                # Tanpa outline: outline hitam di atas blok berwarna membuat
                # hurufnya terlihat tebal dan kotor, bukan lebih terbaca.
                tag += f"\\1c&H{warna_teks}&\\bord0\\shad0{pop}"
            out.append(f"Dialogue: 1,{waktu},Cap,,0,0,0,,{{{tag}}}{_kata(x['w'], besar)}")
    return out


def knob_dari_settings() -> dict:
    """Knob tampilan dari .env. Dipisah supaya preview di halaman Setting bisa
    memakai jalur yang sama persis dengan produksi."""
    from config.settings import settings

    return {
        "font": settings.CAPTION_FONT,
        "ukuran": settings.CAPTION_SIZE or None,
        "aktif": settings.CAPTION_COLOR,
        "kata": settings.CAPTION_WORDS or None,
        "upper": settings.CAPTION_UPPER,
        "active_word_style": settings.ACTIVE_WORD_STYLE,
        "active_word_background_color": settings.ACTIVE_WORD_BACKGROUND_COLOR,
        "active_word_text_color": settings.ACTIVE_WORD_TEXT_COLOR,
        "active_word_border_radius": settings.ACTIVE_WORD_BORDER_RADIUS,
        "active_word_padding_x": settings.ACTIVE_WORD_PADDING_X,
        "active_word_padding_y": settings.ACTIVE_WORD_PADDING_Y,
    }


def run(ctx: dict) -> dict:
    if "template_id" in ctx:
        from pipeline import emphasis, motion
        from pipeline.reference_caption import CaptionEngine, MOTIONS, render_overlay
        paths = {}
        if ctx["template_id"] == "mentahan":
            return {"captions": paths}
        for seg in ctx["segments_final"]:
            words = [w for w in ctx["words"] if w["e"] > seg["start"] and w["s"] < seg["end"]]
            if ctx["template_id"] == "custom":
                from pipeline.custom import caption_ass, output_size
                if ctx["adjustments"].get("caption"):
                    w, h = output_size(ctx["adjustments"])
                    path = ctx["workdir"] / f"{seg['id']}.ass"
                    path.write_text(caption_ass(words, seg, ctx["adjustments"], w, h), encoding="utf-8")
                    paths[seg["id"]] = path
                continue
            selected = set()
            if ctx["adjustments"].get("caption_motion") in {"editorial_focus", "scatter_emphasis"}:
                selected = emphasis.choose(words, seg["start"], seg["end"])
            if ctx["adjustments"].get("caption_motion") in MOTIONS:
                path = ctx["workdir"] / f"{seg['id']}.mov"
                engine = CaptionEngine(words, seg, ctx["template_id"],
                                       ctx["adjustments"], ctx["crops"][seg["id"]], selected)
                paths[seg["id"]] = render_overlay(engine, path, ctx["deadline"])
                continue
            path = ctx["workdir"] / f"{seg['id']}.ass"
            path.write_text(motion.build(words, seg, ctx["template_id"],
                                         ctx["adjustments"], ctx["crops"][seg["id"]], selected), encoding="utf-8")
            paths[seg["id"]] = path
        return {"captions": paths}
    from config.settings import settings
    from pipeline import layout

    words: list[dict] = ctx["words"]
    workdir: Path = ctx["workdir"]
    lay = layout.ambil(ctx.get("layout") or settings.CLIP_LAYOUT)
    # Knob milik JOB menimpa default di setelan. Kosong berarti "ikut
    # default", bukan "kosongkan" — makanya disaring lebih dulu di schema.
    knob = {**knob_dari_settings(), **(ctx.get("gaya") or {})}
    lay = layout.terapkan_knob(lay, knob)

    if not layout.pakai_caption(lay, knob):
        log.info("caption dimatikan — tidak ada .ass yang dibuat")
        return {"captions": {}}

    paths = {}

    for seg in ctx["segments_final"]:
        start, end = seg["start"], seg["end"]
        # Dipilih berdasarkan waktu, bukan index, karena Stage 4 sudah menggeser
        # batasnya — index asli dari LLM tidak lagi mewakili batas yang dipakai.
        slice_ = [w for w in words if w["e"] > start and w["s"] < end]
        path = workdir / f"{seg['id']}.ass"
        seg_lay = lay
        if lay.duo and not (ctx.get("crops", {}).get(seg["id"], {}).get("duo")):
            seg_lay = layout.ambil("penuh")
        path.write_text(build_ass(slice_, start, end, seg_lay, knob), encoding="utf-8")
        paths[seg["id"]] = path
        log.info("caption %s: %d kata", seg["id"], len(slice_))

    return {"captions": paths}
