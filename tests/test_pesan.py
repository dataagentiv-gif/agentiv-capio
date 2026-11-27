"""Terjemahan kegagalan jadi kalimat yang bisa ditindaklanjuti.

Yang dijaga di sini bukan susunan katanya, melainkan dua hal yang menentukan
apakah pesannya berguna: apakah SEBABNYA dikenali dengan benar, dan apakah ada
TINDAKAN yang bisa diambil. Pesan yang ramah tapi menyuruh melakukan hal yang
salah lebih buruk daripada traceback mentah — traceback setidaknya jujur bahwa
ia tidak menjelaskan apa-apa.
"""
import pytest

from utils import pesan

# Bentuknya sintetis, tapi regresinya nyata: ElevenLabs (sudah dibuang) dulu
# betulan mengirim kuota habis dengan status HTTP 401, bukan 429 yang lazim.
# Dipertahankan sebagai jaring pengaman kalau provider lain suatu saat
# melakukan hal serupa.
KUOTA_401 = (
    'RuntimeError: Gemini HTTP 401: {"detail":{"type":"invalid_request",'
    '"code":"quota_exceeded","message":"This request exceeds your quota of '
    '10000. You have 704 credits remaining, while 965 credits are required for '
    'this request.","status":"quota_exceeded"}}\n\nTraceback (most recent call '
    'last):\n  File "/app/worker/orchestrator.py", line 122, in run\n'
)


def test_kuota_habis_tidak_disalahartikan_sebagai_key_salah():
    """Kalau aturan "key ditolak" diperiksa lebih dulu untuk kode 401, orangnya
    disuruh mengganti key yang sebetulnya baik-baik saja — dan kuotanya tetap
    habis setelah diganti."""
    m = pesan.terjemah(KUOTA_401)
    assert "habis" in m["judul"].lower()
    assert "Gemini" in m["judul"]
    assert "ditolak" not in m["judul"].lower()


def test_kuota_habis_menyebut_tindakan_yang_bisa_diambil():
    saran = pesan.terjemah(KUOTA_401)["saran"].lower()
    assert "setting" in saran, "harus menunjuk ke mana orangnya pergi"
    assert "key" in saran


def test_tidak_ada_traceback_yang_bocor_ke_pesan():
    """Kalau teks mentahnya ikut masuk, seluruh gunanya hilang."""
    m = pesan.terjemah(KUOTA_401)
    for bagian in ("Traceback", "RuntimeError", "orchestrator.py", "{"):
        assert bagian not in m["judul"] + m["saran"]


@pytest.mark.parametrize("mentah,kata", [
    ("RuntimeError: Groq HTTP 401: invalid api key", "ditolak"),
    ("RuntimeError: Gemini API key kosong — isi di halaman Setting", "belum diisi"),
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


# --- nama model yang sudah dipensiunkan ---

MODEL_MATI = (
    'LLMError: gemini gagal setelah 3x: HTTP 404 [{"error": {"code": 404, '
    '"message": "This model models/gemini-2.5-pro is no longer available to new '
    'users. Please update your code to use models/gemini-3.1-pro-preview"}}]'
)


def test_model_pensiun_tidak_disalahartikan_sebagai_key_salah():
    """Google memensiunkan nama model berversi untuk akun BARU sementara akun
    lama tetap bisa memakainya — jadi setelan yang disalin dari mesin lain mati
    di mesin ini saja, dan gejalanya sangat mirip key yang salah. Kalau salah
    didiagnosis, orangnya menghapus key yang baik-baik saja."""
    m = pesan.terjemah(MODEL_MATI)
    assert "model" in m["judul"].lower()
    assert "ditolak" not in m["judul"].lower()
    assert "key" not in m["judul"].lower()


def test_model_pensiun_menyuruh_pakai_alias():
    saran = pesan.terjemah(MODEL_MATI)["saran"].lower()
    assert "-latest" in saran, "alias adalah satu-satunya bentuk yang tidak ikut pensiun"
    assert "setting" in saran


# --- pesan tombol tes koneksi ---

def test_tes_koneksi_membedakan_model_salah_dari_key_salah():
    from api import checks

    m = checks._pesan("gemini", 404, "models/gemini-2.5-pro is no longer available")
    assert "model" in m.lower()
    assert "-latest" in m


def test_tes_koneksi_membedakan_tanpa_jatah_gratis_dari_kuota_habis():
    """Dua hal yang sangat berbeda memakai kode yang sama. Model kelas pro
    menjawab 429 karena memang tidak punya jatah gratis sama sekali — menunggu
    tidak akan pernah menolong, dan menyuruh menunggu justru menyesatkan."""
    from api import checks

    tanpa_jatah = checks._pesan(
        "gemini", 429,
        "You exceeded your current quota, please check your plan and billing details.")
    assert "tidak punya jatah gratis" in tanpa_jatah.lower()

    biasa = checks._pesan("gemini", 429, "rate limit exceeded, retry later")
    assert biasa == "Kuota habis (429)"


def test_penyedia_disebut_namanya():
    """"Kuota habis" tanpa menyebut kuota MILIK SIAPA tidak bisa ditindaklanjuti
    — penyedia yang tidak dikenali jatuh ke pesan generik, bukan diam-diam
    tidak menyebut siapa pun."""
    m = pesan.terjemah("RuntimeError: gemini HTTP 429 quota_exceeded")
    assert "Gemini" in m["judul"]


def test_kegagalan_asing_tetap_dapat_penjelasan():
    """Yang tidak dikenali TIDAK boleh jatuh ke pesan kosong atau ke teks
    mentahnya — di situlah orang paling butuh diberi tahu harus apa."""
    m = pesan.terjemah("ZeroDivisionError: division by zero")
    assert m["judul"] and m["saran"]
    assert "ZeroDivisionError" not in m["judul"] + m["saran"]
    assert "detail teknis" in m["saran"].lower()


def test_worker_mati_menyuruh_nyalakan_docker_dan_proses_ulang():
    m = pesan.terjemah(
        "Worker berhenti saat job masih di tahap 'rendering'. Job tidak dilanjutkan otomatis."
    )
    assert "worker" in m["judul"].lower()
    assert "docker" in m["saran"].lower()
    assert "proses ulang" in m["saran"].lower()


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
               error=KUOTA_401)
    assert j.masalah["judul"]
    assert "Gemini" in j.masalah["judul"]
    # Teks mentahnya tetap utuh — kalau terjemahannya meleset, yang hilang cuma
    # terjemahannya.
    assert j.error == KUOTA_401


def test_job_berhasil_tidak_punya_masalah():
    from api.schemas import JobOut

    j = JobOut(id="x", url="u", target_clips=3, status="done", progress=100)
    assert j.masalah is None


def test_penolakan_seleksi_tidak_menyarankan_melonggarkan_durasi():
    result = pesan.terjemah("RuntimeError: Tidak ada segmen lolos validasi setelah seleksi dan satu koreksi. Batas 30-90s; alasan: too_long.")
    assert "longgarkan" not in result["saran"].lower()
    assert "koreksi" in result["saran"].lower()
