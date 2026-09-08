"""Gerbang lisensi: yang menentukan boleh-tidaknya submit job baru.

Ruang lingkupnya sempit dan sengaja begitu — ini "gerbang lisensi minimum",
bukan Fase 7 lengkap. Tujuannya membuat license key benar-benar mengontrol
sesuatu secepat mungkin, supaya trial bisa dibagikan dengan terkendali.

Tiga aturan yang tidak boleh dilanggar, dan ketiganya gampang terlanggar tanpa
sengaja:

1. **Aplikasi TIDAK PERNAH menolak start.** Tanpa key, halaman Setting harus
   tetap terbuka — di situlah key dimasukkan. Menolak start berarti key tidak
   akan pernah bisa dimasukkan sama sekali: buntu total.

2. **Gerbangnya di submit, bukan di boot.** Job yang sudah terlanjur antre
   tetap diselesaikan; lisensi bisa habis tengah malam sementara orang submit
   lima video jam sebelas. Karena itu worker/ dan pipeline/ tidak perlu tahu
   apa-apa soal modul ini.

3. **"Server bilang tidak valid" BUKAN "server tidak bisa dihubungi".** Yang
   pertama berarti turun sekarang juga. Yang kedua berarti pakai token
   tersimpan, dan kalimat di layar tidak boleh berpura-pura tahu. Client bisa
   jadi sudah membayar penuh, dan menuduhnya menunggak karena masalah jaringan
   adalah cara tercepat kehilangan kepercayaan.

Ditempatkan sebagai modul tingkat atas berisi satu berkas, mengikuti pola
storage/ yang memang cuma punya satu implementasi. Diimpor api/ saja.
"""
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from config.settings import settings
from utils.logging import get

log = get(__name__)

#: Alamat bawaan server lisensi. Bisa ditimpa lewat `LICENSE_SERVER` di .env —
#: dibutuhkan untuk staging dan untuk menguji alur lisensi sebelum DNS produksi
#: ada, karena tanpa itu tidak ada satu pun cara mencobanya dari mesin sendiri.
#:
#: Ini TIDAK melemahkan gerbangnya, dan bedanya dengan public key di bawah itu
#: penting: public key sengaja tidak bisa disetel, karena siapa pun yang bisa
#: menggantinya tinggal menandatangani token palsu miliknya sendiri. Alamat
#: server tidak begitu — server palsu tetap tidak bisa menghasilkan tanda tangan
#: yang lolos verifikasi, jadi mengarahkannya ke mana pun tidak menghasilkan
#: lisensi yang diterima. Mengarahkannya ke alamat mati pun tidak memberi apa-apa
#: yang tidak bisa dilakukan dengan memblokir domainnya di firewall.
SERVER_BAWAAN = "https://app.agentiv.my.id"
PRODUCT_ID = "capio"

#: Toleransi selisih jam sistem saat membandingkan `exp`. Jam laptop yang
#: meleset beberapa menit itu lazim, dan menolak lisensi karenanya menghasilkan
#: keluhan yang mustahil didiagnosis dari sisi client.
TOLERANSI_JAM = 300

#: Public key server, DI-EMBED — bukan dibaca dari .env. Kalau ia bisa disetel
#: pengguna, siapa pun tinggal memasang public key miliknya sendiri lalu
#: menandatangani token palsu, dan seluruh gerbang ini jadi hiasan.
#:
#: Berkasnya ikut ke dalam image saat build. Untuk rilis produksi, ganti isinya
#: dengan public key dari keypair PRODUKSI — kalau tertukar dengan keypair
#: pengembangan, setiap token ditolak dan gejalanya terlihat persis seperti
#: "lisensi tidak valid" padahal lisensinya benar.
PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "agentiv-public.pem"


def _data() -> Path:
    """Folder yang harus bertahan melewati update image.

    Bukan CLIPS_DIR (terlihat dan dikelola pengguna) dan bukan WORK_DIR (disapu
    berkala). install_id yang hilang saat update berarti slot perangkat baru
    diklaim tiap kali versi diganti — dan batas 1 atau 3 perangkat habis
    sendiri tanpa pengguna melakukan apa pun.
    """
    d = Path(settings.DATA_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_id() -> str:
    """UUID v4 yang mewakili pemasangan ini. Dibuat sekali, lalu tetap."""
    p = _data() / "install_id"
    try:
        ada = p.read_text(encoding="utf-8").strip()
        if ada:
            return ada
    except OSError:
        pass
    baru = str(uuid.uuid4())
    p.write_text(baru, encoding="utf-8")
    log.info("install_id dibuat: %s", baru)
    return baru


# --- verifikasi token ---


def _b64u(s: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class Klaim:
    key: str
    product_id: str
    plan: str
    install_id: str
    berlaku_sampai: str   # license_expires_at — INI yang ditampilkan ke user
    exp: int              # masa berlaku token, urusan internal saja


def _publik():
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    return load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())


def baca_token(token: str, sekarang: float | None = None) -> Klaim | None:
    """Klaim di dalam token, atau None kalau token tidak sah.

    Yang diperiksa: tanda tangan RS256, product_id, install_id, dan exp. Tiga
    yang pertama wajib menurut kontrak; install_id ditambahkan karena tanpa itu
    berkas license.jwt bisa disalin ke laptop lain dan batas perangkat — yang
    justru membedakan SKU 1 dan 3 perangkat — tidak menahan apa pun.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    bagian = token.split(".")
    if len(bagian) != 3:
        return None
    try:
        _publik().verify(
            _b64u(bagian[2]),
            f"{bagian[0]}.{bagian[1]}".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        klaim = json.loads(_b64u(bagian[1]))
    except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError) as e:
        log.warning("token lisensi ditolak: %s", type(e).__name__)
        return None

    if klaim.get("product_id") != PRODUCT_ID:
        log.warning("token untuk produk lain: %r", klaim.get("product_id"))
        return None
    if klaim.get("install_id") != install_id():
        log.warning("token diterbitkan untuk pemasangan lain")
        return None

    t = sekarang if sekarang is not None else time.time()
    if float(klaim.get("exp", 0)) + TOLERANSI_JAM < t:
        return None

    return Klaim(
        key=str(klaim.get("sub", "")),
        product_id=str(klaim.get("product_id", "")),
        plan=str(klaim.get("plan", "")),
        install_id=str(klaim.get("install_id", "")),
        berlaku_sampai=str(klaim.get("license_expires_at", "")),
        exp=int(klaim.get("exp", 0)),
    )


# --- simpanan lokal ---


def _simpan(token: str, catatan: dict) -> None:
    if token:
        (_data() / "license.jwt").write_text(token, encoding="utf-8")
    (_data() / "license.json").write_text(
        json.dumps(catatan, ensure_ascii=False), encoding="utf-8"
    )


def _token_tersimpan() -> str:
    try:
        return (_data() / "license.jwt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _catatan() -> dict:
    try:
        return json.loads((_data() / "license.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _hapus_token() -> None:
    """Dipanggil saat server MENJAWAB tidak valid — bukan saat gagal dihubungi.

    Membuang token pada gangguan jaringan adalah kesalahan yang paling merusak
    di seluruh modul ini: sekali terbuang, ia tidak bisa dipulihkan tanpa
    jaringan, jadi gangguan sesaat berubah jadi penghentian permanen.
    """
    try:
        (_data() / "license.jwt").unlink(missing_ok=True)
    except OSError:
        pass


# --- panggilan ke server ---


def verifikasi() -> dict:
    """Tanya server, simpan hasilnya. {ok, alasan, pesan, terhubung}.

    `terhubung` False berarti server tidak menjawab sama sekali — itu BUKAN
    jawaban, dan tidak boleh diperlakukan sebagai lisensi tidak valid.
    """
    key = (settings.LICENSE_KEY or "").strip()
    if not key:
        return {"ok": False, "alasan": "kosong", "terhubung": True,
                "pesan": "License key belum diisi."}

    try:
        r = httpx.post(
            # Dibaca saat dipanggil, bukan saat modul diimpor: halaman Setting
            # bisa mengubah .env kapan saja, dan nilai yang dibekukan saat start
            # membuat perubahannya tidak pernah berlaku.
            f"{(settings.LICENSE_SERVER or SERVER_BAWAAN).rstrip('/')}/api/license/verify",
            json={
                "license_key": key,
                "product_id": PRODUCT_ID,
                "install_id": install_id(),
                "agent_version": settings.VERSI,
            },
            timeout=20.0,
        )
        # Status selain 200 BUKAN jawaban: 429 rate limit, 5xx gangguan server.
        # Kontraknya menjawab "tidak valid" dengan 200 justru supaya keduanya
        # bisa dibedakan di sini.
        if r.status_code != 200:
            raise httpx.HTTPError(f"HTTP {r.status_code}")
        d = r.json()
    except Exception as e:  # noqa: BLE001 — gangguan jaringan bukan kegagalan lisensi
        log.warning("server lisensi tidak bisa dihubungi: %s", e)
        catatan = _catatan()
        catatan["gagal_sejak"] = catatan.get("gagal_sejak") or time.time()
        _simpan("", catatan)
        return {"ok": False, "alasan": "tak_terhubung", "terhubung": False,
                "pesan": "Server lisensi tidak bisa dihubungi."}

    if not d.get("valid"):
        alasan = str(d.get("reason", "invalid"))
        pesan = str(d.get("message", "Lisensi tidak valid."))
        log.warning("lisensi ditolak server: %s", alasan)
        _hapus_token()
        _simpan("", {"diperiksa": time.time(), "alasan": alasan, "pesan": pesan})
        return {"ok": False, "alasan": alasan, "terhubung": True, "pesan": pesan}

    token = str(d.get("token", ""))
    if baca_token(token) is None:
        # Tanda tangan tidak sah padahal server bilang valid. Hampir selalu
        # public key yang tertukar antara keypair pengembangan dan produksi.
        log.error("server mengirim token yang tidak lolos verifikasi lokal — "
                  "public key ter-embed kemungkinan besar bukan pasangannya")
        return {"ok": False, "alasan": "token_ditolak", "terhubung": True,
                "pesan": "Token dari server tidak bisa diverifikasi. "
                         "Hubungi Agentiv — ini masalah di sisi kami."}

    _simpan(token, {"diperiksa": time.time(), "alasan": "", "pesan": "",
                     "versi_terbaru": d.get("latest_version")})
    log.info("lisensi terverifikasi")
    return {"ok": True, "alasan": "", "terhubung": True, "pesan": "Lisensi aktif."}


# --- pembacaan lokal, TANPA jaringan ---


def status() -> dict:
    """Keadaan lisensi menurut token tersimpan. Tidak pernah memanggil server.

    Dipakai halaman Setting dan gerbang submit. Submit tidak boleh memanggil
    server supaya ia tidak pernah menunggu jaringan.
    """
    catatan = _catatan()
    dasar = {
        "aktif": False,
        "punya_key": bool((settings.LICENSE_KEY or "").strip()),
        "berlaku_sampai": "",
        "sisa_hari": None,
        "diperiksa": catatan.get("diperiksa"),
        "gagal_sejak": catatan.get("gagal_sejak"),
        "alasan": catatan.get("alasan", ""),
        "pesan": catatan.get("pesan", ""),
        "versi_terbaru": catatan.get("versi_terbaru"),
        "update_tersedia": _lebih_baru(catatan.get("versi_terbaru"), settings.VERSI),
    }
    if not dasar["punya_key"]:
        dasar["pesan"] = "License key belum diisi."
        return dasar

    klaim = baca_token(_token_tersimpan()) if _token_tersimpan() else None
    if klaim is None:
        if not dasar["pesan"]:
            dasar["pesan"] = ("Lisensi belum terverifikasi. Tekan Verifikasi "
                              "ulang di halaman Setting.")
        return dasar

    dasar["aktif"] = True
    dasar["berlaku_sampai"] = klaim.berlaku_sampai
    dasar["plan"] = klaim.plan
    # Dari license_expires_at, BUKAN dari exp. exp dipotong maksimal 14 hari
    # supaya jam sistem yang dimundurkan tidak bisa dipakai selamanya —
    # menampilkannya membuat client yang baru membayar 30 hari melihat
    # "14 hari lagi" lalu menghubungi Agentiv.
    dasar["sisa_hari"] = _sisa_hari(klaim.berlaku_sampai)
    dasar["pesan"] = ""
    return dasar


def _sisa_hari(iso: str) -> int | None:
    from datetime import datetime, timezone

    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((t - datetime.now(timezone.utc)).total_seconds() / 86400))


def _lebih_baru(versi_terbaru: str | None, versi_sekarang: str) -> bool:
    """True kalau versi_terbaru semver lebih baru dari versi_sekarang.

    Dibandingkan sebagai tuple angka, bukan string — "1.9.0" > "1.10.0" secara
    string padahal salah. Versi yang tidak bisa di-parse dianggap "tidak ada
    update", bukan error: field ini diisi manual oleh admin, jadi typo harus
    gagal senyap — status() wajib 100% bebas jaringan dan tidak boleh melempar.
    """
    if not versi_terbaru:
        return False
    try:
        return tuple(int(x) for x in versi_terbaru.split(".")) > \
               tuple(int(x) for x in versi_sekarang.split("."))
    except (ValueError, AttributeError):
        return False


def boleh_submit() -> tuple[bool, str]:
    """(boleh, alasan untuk ditampilkan). Ini satu-satunya gerbangnya."""
    s = status()
    if s["aktif"]:
        return True, ""

    if not s["punya_key"]:
        return False, (
            "CAPIO butuh license key untuk memproses video. Buka halaman "
            "Setting untuk memasukkannya. Klip yang sudah ada tetap bisa "
            "dibuka dan diunduh."
        )

    # Server tidak pernah menjawab, dan token tersimpan sudah lewat masanya.
    # Kalimatnya JUJUR: kita tidak tahu lisensinya habis atau tidak.
    if s.get("gagal_sejak") and not s.get("alasan"):
        return False, (
            "Submit dihentikan sementara karena server lisensi tidak bisa "
            "dihubungi. Ini belum tentu berarti lisensimu habis — kami hanya "
            "belum bisa memastikannya. Klip lama tetap bisa dibuka dan diunduh."
        )

    return False, s["pesan"] or "Lisensi tidak aktif."


def tautan_wa() -> str:
    """Tautan wa.me berisi license key, supaya client tidak perlu mengetik ulang.

    Tautan, bukan pesan otomatis: sistem lisensi tidak pernah mengirim WhatsApp
    sendiri — client yang menyapa duluan.
    """
    from urllib.parse import quote

    key = (settings.LICENSE_KEY or "").strip() or "(belum diisi)"
    teks = quote(f"Halo Agentiv, saya butuh bantuan soal lisensi CAPIO.\nKey: {key}")
    return f"https://wa.me/{settings.AGENTIV_WA}?text={teks}"
