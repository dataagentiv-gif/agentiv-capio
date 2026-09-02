"""Stage 1: yt-dlp + ekstraksi audio.

Input  : ctx[url], ctx[workdir], ctx[deadline]
Output : source.mp4, audio.ogg (16kHz mono opus), meta.json
"""
import json
import sys
from pathlib import Path

# run di-alias: stage ini mengekspor run(ctx) sendiri, dan nama itu akan
# menimpa helper di namespace modul.
from utils.ffmpeg_helpers import ffmpeg, probe
from utils.ffmpeg_helpers import run as ff
from utils.logging import get
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
        cap=1200,
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
]


def _sebab(teks: str) -> str:
    rendah = teks.lower()
    for penanda, pesan in SEBAB:
        if any(p in rendah for p in penanda):
            return pesan
    return "Download gagal."


def run(ctx: dict) -> dict:
    workdir: Path = ctx["workdir"]
    deadline = ctx["deadline"]
    source = workdir / "source.mp4"
    audio = workdir / "audio.ogg"

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
        "title": raw.get("title", ""),
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
