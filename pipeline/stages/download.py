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
FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"


def _ytdlp(url: str, workdir: Path, deadline) -> None:
    ff(
        [
            sys.executable, "-m", "yt_dlp",
            "-f", FORMAT,
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--no-progress",
            "--write-info-json",
            # Nama file literal pendek, bukan %(title)s: path Windows mentok di
            # MAX_PATH 260 dan judul YouTube bisa 100 karakter sendiri.
            "-o", "source.%(ext)s",
            url,
        ],
        deadline,
        cwd=workdir,
        cap=1200,
    )


def run(ctx: dict) -> dict:
    workdir: Path = ctx["workdir"]
    deadline = ctx["deadline"]
    source = workdir / "source.mp4"
    audio = workdir / "audio.ogg"

    # Retry 2x backoff 30s (PRD Bagian 6). Penyebab gagal permanen yang lazim:
    # video private, geo-block, atau bot-detection YouTube.
    try:
        retry(attempts=3, backoff=30.0)(_ytdlp)(ctx["url"], workdir, deadline)
    except Exception as e:
        raise RuntimeError(
            f"Download gagal. Kemungkinan video private, geo-block, atau "
            f"bot-detection YouTube. Detail: {e}"
        ) from e

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
