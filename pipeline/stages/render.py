"""Stage 7: render MP4 9:16 dengan caption burned-in.

Input  : ctx[source], ctx[segments_final], ctx[crops], ctx[captions], ctx[meta]
Output : clips/{clip_id}.mp4
"""
from pathlib import Path

from utils.ffmpeg_helpers import run
from utils.logging import get
from utils.retry import retry

log = get(__name__)

OUT_W, OUT_H = 1080, 1920


def _render_one(source: Path, workdir: Path, seg: dict, crop: dict, src_h: int, deadline) -> Path:
    out = Path("clips") / f"{seg['id']}.mp4"
    vf = (
        f"crop={crop['w']}:{src_h}:{crop['x']}:0,"
        f"scale={OUT_W}:{OUT_H},setsar=1,"
        # Nama file .ass polos, tanpa path. Inilah gunanya cwd=workdir: filter
        # subtitles mem-parse argumennya sendiri, dan path Windows absolut
        # (backslash, titik dua drive, spasi di nama user) harus di-escape
        # berlapis. Dengan nama relatif, tidak ada yang perlu di-escape.
        f"subtitles={seg['id']}.ass"
    )
    run(
        [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-nostats", "-v", "error",
            # -ss WAJIB sebelum -i. Input seek melewatkan hanya frame yang
            # dibutuhkan ke filtergraph DAN me-rebase pts ke nol, sehingga
            # timestamp di file .ass benar saat dihitung relatif terhadap awal
            # klip. Output seek (-ss setelah -i) men-decode dari detik nol dan
            # membuat filter subtitles melihat timestamp absolut source.
            "-ss", f"{seg['start']:.3f}",
            "-i", "source.mp4",
            "-t", f"{seg['end'] - seg['start']:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            # Wajib per PRD: yuv420p supaya diputar di semua player, faststart
            # supaya moov atom di depan dan video bisa mulai sebelum unduh penuh.
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-movflags", "+faststart",
            str(out),
        ],
        deadline,
        cwd=workdir,
        cap=900,
    )
    return workdir / out


def run(ctx: dict) -> dict:
    workdir: Path = ctx["workdir"]
    source: Path = ctx["source"]
    src_h = int(ctx["meta"]["height"])
    deadline = ctx["deadline"]
    (workdir / "clips").mkdir(exist_ok=True)

    rendered = {}
    for seg in ctx["segments_final"]:
        crop = ctx["crops"][seg["id"]]
        # Retry 1x (PRD Bagian 6) = 2 percobaan.
        path = retry(attempts=2, backoff=2.0)(_render_one)(
            source, workdir, seg, crop, src_h, deadline
        )
        size_mb = path.stat().st_size / 1e6
        if size_mb < 0.05:
            raise RuntimeError(f"{seg['id']}.mp4 kosong ({size_mb:.2f} MB) — render gagal diam-diam")
        log.info("render %s: %.1f MB, %.1fs", seg["id"], size_mb, seg["end"] - seg["start"])
        rendered[seg["id"]] = path

    return {"rendered": rendered}
