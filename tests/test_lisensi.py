"""Gerbang lisensi.

Tiga aturan yang paling mudah terlanggar tanpa sengaja, dan ketiganya diuji di
sini karena melanggarnya tidak menghasilkan satu pun error:

1. Aplikasi tidak boleh menolak start. Tanpa key, halaman Setting harus tetap
   terbuka — kalau tidak, key tidak akan pernah bisa dimasukkan sama sekali.
2. Gerbangnya di ENDPOINT, bukan cuma tombol UI. Tombol yang di-disable bisa
   dilewati dengan satu perintah curl.
3. "Server bilang tidak valid" BUKAN "server tidak bisa dihubungi". Yang kedua
   tidak boleh dilaporkan sebagai lisensi kedaluwarsa, dan tidak boleh
   membuang token tersimpan.
"""
import json
import time
from pathlib import Path

import pytest

import license as lisensi

RSA = pytest.importorskip("cryptography")


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "LICENSE_KEY", "AGV-CAP-SG-K7M2QX4P")
    return tmp_path


@pytest.fixture(scope="module")
def kunci():
    """Keypair khusus uji. Public key produksi TIDAK dipakai di sini — token uji
    memang harus ditandatangani kunci yang kita pegang sendiri."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, pem


@pytest.fixture(autouse=True)
def pakai_kunci_uji(kunci, tmp_path, monkeypatch):
    _, pem = kunci
    p = tmp_path / "uji-public.pem"
    p.write_bytes(pem)
    monkeypatch.setattr(lisensi, "PUBLIC_KEY_PATH", p)


def buat_token(kunci, **timpa) -> str:
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    priv, _ = kunci
    sekarang = int(time.time())
    klaim = {
        "sub": "AGV-CAP-SG-K7M2QX4P",
        "product_id": "capio",
        "plan": "tier2",
        "features": [],
        "install_id": lisensi.install_id(),
        "license_expires_at": "2026-12-01T00:00:00+00:00",
        "iat": sekarang,
        "exp": sekarang + 7 * 86400,
    }
    klaim.update(timpa)

    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(klaim).encode())
    sig = priv.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(sig)}"


# --- install_id ---

def test_install_id_tetap_sama_setiap_dipanggil():
    assert lisensi.install_id() == lisensi.install_id()


def test_install_id_bertahan_di_disk(data):
    ident = lisensi.install_id()
    assert (data / "install_id").read_text(encoding="utf-8").strip() == ident


# --- verifikasi token ---

def test_token_sah_diterima(kunci):
    k = lisensi.baca_token(buat_token(kunci))
    assert k is not None
    assert k.berlaku_sampai.startswith("2026-12-01")


def test_tanda_tangan_palsu_ditolak(kunci):
    """Inti seluruh gerbang ini. Kalau lolos, siapa pun bisa mengarang token."""
    t = buat_token(kunci)
    head, body, sig = t.split(".")
    palsu = buat_token(kunci, license_expires_at="2099-01-01T00:00:00+00:00")
    assert lisensi.baca_token(f"{palsu.split('.')[0]}.{palsu.split('.')[1]}.{sig}") is None


def test_token_untuk_produk_lain_ditolak(kunci):
    assert lisensi.baca_token(buat_token(kunci, product_id="agen-lain")) is None


def test_token_untuk_pemasangan_lain_ditolak(kunci):
    """Tanpa ini, license.jwt tinggal disalin ke laptop lain dan batas perangkat
    — yang justru membedakan SKU 1 dan 3 perangkat — tidak menahan apa pun."""
    assert lisensi.baca_token(
        buat_token(kunci, install_id="00000000-0000-4000-8000-000000000000")) is None


def test_token_kedaluwarsa_ditolak(kunci):
    lewat = int(time.time()) - 10 * 86400
    assert lisensi.baca_token(buat_token(kunci, exp=lewat)) is None


def test_selisih_jam_kecil_dimaafkan(kunci):
    """Jam laptop yang meleset beberapa menit itu lazim. Menolak lisensi
    karenanya menghasilkan keluhan yang mustahil didiagnosis dari sisi client."""
    baru_lewat = int(time.time()) - 100
    assert lisensi.baca_token(buat_token(kunci, exp=baru_lewat)) is not None


def test_token_ngawur_tidak_bikin_crash():
    for jelek in ("", "bukan.token", "a.b.c", "x" * 500):
        assert lisensi.baca_token(jelek) is None


# --- status dibaca tanpa jaringan ---

def test_status_memakai_license_expires_at_bukan_exp(kunci, data):
    """exp dipotong maksimal 14 hari supaya jam yang dimundurkan tidak bisa
    dipakai selamanya. Menampilkannya membuat client yang baru membayar 30 hari
    melihat "14 hari lagi" lalu menghubungi Agentiv."""
    (data / "license.jwt").write_text(
        buat_token(kunci,
                   license_expires_at="2026-12-01T00:00:00+00:00",
                   exp=int(time.time()) + 3 * 86400),
        encoding="utf-8")
    s = lisensi.status()
    assert s["aktif"] is True
    assert s["berlaku_sampai"].startswith("2026-12-01")
    assert s["sisa_hari"] > 30    # dari license_expires_at, bukan exp 3 hari


def test_status_tanpa_key_tidak_memanggil_jaringan(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "LICENSE_KEY", "")
    monkeypatch.setattr(lisensi.httpx, "post",
                        lambda *a, **k: pytest.fail("tidak boleh memanggil server"))
    s = lisensi.status()
    assert s["aktif"] is False and s["punya_key"] is False


# --- gerbang submit ---

def test_tanpa_key_submit_diblokir_dengan_arahan(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "LICENSE_KEY", "")
    boleh, alasan = lisensi.boleh_submit()
    assert boleh is False
    assert "Setting" in alasan
    # Klip lama tetap bisa dibuka — itu harus disebut, bukan disimpulkan sendiri.
    assert "diunduh" in alasan


def test_token_sah_membuka_submit(kunci, data):
    (data / "license.jwt").write_text(buat_token(kunci), encoding="utf-8")
    assert lisensi.boleh_submit()[0] is True


# --- server menjawab vs server diam ---

class _Balasan:
    def __init__(self, code, isi):
        self.status_code, self._isi = code, isi

    def json(self):
        return self._isi


def test_server_bilang_tidak_valid_membuang_token(kunci, data, monkeypatch):
    """Server sudah menjawab — ini bukan gangguan jaringan. Turun sekarang."""
    (data / "license.jwt").write_text(buat_token(kunci), encoding="utf-8")
    monkeypatch.setattr(lisensi.httpx, "post", lambda *a, **k: _Balasan(
        200, {"valid": False, "reason": "revoked", "message": "Lisensi ini dicabut."}))

    hasil = lisensi.verifikasi()
    assert hasil["ok"] is False and hasil["terhubung"] is True
    assert hasil["pesan"] == "Lisensi ini dicabut."
    assert not (data / "license.jwt").exists()


def test_server_tidak_terhubung_TIDAK_membuang_token(kunci, data, monkeypatch):
    """Kesalahan paling merusak di seluruh modul ini. Sekali token terbuang, ia
    tidak bisa dipulihkan tanpa jaringan — jadi gangguan sesaat berubah jadi
    penghentian permanen."""
    (data / "license.jwt").write_text(buat_token(kunci), encoding="utf-8")

    def mati(*a, **k):
        raise lisensi.httpx.ConnectError("jaringan mati")

    monkeypatch.setattr(lisensi.httpx, "post", mati)
    hasil = lisensi.verifikasi()
    assert hasil["terhubung"] is False
    assert (data / "license.jwt").exists()
    # Dan submit tetap jalan selama token belum lewat masanya.
    assert lisensi.boleh_submit()[0] is True


def test_server_diam_tidak_pernah_menulis_kedaluwarsa(data, monkeypatch):
    """Client bisa jadi sudah membayar penuh. Menuduhnya menunggak karena
    masalah jaringan adalah cara tercepat kehilangan kepercayaan."""
    def mati(*a, **k):
        raise lisensi.httpx.ConnectError("jaringan mati")

    monkeypatch.setattr(lisensi.httpx, "post", mati)
    lisensi.verifikasi()
    _, alasan = lisensi.boleh_submit()
    assert "kedaluwarsa" not in alasan.lower()
    assert "habis" not in alasan.lower() or "belum tentu" in alasan.lower()


def test_status_429_diperlakukan_sebagai_gangguan_bukan_jawaban(data, monkeypatch):
    """Rate limit bukan jawaban. Kontraknya menjawab 'tidak valid' dengan 200
    justru supaya keduanya bisa dibedakan."""
    monkeypatch.setattr(lisensi.httpx, "post",
                        lambda *a, **k: _Balasan(429, {"valid": False}))
    assert lisensi.verifikasi()["terhubung"] is False


def test_token_yang_tidak_lolos_verifikasi_lokal_ditolak(data, monkeypatch):
    """Server bilang valid tapi tanda tangannya tidak cocok — hampir selalu
    public key yang tertukar antara keypair pengembangan dan produksi."""
    monkeypatch.setattr(lisensi.httpx, "post", lambda *a, **k: _Balasan(
        200, {"valid": True, "token": "a.b.c", "plan": "tier2"}))
    hasil = lisensi.verifikasi()
    assert hasil["ok"] is False
    assert hasil["terhubung"] is True


# --- tautan bantuan ---

def test_tautan_wa_membawa_key(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "LICENSE_KEY", "AGV-CAP-SG-ABCD1234")
    assert "AGV-CAP-SG-ABCD1234" in lisensi.tautan_wa()
    assert lisensi.tautan_wa().startswith("https://wa.me/")
