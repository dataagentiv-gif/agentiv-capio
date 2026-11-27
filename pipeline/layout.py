"""Bentuk frame klip: geometri video, latar, dan gaya caption.

Satu tempat yang memutuskan SELURUH tampilan, dan itu disengaja. Di layout
`samping`, pergeseran crop ke kiri, arah gradien gelap, perataan teks ke kanan,
dan penumpukan kata vertikal harus sepakat — kalau keempatnya jadi setelan
terpisah, orang bisa membuat kombinasi yang saling bertentangan (teks rata kanan
tapi pembicaranya juga di kanan). Jadi layout dipilih utuh, bukan dipreteli.

Yang boleh diputar sendiri ada di `settings` sebagai knob: font, ukuran, warna
kata aktif, jumlah kata, huruf besar. Semuanya berdiri sendiri — diputar
bagaimanapun tidak bisa merusak geometri.
"""
import re
from dataclasses import dataclass, field, replace

OUT_W, OUT_H = 1080, 1920

#: Rentang knob bayangan, dalam persen. Ujung 100% memang hitam penuh;
#: luas di bawah 20% tidak lagi sampai ke belakang teks, dan di atas 80%
#: gelapnya mulai merayap ke pembicara yang ditaruh di sepertiga kiri.
REDUP_GELAP = (0, 100)
REDUP_LUAS = (20, 80)


@dataclass(frozen=True)
class Layout:
    nama: str
    judul: str
    keterangan: str
    #: True kalau layout menaruh video di kotak; False = 9:16 mengisi layar.
    kotak: bool = False
    #: Frame sumber tidak disentuh sama sekali — tanpa crop, scale, maupun pad.
    #: Klipnya keluar dengan rasio aslinya, cuma dipotong di sumbu waktu.
    apa_adanya: bool = False
    #: Layout ini memakai caption. Dimatikan untuk mentahan: teks yang terbakar
    #: ke gambar tidak bisa dicabut lagi oleh yang mengedit ulang, jadi di sana
    #: caption bukan pilihan yang mati — ia tidak masuk akal sejak awal.
    teks: bool = True
    #: Tinggi kotak video sebagai pecahan tinggi keluaran. 1.0 = mengisi penuh.
    tinggi: float = 1.0
    #: Bagian tinggi sumber yang diambil. 1.0 = seluruh tinggi.
    #:
    #: Ini yang membuat posisi wajah berguna. Pada sumber 16:9, jendela apa pun
    #: yang tidak lebih lebar dari 16:9 akan memakai TINGGI PENUH — tidak ada
    #: yang bisa digeser, dan fx/fy jadi sia-sia. Referensinya sendiri memang
    #: di-zoom: pembicara terlihat dari dada ke atas, bukan seluruh frame
    #: dikecilkan.
    zoom: float = 1.0
    #: Posisi wajah yang dituju secara horizontal di dalam kotak (0..1).
    #: 0.5 = tengah; 0.3 menaruh pembicara di kiri dan menyisakan ruang teks.
    wajah_x: float = 0.5
    #: Ruang di atas kepala, pecahan tinggi kotak. Dipakai hanya kalau kotaknya
    #: lebih pendek dari frame — pada 9:16 penuh tidak ada yang bisa digeser.
    kepala: float = 0.34
    #: Radius sudut kotak dalam piksel keluaran. 0 = siku.
    radius: int = 0
    #: (mulai, alpha_maks) gradasi gelap menuju `redup_sisi`. None = tidak ada.
    #:
    #: `mulai` = di mana gelapnya MULAI muncul, pecahan lebar; dari situ ia
    #: menguat sampai `alpha_maks` di tepi kanan. Bukan kotak beralpha rata:
    #: kotak meninggalkan garis batas yang terlihat jelas dan membelah frame
    #: jadi dua bidang, sementara yang dituju adalah tepi yang pekat lalu
    #: memudar tanpa batas yang bisa ditunjuk.
    redup: tuple[float, float] | None = None
    #: Tepi yang dibuat paling gelap. Pada `samping`, nilainya selalu
    #: berlawanan dengan posisi pembicara.
    redup_sisi: str = "kanan"
    #: Dua crop sumber ditumpuk menjadi panel 1080x960.
    duo: bool = False
    #: Alignment .ass (numpad): 2 bawah-tengah, 5 tengah, 6 tengah-kanan.
    align: int = 2
    margin_v: int = 420
    margin_l: int = 80
    margin_r: int = 80
    #: Kata ditumpuk vertikal satu per baris, bukan mengalir mendatar.
    tumpuk: bool = False
    #: Kata yang sedang diucapkan diberi warna sendiri. Dimatikan untuk gaya
    #: yang tenang: sorotan menarik mata mengikuti ucapan, tapi pada tipografi
    #: serif yang kalem ia justru terasa ramai.
    sorot: bool = True
    #: Huruf tebal. Sans padat butuh ini; serif justru rusak ditebalkan —
    #: libass mensintesis tebalnya, dan hasilnya blobby di ukuran besar.
    tebal: bool = True
    #: Font yang disarankan untuk layout ini. Bukan paksaan — form Submit
    #: memakainya sebagai nilai awal, dan pilihan pengguna tetap menang.
    font_saran: str = ""
    kata: int = 4
    ukuran: int = 96
    warna_pasif: str = "FFFFFF"
    tags: dict = field(default_factory=dict)


LAYOUTS = {
    "penuh": Layout(
        nama="penuh",
        judul="Penuh",
        keterangan="Video mengisi seluruh layar, caption di bawah tengah. "
                   "Paling aman dan paling banyak menampilkan gambar.",
    ),
    "duo": Layout(
        nama="duo",
        judul="Podcast 2 Orang",
        keterangan="Untuk wide-shot yang terus menampilkan tepat dua orang. "
                   "Posisi keduanya dikunci sepanjang klip; video multicam, "
                   "close-up bergantian, atau tiga orang otomatis memakai Penuh.",
        duo=True,
        # Medium shot yang sedikit lebih rapat agar wajah tetap menjadi fokus.
        zoom=0.65,
        align=5,
        margin_v=0,
    ),
    "kotak": Layout(
        nama="kotak",
        judul="Kotak tengah",
        keterangan="Video dalam kotak sudut tumpul di tengah, latar hitam, "
                   "caption besar di bawah kotak.",
        kotak=True,
        tinggi=0.55,
        zoom=0.80,
        radius=72,
        align=2,
        margin_v=300,
        kata=2,
        ukuran=112,
    ),
    "samping": Layout(
        nama="samping",
        judul="Pembicara di samping",
        keterangan="Pita mendatar, pembicara bisa di kiri atau kanan, dengan "
                   "teks dan gradasi di sisi sebaliknya. "
                   "Sebagian teks tertutup UI TikTok — itu memang lazim di klip "
                   "sekarang.",
        kotak=True,
        tinggi=0.42,
        zoom=0.85,
        wajah_x=0.3,
        # Sempat diturunkan ke 0.45 setelah versi awal 0.88 terbaca sebagai
        # bidang gelap. Di pemakaian nyata 0.45 ternyata kurang: teks putih di
        # atas latar terang tetap sulit dibaca. 0.70 di tengah keduanya, dan
        # sekarang bisa diputar per video lewat knob (terapkan_knob) — jadi
        # angka ini cuma titik awal, bukan satu-satunya pilihan.
        redup=(0.40, 1.0),
        align=6,
        margin_r=70,
        # Satu baris mendatar, bukan ditumpuk — mengikuti referensi.
        tumpuk=False,
        # Sorotan warna kata aktif TETAP NYALA — kalau mau polos seperti
        # referensi awal, samakan saja warna aktif dengan putih lewat knob
        # Submit (warna_pasif). Dulu ini dimatikan permanen di sini, tapi
        # mematikannya di layout mengunci SEMUA video ke satu pilihan; orang
        # yang justru mau sorotan warna di layout ini tidak punya jalan keluar
        # sama sekali selain mengedit kode.
        tebal=False,
        font_saran="Lora",
        kata=3,
        ukuran=64,
    ),
    "ori": Layout(
        nama="ori",
        judul="Asli (mentahan)",
        keterangan="Rasio sumber dipertahankan dan tidak ada caption — videonya "
                   "cuma dipotong. Untuk mentahan yang mau diedit lagi di "
                   "aplikasi lain.",
        apa_adanya=True,
        teks=False,
    ),
}

DEFAULT = "penuh"


def ambil(nama: str) -> Layout:
    return LAYOUTS.get(str(nama).strip().lower(), LAYOUTS[DEFAULT])


def _jepit(v, lo: float, hi: float) -> float | None:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def terapkan_knob(lay: Layout, knob: dict | None) -> Layout:
    """Layout dengan bayangan milik JOB, kalau knobnya diisi.

    Yang boleh ditimpa cuma dua angka — seberapa gelap dan seberapa luas.
    Arahnya tetap milik layout, jadi knob tidak bisa menaruh gelap di sisi
    pembicara. Layout tanpa bayangan dikembalikan apa adanya: knob tidak
    menciptakan bayangan di layout yang tidak dirancang untuknya.

    `redup_luas` diukur dari tepi kanan, karena begitu orang membacanya di
    layar ("60% lebar tertutup bayangan"); di dalam, `redup` menyimpan titik
    MULAINYA dari kiri.
    """
    knob = knob or {}
    if lay.nama == "samping" and knob.get("speaker_side") == "kanan":
        lay = replace(
            lay,
            wajah_x=1 - lay.wajah_x,
            align=4,
            margin_l=lay.margin_r,
            margin_r=lay.margin_l,
            redup_sisi="kiri",
        )
    if not lay.redup:
        return lay
    mulai, maks = lay.redup
    if (luas := _jepit(knob.get("redup_luas"), *REDUP_LUAS)) is not None:
        mulai = 1 - luas / 100
    if (gelap := _jepit(knob.get("redup_gelap"), *REDUP_GELAP)) is not None:
        maks = gelap / 100
    return replace(lay, redup=(round(mulai, 2), round(maks, 2)))


def _genap(n: float) -> int:
    return max(2, int(n)) & ~1


def geometri(lay: Layout, crop: dict, src_w: int, src_h: int) -> dict:
    """Jendela yang diambil dari sumber, dan ukuran kotak di kanvas keluaran.

    `crop` membawa fx/fy hasil deteksi wajah (None kalau tidak terdeteksi).
    """
    if not lay.kotak:
        # Layout penuh memakai jendela yang sudah dihitung stage crop, apa
        # adanya — angkanya tidak boleh berubah sedikit pun dari sebelum modul
        # ini ada.
        return {
            "cw": crop["w"], "ch": src_h, "cx": crop["x"], "cy": 0,
            "bw": OUT_W, "bh": OUT_H, "bx": 0, "by": 0,
        }

    bh = _genap(OUT_H * lay.tinggi)
    bw = OUT_W

    # Rasio jendela mengikuti kotaknya, bukan angka terpisah: dua nilai yang
    # bisa berbeda pasti akan berbeda suatu saat, dan hasilnya video ter-stretch
    # tanpa ada yang salah secara kode.
    ch = _genap(src_h * lay.zoom)
    cw = _genap(ch * bw / bh)
    if cw > src_w:
        cw = _genap(src_w)
        ch = _genap(cw * bh / bw)

    fx = crop.get("fx")
    fy = crop.get("fy")
    # Tanpa wajah, tengah adalah tebakan yang paling tidak merugikan.
    px = 0.5 if fx is None else fx
    py = 0.5 if fy is None else fy

    cx = _genap(px * src_w - cw * lay.wajah_x)
    cx = max(0, min(src_w - cw, cx))
    # Kepala ditaruh di `kepala` dari atas jendela, bukan di tengah: orang di
    # podcast duduk di sepertiga atas frame, jadi memusatkan wajah menyisakan
    # ruang menganga di atas kepala dan memotong badan.
    cy = _genap(py * src_h - ch * lay.kepala)
    cy = max(0, min(src_h - ch, cy))

    return {"cw": cw, "ch": ch, "cx": cx, "cy": cy,
            "bw": bw, "bh": bh, "bx": 0, "by": _genap((OUT_H - bh) / 2)}


def geometri_duo(lay: Layout, crop: dict, src_w: int, src_h: int) -> list[dict]:
    """Dua jendela medium-shot, kiri sumber menjadi atas lalu kanan bawah."""
    wajah = crop.get("duo") or []
    if len(wajah) != 2:
        return []
    hasil = []
    for i, muka in enumerate(wajah):
        ch = _genap(src_h * lay.zoom)
        cw = _genap(ch * OUT_W / (OUT_H / 2))
        if cw > src_w:
            cw = _genap(src_w)
            ch = _genap(cw * (OUT_H / 2) / OUT_W)
        # Keduanya menghadap ke sambungan panel: orang kiri berada di 65%
        # lebar panel, orang kanan di 35%. Crop boleh melewati titik tengah
        # sumber, tetapi pusat wajah lawan tetap di luar dengan sedikit jarak.
        target_x = 0.65 if i == 0 else 0.35
        cx = _genap(muka["fx"] * src_w - cw * target_x)
        aman = _genap(src_w * 0.05)
        lawan_x = wajah[1 - i]["fx"] * src_w
        if i == 0:
            cx = min(cx, _genap(lawan_x - aman - cw))
        else:
            cx = max(cx, _genap(lawan_x + aman))
        cx = max(0, min(src_w - cw, cx)) & ~1
        cy = _genap(muka["fy"] * src_h - ch * lay.kepala)
        cy = max(0, min(src_h - ch, cy)) & ~1
        hasil.append({"cw": cw, "ch": ch, "cx": cx, "cy": cy,
                      "bw": OUT_W, "bh": OUT_H // 2,
                      "bx": 0, "by": i * (OUT_H // 2)})
    return hasil


def filtergraph(lay: Layout, g: dict, ass: str | None = None,
                mask: str | None = None) -> str:
    """Rantai filter ffmpeg lengkap untuk satu klip.

    `ass` None berarti tanpa caption. String KOSONG yang dikembalikan berarti
    tidak ada filter sama sekali — pemanggilnya harus menghilangkan `-vf`, bukan
    mengirimnya kosong, karena `-vf ""` ditolak ffmpeg.
    """
    bagian = []

    if not lay.apa_adanya:
        bagian.append(f"crop={g['cw']}:{g['ch']}:{g['cx']}:{g['cy']}")
        if not lay.kotak:
            bagian.append(f"scale={OUT_W}:{OUT_H}")
        else:
            bagian.append(f"scale={g['bw']}:{g['bh']}")
            bagian.append(
                f"pad={OUT_W}:{OUT_H}:{g['bx']}:{g['by']}:black"
            )
        bagian.append("setsar=1")

    if not mask:
        if ass:
            bagian.append(f"subtitles={ass}")
        return ",".join(bagian)

    # Sudut tumpul DAN gradasi gelap lewat satu gambar bertumpuk, bukan filter
    # per piksel per frame. Latarnya hitam solid, jadi cukup menimpakan PNG
    # hitam beralpha; `geq` yang menghitungnya cuma jalan sekali pada satu
    # gambar diam.
    #
    # Gradasi TIDAK memakai drawbox: kotak beralpha rata meninggalkan garis
    # batas yang terlihat jelas dan membelah frame jadi dua bidang. Yang dituju
    # adalah tepi pekat yang memudar tanpa batas yang bisa ditunjuk, dan itu
    # menuntut alpha yang berubah per kolom piksel.
    #
    # Label rantai menempel LANGSUNG ke filter terakhir tanpa koma —
    # `setsar=1[v]`, bukan `setsar=1,[v]`. Yang kedua ditolak ffmpeg dengan
    # exit code 8 dan pesan yang menunjuk berkas keluaran, bukan filternya.
    return (
        ",".join(bagian) + "[v];"
        f"movie={mask}[m];"
        f"[v][m]overlay=0:0" + (f",subtitles={ass}" if ass else "")
    )


def pakai_caption(lay: Layout, knob: dict | None = None) -> bool:
    """Apakah klip ini dapat caption terbakar.

    Dua sumber keputusan, dan layout menang: knob `caption` adalah pilihan
    pengguna, tapi layout mentahan tidak pernah memakai caption apa pun isinya.
    Nilai yang disimpan HANYA False — tidak adanya kunci berarti "nyala", sama
    seperti knob tampilan lain di mana kosong berarti ikut default.
    """
    return lay.teks and (knob or {}).get("caption") is not False


def butuh_lapisan(lay: Layout) -> bool:
    """Apakah layout ini perlu gambar bertumpuk (sudut tumpul atau gradasi)."""
    return bool(lay.radius or lay.redup)


def header_ass(lay: Layout, knob: dict) -> str:
    """Blok [Script Info] + [V4+ Styles] sesuai layout dan knob."""
    font = knob.get("font") or "Poppins"
    ukuran = int(knob.get("ukuran") or lay.ukuran)
    # .ass memakai &HBBGGRR&, kebalikan urutan RGB yang biasa ditulis orang.
    pasif = _bgr(knob.get("pasif") or lay.warna_pasif)
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {OUT_W}\n"
        f"PlayResY: {OUT_H}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: None\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font},{ukuran},&H00{pasif},&H000000FF,&H00000000,"
        f"&HA0000000,{-1 if lay.tebal else 0},{-1 if knob.get('italic') else 0},0,0,100,100,0,0,1,"
        f"{knob.get('outline', 6 if lay.tebal else 3)},{knob.get('shadow', 2)},{lay.align},"
        f"{lay.margin_l},{lay.margin_r},{lay.margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )


def _bgr(hex_rgb: str) -> str:
    """RRGGBB -> BBGGRR. Salah urutan di sini menghasilkan warna yang terlihat
    'hampir benar' (merah jadi biru), jadi gampang lolos tanpa disadari."""
    h = str(hex_rgb).strip().lstrip("#")
    # Hex sungguhan, bukan sekadar enam karakter: hasilnya ditempel ke dalam
    # blok override .ass, dan "a{b}cd" yang lolos akan menutup blok itu lebih
    # awal lalu merusak seluruh baris caption.
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        h = "FFFFFF"
    return (h[4:6] + h[2:4] + h[0:2]).upper()
