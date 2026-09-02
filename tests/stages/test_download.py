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
