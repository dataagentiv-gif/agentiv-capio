"""Pesan gagal unduh harus menunjuk penyebab yang benar.

Ini bukan soal kosmetik. Gagal jaringan dan ditolak YouTube minta tindakan yang
berbeda total, dan pesan yang salah menuduh mengirim orang mengoprek cookie
berjam-jam padahal koneksinya yang putus — persis yang terjadi di uji beban.
"""
import pytest

from pipeline.stages.download import _sebab


@pytest.mark.parametrize("stderr,harus_ada", [
    # Yang benar-benar muncul di log saat DNS host mati.
    ("ERROR: [youtube] Unable to download API page: [Errno -2] "
     "Name or service not known (caused by TransportError)", "DNS"),
    ("URLError: <urlopen error [Errno -3] Temporary failure in name resolution>", "DNS"),
    ("ERROR: unable to download video data: <urlopen error timed out>", "terputus"),
    ("ERROR: [youtube] Sign in to confirm you're not a bot", "verifikasi bot"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
     "private"),
    ("ERROR: [youtube] abc: Video unavailable", "tidak tersedia"),
])
def test_penyebab_dikenali(stderr, harus_ada):
    assert harus_ada in _sebab(stderr)


def test_error_asing_tidak_menuduh_apa_pun():
    """Kalau tidak dikenali, jangan menebak — detail mentahnya tetap dilampirkan."""
    pesan = _sebab("ERROR: sesuatu yang belum pernah kita lihat")
    assert pesan == "Download gagal."


def test_jaringan_tidak_disalahartikan_sebagai_bot_detection():
    """Regresi: satu-satunya kesalahan yang benar-benar merugikan."""
    pesan = _sebab("[Errno -2] Name or service not known")
    assert "bot" not in pesan.lower()
    assert "private" not in pesan.lower()


# --- batas waktu per percobaan unduh ---
#
# Dulu 1200 detik mati, dan itu membuat JOB_TIMEOUT_SEC jadi setelan bohong:
# berapa pun anggaran job dinaikkan, satu percobaan unduh tetap berhenti di
# menit ke-20. Terukur: jaringan 0,16 MB/s butuh 104 menit untuk podcast 2,4
# jam, sementara tiga percobaan @20 menit cuma menyediakan 60 menit — video
# seperti itu tidak akan pernah selesai diunduh, dan pesan errornya justru
# menyuruh menaikkan setelan yang tidak berpengaruh.

def _cap_terpakai(monkeypatch, budget):
    from config.settings import settings
    from pipeline.stages import download

    monkeypatch.setattr(settings, "JOB_TIMEOUT_SEC", budget)
    dicatat = {}
    monkeypatch.setattr(download, "ff",
                        lambda *a, **k: dicatat.update(cap=k.get("cap")))
    download._ytdlp("https://youtu.be/x", __import__("pathlib").Path("."), None)
    return dicatat["cap"]


def test_batas_unduh_ikut_naik_saat_anggaran_dinaikkan(monkeypatch):
    """Inilah inti perbaikannya: menaikkan JOB_TIMEOUT_SEC harus benar-benar
    memberi unduhan waktu lebih banyak."""
    kecil = _cap_terpakai(monkeypatch, 1800)
    besar = _cap_terpakai(monkeypatch, 10800)
    assert besar > kecil, "batas unduh tidak ikut naik — setelannya jadi bohong"


def test_batas_unduh_menyisakan_waktu_untuk_stage_lain(monkeypatch):
    """Unduhan tidak boleh boleh menghabiskan seluruh anggaran: transkrip,
    render, dan metadata masih harus kebagian."""
    assert _cap_terpakai(monkeypatch, 10800) < 10800


def test_anggaran_kecil_tetap_punya_lantai_wajar(monkeypatch):
    """Anggaran job yang sangat kecil jangan sampai memberi unduhan waktu yang
    terlalu pendek untuk video pendek sekalipun."""
    assert _cap_terpakai(monkeypatch, 600) >= 1200
