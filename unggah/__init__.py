"""Penampungan berkas video yang diunggah, sebelum job memprosesnya.

Modul tingkat atas, bukan bagian dari api/, dan itu bukan selera penataan:
aturan lapisan repo ini melarang pipeline/stages/* mengimpor api/. Stage
download butuh tahu di mana berkas unggahan berada, jadi pengetahuan itu harus
tinggal di modul yang boleh diimpor keduanya — pola yang sama dengan storage/.

Kenapa ada: sampai sekarang satu-satunya sumber video adalah link YouTube, dan
`JobCreate` bahkan MENOLAK apa pun selain host YouTube. Itu memblokir pemakaian
yang justru jadi target komersial — operator jasa clipper dan agensi umumnya
punya rekamannya sendiri: podcast, Zoom, kamera.

Ada alasan kedua yang tidak kalah penting: yt-dlp adalah bagian paling rapuh di
seluruh pipeline. Ia kena bot-detection YouTube, butuh cookies yang basi
sendiri, dan gagal di tahap paling awal setelah orang sudah menunggu. Berkas
yang diunggah melewati semuanya.

Berkasnya ditampung di WORK_DIR, bukan CLIPS_DIR: ini bahan mentah yang berumur
pendek, sementara CLIPS_DIR isinya hasil jadi yang dikelola pengguna. Unggahan
yang tidak pernah jadi job dibersihkan `sapu_lama()` saat worker menyala —
BUKAN oleh `rmtree_stale`, yang sengaja hanya mengenali folder workdir job.
"""
import json
import re
import time
import uuid
from pathlib import Path

from config.settings import settings
from utils.logging import get

log = get(__name__)

#: Penanda di kolom `url` milik job. Bentuk ini yang membedakan job unggahan
#: dari job link YouTube tanpa menambah kolom baru di database.
AWALAN = "unggah:"

#: Batas kepercayaan. Nilai di kolom `url` ikut menyusun path di disk, jadi
#: bentuknya dikunci ke UUID — bukan sekadar "bukan URL YouTube".
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: Wadah yang ffmpeg bisa baca dan lazim keluar dari kamera, HP, Zoom, maupun
#: hasil ekspor editor. Dicek dari nama berkas hanya untuk menolak salah pilih
#: lebih awal — yang menentukan tetap isinya, dan itu diperiksa ffprobe.
EKSTENSI = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg",
            ".ts", ".flv", ".wmv", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus"}


def folder() -> Path:
    d = Path(settings.WORK_DIR) / "unggah"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sumber(nilai: str) -> str | None:
    """Id unggahan dari nilai kolom `url`, atau None kalau itu link biasa."""
    if not str(nilai).startswith(AWALAN):
        return None
    ident = str(nilai)[len(AWALAN):]
    return ident if _ID.match(ident) else None


def berkas(ident: str) -> Path:
    return folder() / ident


def nama_asli(ident: str) -> str:
    """Nama berkas yang diunggah pengguna, untuk dipakai sebagai judul.

    Disimpan terpisah, bukan ditempelkan ke nilai kolom `url`: nama berkas bisa
    memuat karakter apa saja termasuk pemisah path, dan menyusun path dari nama
    yang dikirim pengguna adalah cara paling umum untuk bocor keluar folder.
    """
    p = folder() / f"{ident}.json"
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("nama", ""))
    except Exception:  # noqa: BLE001 — judul kosong bukan alasan menggagalkan job
        return ""


def catat_nama(ident: str, nama: str) -> None:
    (folder() / f"{ident}.json").write_text(
        json.dumps({"nama": nama[:200]}, ensure_ascii=False), encoding="utf-8"
    )


def baru() -> tuple[str, Path]:
    ident = str(uuid.uuid4())
    return ident, berkas(ident)


def sapu_lama(umur_jam: float = 24.0) -> int:
    """Buang berkas unggahan yang tidak pernah jadi job.

    Orang membatalkan submit setelah berkasnya terlanjur terunggah, dan yang
    tertinggal berukuran giga. Tanpa penyapuan, itu kebocoran disk yang tumbuh
    diam-diam di volume yang sama dengan video kerja.

    TIDAK ikut disapu `rmtree_stale`: penyapu itu sengaja hanya mengenali folder
    workdir job. Unggahan punya siklus hidupnya sendiri dan batas umurnya jauh
    lebih pendek.
    """
    batas = time.time() - umur_jam * 3600
    dibuang = 0
    for p in folder().iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < batas:
                besar = p.stat().st_size
                p.unlink()
                dibuang += 1
                log.info("unggahan tak terpakai disapu: %s (%.1f MB)",
                         p.name, besar / 1e6)
        except OSError as e:
            log.debug("gagal menyapu %s: %s", p.name, e)
    return dibuang


def bersihkan(ident: str) -> None:
    """Buang berkas tampungan beserta sidecarnya.

    Dipanggil setelah berkasnya dipindah ke workdir job. Ditinggal, ia jadi
    salinan kedua dari video berukuran giga yang tidak pernah dibaca siapa pun.
    """
    for p in (berkas(ident), folder() / f"{ident}.json"):
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            log.debug("sisa unggahan %s tidak terhapus: %s", p.name, e)
