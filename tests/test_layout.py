"""Geometri layout dan gaya caption.

Yang paling penting dijaga di sini adalah layout `penuh`: ia harus menghasilkan
angka yang PERSIS sama seperti sebelum modul ini ada. Kalau bergeser sedikit
pun, seluruh klip yang sudah dianggap benar ikut berubah tanpa ada yang meminta.
"""
import pytest

from pipeline import layout as L


def crop(x=656, w=608, fx=None, fy=None):
    return {"x": x, "w": w, "fx": fx, "fy": fy}


# --- layout penuh tidak boleh berubah ---

def test_penuh_memakai_jendela_dari_stage_crop():
    g = L.geometri(L.ambil("penuh"), crop(x=100, w=608), 1920, 1080)
    assert (g["cw"], g["ch"], g["cx"], g["cy"]) == (608, 1080, 100, 0)


def test_penuh_mengisi_kanvas_tanpa_pad():
    lay = L.ambil("penuh")
    g = L.geometri(lay, crop(), 1920, 1080)
    vf = L.filtergraph(lay, g, "c1.ass")
    assert "scale=1080:1920" in vf
    assert "pad=" not in vf, "layout penuh tidak boleh punya latar hitam"
    assert vf.startswith("crop=608:1080:656:0")


def test_nama_tidak_dikenal_jatuh_ke_penuh():
    """Nilai lama atau salah ketik di .env jangan menggagalkan job."""
    assert L.ambil("entah-apa").nama == "penuh"
    assert L.ambil("").nama == "penuh"


# --- kotak ---

def test_kotak_lebih_pendek_dari_layar():
    g = L.geometri(L.ambil("kotak"), crop(fx=0.5, fy=0.4), 1920, 1080)
    assert g["bh"] < L.OUT_H
    assert g["by"] > 0, "kotak harus punya ruang hitam di atasnya"


def test_kotak_berada_di_tengah_vertikal():
    g = L.geometri(L.ambil("kotak"), crop(fx=0.5, fy=0.4), 1920, 1080)
    bawah = L.OUT_H - (g["by"] + g["bh"])
    assert abs(g["by"] - bawah) <= 2


def test_kotak_memakai_posisi_wajah_vertikal():
    """Inilah gunanya membuka koordinat Y. Wajah di atas dan di bawah frame
    harus menghasilkan jendela yang berbeda."""
    atas = L.geometri(L.ambil("kotak"), crop(fx=0.5, fy=0.25), 1920, 1080)
    bawah = L.geometri(L.ambil("kotak"), crop(fx=0.5, fy=0.75), 1920, 1080)
    assert atas["cy"] < bawah["cy"]


def test_kotak_menyisakan_ruang_di_atas_kepala():
    """Kepala ditaruh di sepertiga atas, bukan di tengah — memusatkan wajah
    menyisakan ruang menganga di atas dan memotong badan."""
    lay = L.ambil("kotak")
    g = L.geometri(lay, crop(fx=0.5, fy=0.5), 1920, 1080)
    # Wajah di tengah sumber (540 px) harus jatuh di ~34% tinggi jendela.
    posisi = (540 - g["cy"]) / g["ch"]
    assert 0.28 < posisi < 0.40


def test_kotak_punya_latar_hitam_dan_sudut_tumpul():
    lay = L.ambil("kotak")
    g = L.geometri(lay, crop(fx=0.5, fy=0.4), 1920, 1080)
    vf = L.filtergraph(lay, g, "c1.ass", mask="mask.png")
    assert "pad=1080:1920" in vf
    assert "overlay=0:0" in vf
    assert lay.radius > 0


# --- samping ---

def test_samping_menggeser_pembicara_ke_kiri():
    """Wajah harus berakhir di sepertiga kiri jendela, menyisakan ruang teks."""
    lay = L.ambil("samping")
    g = L.geometri(lay, crop(fx=0.5, fy=0.4), 1920, 1080)
    posisi = (0.5 * 1920 - g["cx"]) / g["cw"]
    assert 0.25 < posisi < 0.36


def test_samping_menggelapkan_sisi_kanan():
    """Gelapnya lewat gambar bertumpuk beralpha, BUKAN drawbox. Kotak beralpha
    rata meninggalkan garis batas yang terlihat dan membelah frame jadi dua
    bidang — yang dituju tepi pekat yang memudar tanpa batas yang bisa
    ditunjuk."""
    lay = L.ambil("samping")
    assert lay.redup is not None
    assert L.butuh_lapisan(lay)
    vf = L.filtergraph(lay, L.geometri(lay, crop(fx=0.5, fy=0.4), 1920, 1080),
                       "c1.ass", mask="m.png")
    assert "drawbox=" not in vf, "kotak beralpha rata meninggalkan tepi keras"
    assert "overlay=0:0" in vf


def test_gradasi_mulai_setelah_posisi_wajah():
    """Mulai terlalu kanan menghasilkan tepi yang terasa; terlalu kiri menutupi
    pembicaranya, yang justru ditaruh di sepertiga kiri.

    Kepekatannya TIDAK diuji di sini — lihat
    test_gradasi_samping_jauh_lebih_halus_dari_versi_awal. Versi awal memakai
    0.88 dan itu terbaca sebagai bidang gelap, bukan bayangan."""
    lay = L.ambil("samping")
    mulai, _ = lay.redup
    assert 0.25 < mulai < 0.55
    assert lay.wajah_x < mulai, "gradasi mulai sebelum posisi wajah"


def test_layout_lain_tidak_punya_gradasi():
    for nama in ("penuh", "kotak"):
        assert L.ambil(nama).redup is None


def test_butuh_lapisan_hanya_saat_perlu():
    """Layout penuh tidak boleh ikut merender gambar bertumpuk — itu kerja
    ffmpeg tambahan untuk hasil yang persis sama."""
    assert not L.butuh_lapisan(L.ambil("penuh"))
    assert L.butuh_lapisan(L.ambil("kotak"))      # sudut tumpul
    assert L.butuh_lapisan(L.ambil("samping"))    # gradasi


def test_samping_meratakan_teks_ke_kanan():
    assert L.ambil("samping").align == 6


# --- jendela selalu di dalam frame ---

@pytest.mark.parametrize("nama", ["penuh", "kotak", "samping"])
@pytest.mark.parametrize("fx,fy", [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (None, None)])
def test_jendela_tidak_pernah_keluar_frame(nama, fx, fy):
    """Wajah di tepi frame adalah kasus yang paling mungkin bikin crop keluar
    batas — dan ffmpeg akan menolak dengan pesan yang tidak menyebut sebabnya."""
    lay = L.ambil(nama)
    g = L.geometri(lay, crop(fx=fx, fy=fy), 1920, 1080)
    assert 0 <= g["cx"] and g["cx"] + g["cw"] <= 1920
    assert 0 <= g["cy"] and g["cy"] + g["ch"] <= 1080


@pytest.mark.parametrize("nama", ["penuh", "kotak", "samping"])
def test_dimensi_selalu_genap(nama):
    """libx264 menolak dimensi ganjil pada yuv420p, dan kegagalannya baru
    muncul di stage render."""
    g = L.geometri(L.ambil(nama), crop(fx=0.5, fy=0.4), 1920, 1080)
    for k in ("cw", "ch", "cx", "cy", "bw", "bh", "by"):
        assert g[k] % 2 == 0, f"{nama}.{k} ganjil: {g[k]}"


# --- warna dan header ---

def test_warna_dibalik_ke_bgr():
    """.ass memakai BBGGRR. Salah urutan menghasilkan warna yang terlihat
    'hampir benar' — merah jadi biru — jadi gampang lolos tanpa disadari."""
    assert L._bgr("FF0000") == "0000FF"
    assert L._bgr("#00E5FF") == "FFE500"


def test_warna_ngawur_jatuh_ke_putih():
    assert L._bgr("bukan warna") == "FFFFFF"


def test_header_memakai_font_dan_ukuran_dari_knob():
    h = L.header_ass(L.ambil("kotak"), {"font": "Anton", "ukuran": 130})
    assert "Anton,130," in h


def test_header_memakai_alignment_layout():
    h = L.header_ass(L.ambil("samping"), {})
    baris = [x for x in h.splitlines() if x.startswith("Style:")][0]
    assert baris.split(",")[18] == "6"


def test_label_rantai_menempel_tanpa_koma():
    """`setsar=1,[v]` ditolak ffmpeg dengan exit code 8 dan pesan yang menunjuk
    berkas KELUARAN, bukan filternya — jadi sangat sulit dilacak balik ke sini."""
    lay = L.ambil("kotak")
    g = L.geometri(lay, crop(fx=0.5, fy=0.4), 1920, 1080)
    vf = L.filtergraph(lay, g, "c1.ass", mask="m.png")
    assert ",[v]" not in vf
    assert "[v];movie=m.png[m];[v][m]overlay=0:0" in vf
    assert vf.endswith("subtitles=c1.ass")


def test_tanpa_mask_tidak_ada_label_rantai():
    lay = L.ambil("penuh")
    g = L.geometri(lay, crop(), 1920, 1080)
    vf = L.filtergraph(lay, g, "c1.ass")
    assert "[" not in vf and ";" not in vf


# --- samping mengikuti referensi ---
#
# Versi pertama salah di hampir semua sumbu, dan itu baru ketahuan setelah
# hasilnya disandingkan dengan klip referensi sungguhan: teks ditumpuk vertikal
# padahal referensinya satu baris, sans tebal bersorot kuning padahal
# referensinya serif putih polos, dan gelap di sisi teks dibuat sebagai bidang
# padahal di referensi ruangannya memang gelap.

def test_samping_satu_baris_bukan_ditumpuk():
    assert L.ambil("samping").tumpuk is False


def test_samping_bisa_menyorot_kata():
    """Dulu sorotan dimatikan permanen di layout ini (serif yang kalem
    dianggap keramaian). Sekarang dibiarkan menyala sama seperti layout lain
    — yang mau tampilan polos seperti referensi awal tinggal menyamakan warna
    aktif dengan putih lewat knob Submit, bukan dipaku di kode."""
    assert L.ambil("samping").sorot is True


def test_samping_tidak_tebal():
    """Serif rusak ditebalkan: libass mensintesis tebalnya, dan hasilnya blobby
    di ukuran besar."""
    assert L.ambil("samping").tebal is False


def test_samping_menyarankan_serif():
    assert L.ambil("samping").font_saran == "Lora"


def test_gradasi_samping_jauh_lebih_halus_dari_versi_awal():
    """Versi awal 0.88 terbaca sebagai bidang gelap. Sekarang perannya cuma
    asuransi keterbacaan untuk sumber yang latarnya terang."""
    _, maks = L.ambil("samping").redup
    assert maks < 0.6


def test_header_tidak_tebal_saat_layout_meminta():
    h = L.header_ass(L.ambil("samping"), {})
    baris = [x for x in h.splitlines() if x.startswith("Style:")][0]
    assert baris.split(",")[7] == "0", "flag Bold harus 0 untuk serif"


def test_header_tetap_tebal_untuk_layout_sans():
    for nama in ("penuh", "kotak"):
        baris = [x for x in L.header_ass(L.ambil(nama), {}).splitlines()
                 if x.startswith("Style:")][0]
        assert baris.split(",")[7] == "-1"


def test_layout_bersorot_tetap_punya_warna_aktif():
    """Perbaikan untuk samping jangan sampai mematikan sorotan di layout lain."""
    for nama in ("penuh", "kotak", "samping"):
        assert L.ambil(nama).sorot is True


# --- layout mentahan ---

def test_ori_tidak_punya_filter_sama_sekali():
    """String kosong, bukan rantai yang tidak melakukan apa-apa: pemanggilnya
    harus MENGHILANGKAN `-vf`, karena `-vf ""` ditolak ffmpeg."""
    lay = L.ambil("ori")
    assert L.filtergraph(lay, L.geometri(lay, crop(), 1920, 1080)) == ""


def test_ori_tidak_memotong_maupun_menskala():
    lay = L.ambil("ori")
    vf = L.filtergraph(lay, L.geometri(lay, crop(), 1920, 1080), "c1.ass")
    for f in ("crop=", "scale=", "pad=", "setsar="):
        assert f not in vf, f"{f} merusak rasio asli"


def test_ori_tidak_pernah_dapat_caption():
    """Layout menang atas knob: teks yang terbakar ke gambar tidak bisa dicabut
    lagi oleh yang mengedit ulang."""
    lay = L.ambil("ori")
    assert not L.pakai_caption(lay)
    assert not L.pakai_caption(lay, {"caption": True})


def test_ori_tidak_perlu_lapisan():
    assert not L.butuh_lapisan(L.ambil("ori"))


# --- saklar caption ---

def test_caption_nyala_kalau_knob_tidak_menyebutnya():
    """Kosong berarti ikut default, sama seperti knob tampilan lain."""
    assert L.pakai_caption(L.ambil("penuh"))
    assert L.pakai_caption(L.ambil("penuh"), {})
    assert L.pakai_caption(L.ambil("penuh"), {"font": "Anton"})


def test_caption_bisa_dimatikan_di_layout_biasa():
    assert not L.pakai_caption(L.ambil("penuh"), {"caption": False})
    assert not L.pakai_caption(L.ambil("samping"), {"caption": False})


def test_caption_mati_menghapus_subtitles_tapi_menahan_geometri():
    """Yang hilang cuma teksnya. Crop dan skala 9:16 tetap jalan — kalau ikut
    hilang, mematikan caption diam-diam berubah jadi mengganti layout."""
    lay = L.ambil("penuh")
    vf = L.filtergraph(lay, L.geometri(lay, crop(), 1920, 1080))
    assert "subtitles=" not in vf
    assert "crop=608:1080:656:0" in vf and "scale=1080:1920" in vf


def test_caption_mati_tetap_menumpuk_lapisan():
    """Sudut tumpul dan gradasi bukan bagian dari caption."""
    lay = L.ambil("kotak")
    vf = L.filtergraph(lay, L.geometri(lay, crop(fx=0.5, fy=0.4), 1920, 1080),
                       None, mask="m.png")
    assert "overlay=0:0" in vf
    assert "subtitles=" not in vf
    assert not vf.endswith(",")
