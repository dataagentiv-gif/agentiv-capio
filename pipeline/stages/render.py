"""Stage 7: render MP4 9:16 dengan caption burned-in.

Input  : ctx[source], ctx[segments_final], ctx[crops], ctx[captions], ctx[meta]
Output : clips/{clip_id}.mp4
"""
from pathlib import Path

from config.settings import settings
from pipeline import layout
# Di-alias: tiap stage mengekspor run(ctx) sendiri, dan nama itu akan
# menimpa helper ini di namespace modul.
from utils.ffmpeg_helpers import run as ff
from utils.logging import get
from utils.retry import retry

log = get(__name__)

OUT_W, OUT_H = 1080, 1920


def _mask(workdir: Path, lay, g: dict, deadline) -> str:
    """Gambar hitam berlubang persegi-sudut-tumpul, untuk ditumpuk di atas video.

    Sudut tumpul tanpa filter per-piksel-per-frame. Karena latarnya hitam solid,
    tidak perlu transparansi sungguhan: cukup menimpakan gambar hitam yang
    berlubang di posisi kotaknya. `geq` yang menghitung lubang itu berat, tapi
    cuma jalan SEKALI pada satu gambar diam — bukan pada tiap frame video.

    Berkasnya dipakai ulang untuk semua klip dalam job yang sama, karena
    geometri kotaknya tidak berubah antar klip.
    """
    nama = f"mask{g['bw']}x{g['bh']}r{lay.radius}.png"
    if (workdir / nama).exists():
        return nama

    r = lay.radius
    x0, y0 = g["bx"], g["by"]
    x1, y1 = x0 + g["bw"], y0 + g["bh"]
    # Alpha 0 (tembus) di dalam persegi yang sudutnya dibulatkan, 255 di luar.
    # Jarak ke pusat lingkaran sudut dipakai untuk menentukan di dalam/di luar.
    dalam = (
        f"between(X,{x0 + r},{x1 - r})*between(Y,{y0},{y1})"
        f"+between(X,{x0},{x1})*between(Y,{y0 + r},{y1 - r})"
        f"+lt(hypot(X-{x0 + r},Y-{y0 + r}),{r})"
        f"+lt(hypot(X-{x1 - r},Y-{y0 + r}),{r})"
        f"+lt(hypot(X-{x0 + r},Y-{y1 - r}),{r})"
        f"+lt(hypot(X-{x1 - r},Y-{y1 - r}),{r})"
    )
    ff(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
         "-f", "lavfi", "-i", f"color=black:s={OUT_W}x{OUT_H}:d=1",
         "-frames:v", "1",
         "-vf", f"format=rgba,geq=r=0:g=0:b=0:a='255*lt({dalam},1)'",
         nama],
        deadline, cwd=workdir, cap=120,
    )
    return nama


def _render_one(source: Path, workdir: Path, seg: dict, crop: dict,
                src_w: int, src_h: int, deadline) -> Path:
    out = Path("clips") / f"{seg['id']}.mp4"
    lay = layout.ambil(settings.CLIP_LAYOUT)
    g = layout.geometri(lay, crop, src_w, src_h)
    mask = _mask(workdir, lay, g, deadline) if lay.radius else None
    # Nama file polos, tanpa path. Inilah gunanya cwd=workdir: filter subtitles
    # dan movie mem-parse argumennya sendiri, dan path Windows absolut
    # (backslash, titik dua drive, spasi di nama user) harus di-escape berlapis.
    # Dengan nama relatif, tidak ada yang perlu di-escape.
    vf = layout.filtergraph(lay, g, f"{seg['id']}.ass", mask)
    ff(
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
    src_w = int(ctx["meta"]["width"])
    src_h = int(ctx["meta"]["height"])
    deadline = ctx["deadline"]
    (workdir / "clips").mkdir(exist_ok=True)

    log.info("render memakai layout '%s'", layout.ambil(settings.CLIP_LAYOUT).nama)

    rendered = {}
    for seg in ctx["segments_final"]:
        crop = ctx["crops"][seg["id"]]
        # Retry 1x (PRD Bagian 6) = 2 percobaan.
        path = retry(attempts=2, backoff=2.0)(_render_one)(
            source, workdir, seg, crop, src_w, src_h, deadline
        )
        size_mb = path.stat().st_size / 1e6
        if size_mb < 0.05:
            raise RuntimeError(f"{seg['id']}.mp4 kosong ({size_mb:.2f} MB) — render gagal diam-diam")
        log.info("render %s: %.1f MB, %.1fs", seg["id"], size_mb, seg["end"] - seg["start"])
        rendered[seg["id"]] = path

    return {"rendered": rendered}
