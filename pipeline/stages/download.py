"""Stage 1: yt-dlp + ekstraksi audio.

Input  : ctx[url], ctx[workdir], ctx[deadline]
Output : source.mp4, audio.ogg (16kHz mono opus), meta.json
"""
import json
import shutil
import sys
from pathlib import Path

from config.settings import settings
# run di-alias: stage ini mengekspor run(ctx) sendiri, dan nama itu akan
# menimpa helper di namespace modul.
from utils.ffmpeg_helpers import ffmpeg, probe
from utils.ffmpeg_helpers import run as ff
from utils.logging import get
import unggah
from utils.retry import retry

log = get(__name__)

# Dibatasi 1080p. Klip akhir 1080x1920 dipotong dari tinggi penuh source, jadi
# source 1080p memberi jendela 608x1080 — sedikit di-upscale, dan itu trade-off
# yang benar dibanding mengunduh 4K yang bikin download plus decode berkali lipat.
#
# avc1 (H.264) DIPRIORITASKAN di atas AV1, walau file AV1 jauh lebih kecil
# (47MB vs 104MB untuk video 15 menit yang sama). Alasannya bukan ukuran, tapi
# jumlah decode: pipeline ini membaca source berulang kali — dua scan
# scene-detect per klip, satu sampling frame per klip, plus satu render per klip
# (~20 pass untuk 5 klip). Decode AV1 3-5x lebih mahal dari H.264, jadi hemat
# 57MB unduhan dibayar berkali lipat di CPU. `[ext=mp4]` saja tidak cukup:
# av01 juga dikemas dalam mp4, dan yt-dlp memilihnya karena lebih kecil.
FORMAT = (
    "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/"
    "bv*[height<=1080][ext=mp4]+ba/"
    "b[height<=1080]/b"
)


def _ytdlp(url: str, workdir: Path, deadline) -> None:
    ff(
        [
            sys.executable, "-m", "yt_dlp",
            "-f", FORMAT,
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--no-progress",
            "--write-info-json",
            # Tanpa ini, koneksi yang menggantung di tengah fragmen tidak pernah
            # putus sendiri — yt-dlp diam menunggu sampai deadline job habis.
            # Terjadi sungguhan: unduhan berhenti 8 menit tanpa satu byte pun,
            # padahal jaringannya sehat.
            "--socket-timeout", "30",
            "--retries", "10",
            "--fragment-retries", "10",
            # Unduh beberapa fragmen sekaligus. Video DASH YouTube dipecah jadi
            # ratusan fragmen kecil, dan satu per satu membuang waktu di latensi.
            "-N", "4",
            # Nama file literal pendek, bukan %(title)s: path Windows mentok di
            # MAX_PATH 260 dan judul YouTube bisa 100 karakter sendiri.
            "-o", "source.%(ext)s",
            url,
        ],
        deadline,
        cwd=workdir,
        # Batas per percobaan diturunkan dari anggaran job, BUKAN angka tetap.
        #
        # Dulu 1200 detik mati. Akibatnya menaikkan JOB_TIMEOUT_SEC tidak
        # menolong sama sekali untuk video panjang: berapa pun anggarannya,
        # satu percobaan unduh tetap berhenti di menit ke-20. Terukur di sini:
        # jaringan 0,16 MB/s butuh 104 menit untuk podcast 2,4 jam (0,98 GB),
        # sementara tiga percobaan @20 menit cuma menyediakan 60 menit — jadi
        # video seperti itu TIDAK PERNAH bisa selesai diunduh, dan pesan
        # errornya justru menyuruh menaikkan setelan yang tidak berpengaruh.
        #
        # Yang mencegah satu perintah menggantung selamanya bukan batas ini,
        # melainkan --socket-timeout 30 di atas: koneksi yang diam lebih dari 30
        # detik diputus, jadi waktu yang terpakai di sini selalu waktu yang
        # benar-benar dipakai mengunduh. Deadline job tetap jadi pagar terakhir.
        cap=max(1200.0, settings.JOB_TIMEOUT_SEC * 0.8),
    )


# Penyebab gagal unduh yang lazim, dan pesan yang benar untuk masing-masing.
# Membedakannya penting: gagal jaringan dan ditolak YouTube minta tindakan yang
# sama sekali berbeda, dan pesan yang salah menuduh membuat orang mengoprek
# cookie berjam-jam padahal yang putus cuma koneksinya. Terjadi sungguhan di uji
# beban — DNS host mati sesaat, dua job pulang membawa tuduhan "video private".
SEBAB = [
    (("name or service not known", "temporary failure in name resolution",
      "getaddrinfo", "nodename nor servname"),
     "Download gagal: nama domain tidak bisa di-resolve. Koneksi internet atau "
     "DNS sedang putus — videonya sendiri kemungkinan tidak bermasalah."),
    (("timed out", "timeout", "connection reset", "connection refused",
      "network is unreachable", "unable to download webpage"),
     "Download gagal: koneksi ke YouTube terputus atau terlalu lambat. "
     "Coba ulang setelah jaringan stabil."),
    (("sign in to confirm", "not a bot", "captcha"),
     "Download gagal: YouTube meminta verifikasi bot untuk IP ini. "
     "Jalankan dari koneksi rumahan, atau pasang cookies browser di yt-dlp."),
    (("private video", "members-only", "login required"),
     "Download gagal: video ini private atau khusus member."),
    (("not available in your country", "geo", "blocked"),
     "Download gagal: video diblokir untuk wilayah ini."),
    (("video unavailable", "has been removed", "does not exist"),
     "Download gagal: video tidak tersedia atau sudah dihapus."),
    # Disk penuh tidak ada hubungannya dengan video maupun jaringan, dan tanpa
    # baris ini pesannya jatuh ke "Download gagal." polos — yang mengirim orang
    # memeriksa link, VPN, dan cookies padahal yang perlu dilakukan cuma
    # mengosongkan ruang. Satu video 1080p berdurasi dua jam sendirian bisa
    # menyita sekitar 1 GB, dan folder kerja job yang GAGAL sengaja ditinggal
    # untuk diperiksa — jadi ruang habis justru paling mungkin terjadi setelah
    # beberapa kegagalan beruntun.
    (("no space left", "not enough space", "disk full", "errno 28"),
     "Download gagal: ruang disk habis. Kosongkan folder kerja atau hapus job "
     "lama dari halaman Proses — folder kerja job yang gagal sengaja tidak "
     "dibersihkan otomatis."),
]


def _sebab(teks: str) -> str:
    rendah = teks.lower()
    for penanda, pesan in SEBAB:
        if any(p in rendah for p in penanda):
            return pesan
    return "Download gagal."


def _pindahkan(ident: str, tujuan: Path) -> None:
    """Pindahkan berkas unggahan ke workdir job.

    DIPINDAH, bukan disalin: berkas sumber bisa berukuran giga, dan menyalinnya
    berarti dua salinan hidup berdampingan sepanjang job berjalan — di volume
    yang sama, pada mesin yang mungkin cuma punya 20 GB kosong.

    Namanya jadi source.mp4 apa pun wadah aslinya. ffmpeg menentukan format dari
    ISI berkas, bukan dari ekstensinya, jadi .mov dan .mkv tetap terbaca — dan
    seluruh stage sesudah ini sudah menyebut nama itu.
    """
    asal = unggah.berkas(ident)
    if tujuan.exists():
        return  # sudah dipindah di percobaan sebelumnya
    if not asal.is_file():
        raise RuntimeError(
            "Berkas yang diunggah sudah tidak ada. Kemungkinan besar terhapus "
            "penyapu berkas lama sebelum job ini sempat berjalan — unggah ulang."
        )
    shutil.move(str(asal), str(tujuan))
    log.info("sumber dari unggahan: %s (%.1f MB)",
             unggah.nama_asli(ident) or ident, tujuan.stat().st_size / 1e6)
    unggah.bersihkan(ident)


def run(ctx: dict) -> dict:
    workdir: Path = ctx["workdir"]
    deadline = ctx["deadline"]
    source = workdir / "source.mp4"
    audio = workdir / "audio.ogg"

    # Berkas yang diunggah melewati yt-dlp sepenuhnya. Ini bukan cuma jalan
    # pintas: yt-dlp bagian paling rapuh di seluruh pipeline — bot-detection
    # YouTube, cookies yang basi sendiri, dan gagalnya di tahap paling awal
    # setelah orang menunggu. Sumber yang sudah ada di disk tidak melewati satu
    # pun dari itu.
    ident = unggah.sumber(ctx["url"])
    if ident:
        _pindahkan(ident, source)
    else:
        # Retry 2x backoff 30s (PRD Bagian 6).
        try:
            retry(attempts=3, backoff=30.0)(_ytdlp)(ctx["url"], workdir, deadline)
        except Exception as e:
            raise RuntimeError(f"{_sebab(str(e))} Detail: {e}") from e

    if not source.exists():
        found = list(workdir.glob("source.*"))
        raise RuntimeError(f"source.mp4 tidak terbentuk. Ada di workdir: {found}")

    # 24kbps opus mono = ~10.8 MB/jam, jadi limit 25MB Groq baru kena di ~2.3 jam
    # audio. FLAC 16k yang disarankan docs Groq ~45 MB/jam dan sudah lewat limit
    # di menit ke-33 — jangan dipakai.
    ffmpeg(
        [
            "-i", "source.mp4", "-vn",
            "-ac", "1", "-ar", "16000",
            "-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip",
            "audio.ogg",
        ],
        deadline,
        cwd=workdir,
        cap=900,
    )

    info_path = workdir / "source.info.json"
    raw = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    v = probe(source, deadline)
    meta = {
        # Nama berkas dipakai sebagai judul untuk sumber unggahan. Tanpa itu
        # judulnya kosong, dan stage metadata kehilangan satu-satunya petunjuk
        # tentang isi video selain transkripnya sendiri.
        "title": raw.get("title", "") or unggah.nama_asli(ident or ""),
        "channel": raw.get("uploader", ""),
        "duration": v["duration"] or float(raw.get("duration", 0)),
        "width": v["width"],
        "height": v["height"],
    }
    (workdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info(
        "download selesai: %.0f detik, %dx%d, audio %.1f MB",
        meta["duration"], meta["width"], meta["height"],
        audio.stat().st_size / 1e6,
    )
    return {"source": source, "audio": audio, "meta": meta}
