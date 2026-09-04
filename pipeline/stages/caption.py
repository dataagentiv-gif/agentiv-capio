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


def build_ass(words: list[dict], clip_start: float, clip_end: float,
              lay=None, knob: dict | None = None) -> str:
    """Bangun isi file .ass. `words` pakai waktu SOURCE; di sini digeser jadi
    relatif terhadap clip_start, karena render memakai input seek (-ss sebelum
    -i) yang me-rebase pts filtergraph ke nol.

    `lay` menentukan hal yang harus sepakat dengan geometri video — posisi,
    perataan, penumpukan. `knob` menentukan hal yang berdiri sendiri: font,
    ukuran, warna kata aktif, huruf besar.
    """
    knob = knob or {}
    if lay is None:
        from pipeline import layout as _l
        lay = _l.ambil("penuh")

    from pipeline import layout as _l
    aktif = "{\\c&H" + _l._bgr(knob.get("aktif") or "FFE500") + "&}"
    pasif = "{\\c&H" + _l._bgr(knob.get("pasif") or lay.warna_pasif) + "&}"
    besar = bool(knob.get("upper"))
    # Penumpukan vertikal cuma soal pemisah baris: \N di .ass memaksa baris
    # baru, sementara spasi biasa membiarkan teks mengalir mendatar.
    pisah = "\\N" if lay.tumpuk else " "

    lines = [_l.header_ass(lay, knob)]
    groups = _group(words, int(knob.get("kata") or lay.kata), MAX_CHARS)
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
            if end_rel <= start_rel:
                continue

            text = pisah.join(
                (aktif + _kata(x["w"], besar) + pasif) if j == i
                else _kata(x["w"], besar)
                for j, x in enumerate(g)
            )
            lines.append(
                f"Dialogue: 0,{_ts(start_rel)},{_ts(end_rel)},Cap,,0,0,0,,{text}"
            )
    return "\n".join(lines) + "\n"


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
    }


def run(ctx: dict) -> dict:
    from config.settings import settings
    from pipeline import layout

    words: list[dict] = ctx["words"]
    workdir: Path = ctx["workdir"]
    lay = layout.ambil(ctx.get("layout") or settings.CLIP_LAYOUT)
    # Knob milik JOB menimpa default di setelan. Kosong berarti "ikut
    # default", bukan "kosongkan" — makanya disaring lebih dulu di schema.
    knob = {**knob_dari_settings(), **(ctx.get("gaya") or {})}
    paths = {}

    for seg in ctx["segments_final"]:
        start, end = seg["start"], seg["end"]
        # Dipilih berdasarkan waktu, bukan index, karena Stage 4 sudah menggeser
        # batasnya — index asli dari LLM tidak lagi mewakili batas yang dipakai.
        slice_ = [w for w in words if w["e"] > start and w["s"] < end]
        path = workdir / f"{seg['id']}.ass"
        path.write_text(build_ass(slice_, start, end, lay, knob), encoding="utf-8")
        paths[seg["id"]] = path
        log.info("caption %s: %d kata", seg["id"], len(slice_))

    return {"captions": paths}
