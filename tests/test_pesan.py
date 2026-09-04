"""Terjemahan kegagalan jadi kalimat yang bisa ditindaklanjuti.

Yang dijaga di sini bukan susunan katanya, melainkan dua hal yang menentukan
apakah pesannya berguna: apakah SEBABNYA dikenali dengan benar, dan apakah ada
TINDAKAN yang bisa diambil. Pesan yang ramah tapi menyuruh melakukan hal yang
salah lebih buruk daripada traceback mentah — traceback setidaknya jujur bahwa
ia tidak menjelaskan apa-apa.
"""
import pytest

from utils import pesan

# Teks mentah sungguhan, disalin dari kolom error di database.
KUOTA_ELEVENLABS = (
    'RuntimeError: ElevenLabs HTTP 401: {"detail":{"type":"invalid_request",'
    '"code":"quota_exceeded","message":"This request exceeds your quota of '
    '10000. You have 704 credits remaining, while 965 credits are required for '
    'this request.","status":"quota_exceeded"}}\n\nTraceback (most recent call '
    'last):\n  File "/app/worker/orchestrator.py", line 122, in run\n'
)


def test_kuota_habis_tidak_disalahartikan_sebagai_key_salah():
    """Kasus yang sebenarnya terjadi, dan jebakannya nyata: ElevenLabs
    mengirim kuota habis dengan status HTTP 401. Kalau aturan "key ditolak"
    diperiksa lebih dulu, orangnya disuruh mengganti key yang sebetulnya
    baik-baik saja — dan kuotanya tetap habis setelah diganti."""
    m = pesan.terjemah(KUOTA_ELEVENLABS)
    assert "habis" in m["judul"].lower()
    assert "ElevenLabs" in m["judul"]
    assert "ditolak" not in m["judul"].lower()


def test_kuota_habis_menyebut_tindakan_yang_bisa_diambil():
    saran = pesan.terjemah(KUOTA_ELEVENLABS)["saran"].lower()
    assert "setting" in saran, "harus menunjuk ke mana orangnya pergi"
    assert "key" in saran


def test_tidak_ada_traceback_yang_bocor_ke_pesan():
    """Kalau teks mentahnya ikut masuk, seluruh gunanya hilang."""
    m = pesan.terjemah(KUOTA_ELEVENLABS)
    for bagian in ("Traceback", "RuntimeError", "orchestrator.py", "{"):
        assert bagian not in m["judul"] + m["saran"]


@pytest.mark.parametrize("mentah,kata", [
    ("RuntimeError: Groq HTTP 401: invalid api key", "ditolak"),
    ("RuntimeError: ElevenLabs API key kosong — isi di halaman Setting", "belum diisi"),
    ("RuntimeError: gemini HTTP 429 rate limit exceeded", "membatasi"),
    ("TimeoutError: deadline job terlampaui sebelum stage 'rendering'", "waktu"),
    ("RuntimeError: Transkrip kosong — audio kemungkinan tanpa suara", "suara"),
    ("RuntimeError: Download gagal: video ini private atau khusus member.", "private"),
    ("RuntimeError: Download gagal: ruang disk habis. no space left on device", "penyimpanan"),
    ("RuntimeError: Tidak ada segmen lolos validasi dari 12 kandidat LLM.", "klip"),
    ("RuntimeError: ffmpeg keluar dengan kode 8:\nInvalid argument", "gagal diolah"),
])
def test_sebab_dikenali(mentah, kata):
    assert kata in pesan.terjemah(mentah)["judul"].lower()


def test_penyedia_disebut_namanya():
    """"Kuota habis" tanpa menyebut kuota MILIK SIAPA tidak bisa ditindaklanjuti
    — ada empat penyedia dan masing-masing punya halaman key sendiri."""
    for kunci, nama in (("groq", "Groq"), ("openrouter", "OpenRouter"),
                        ("gemini", "Gemini")):
        m = pesan.terjemah(f"RuntimeError: {kunci} HTTP 429 quota_exceeded")
        assert nama in m["judul"]


def test_kegagalan_asing_tetap_dapat_penjelasan():
    """Yang tidak dikenali TIDAK boleh jatuh ke pesan kosong atau ke teks
    mentahnya — di situlah orang paling butuh diberi tahu harus apa."""
    m = pesan.terjemah("ZeroDivisionError: division by zero")
    assert m["judul"] and m["saran"]
    assert "ZeroDivisionError" not in m["judul"] + m["saran"]
    assert "detail teknis" in m["saran"].lower()


@pytest.mark.parametrize("kosong", [None, "", "   "])
def test_tanpa_kegagalan_tidak_mengarang_masalah(kosong):
    assert pesan.terjemah(kosong) is None


def test_ringkas_menyimpan_ekor_bukan_kepala():
    """Baris terakhir traceback memuat exception yang sebenarnya; baris awalnya
    cuma rantai pemanggil yang sama untuk hampir semua kegagalan."""
    teks = "baris awal\n" * 200 + "PENYEBAB SEBENARNYA"
    hasil = pesan.ringkas(teks, batas=100)
    assert "PENYEBAB SEBENARNYA" in hasil
    assert len(hasil) <= 101


# --- sampai ke API ---

def test_job_gagal_membawa_penjelasan_ke_ui():
    """Jalur nilainya: kolom error di database -> JobOut.masalah -> halaman
    Proses. Diturunkan saat ditampilkan, bukan disimpan, supaya job lama yang
    sudah terlanjur gagal ikut mendapat penjelasannya tanpa migrasi."""
    from api.schemas import JobOut

    j = JobOut(id="x", url="u", target_clips=3, status="failed", progress=0,
               error=KUOTA_ELEVENLABS)
    assert j.masalah["judul"]
    assert "ElevenLabs" in j.masalah["judul"]
    # Teks mentahnya tetap utuh — kalau terjemahannya meleset, yang hilang cuma
    # terjemahannya.
    assert j.error == KUOTA_ELEVENLABS


def test_job_berhasil_tidak_punya_masalah():
    from api.schemas import JobOut

    j = JobOut(id="x", url="u", target_clips=3, status="done", progress=100)
    assert j.masalah is None
