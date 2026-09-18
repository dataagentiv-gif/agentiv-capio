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


def _gradient_expr(lay) -> str | None:
    """Ekspresi alpha ffmpeg; nol di area wajah, 255 di ujung luar."""
    if not lay.redup:
        return None
    mulai, maks = lay.redup
    if lay.redup_sisi == "kiri":
        batas = (1 - mulai) * OUT_W
        langkah = f"({batas:.0f}-X)/{max(1.0, batas):.0f}"
    else:
        batas = mulai * OUT_W
        langkah = f"(X-{batas:.0f})/{max(1.0, OUT_W - 1 - batas):.0f}"
    return f"{maks * 255:.0f}*pow(clip({langkah},0,1),1.6)"


def _gradient_alpha_at(lay, x: float) -> int:
    """Nilai referensi untuk menguji arah dan batas gradasi produksi."""
    if not lay.redup:
        return 0
    mulai, maks = lay.redup
    if lay.redup_sisi == "kiri":
        batas = (1 - mulai) * OUT_W
        p = (batas - x) / max(1.0, batas)
    else:
        batas = mulai * OUT_W
        p = (x - batas) / max(1.0, OUT_W - 1 - batas)
    return round(maks * 255 * max(0.0, min(1.0, p)) ** 1.6)


def _mask(workdir: Path, lay, g: dict, deadline) -> str:
    """Gambar hitam beralpha untuk ditumpuk di atas video.

    Menangani dua hal sekaligus, keduanya tanpa filter per-piksel-per-frame:

    - **Sudut tumpul.** Latarnya hitam solid, jadi tidak perlu transparansi
      sungguhan — cukup menimpakan gambar hitam yang berlubang di posisi
      kotaknya.
    - **Gradasi gelap dari kanan**, sebagai alas teks. Ini yang TIDAK bisa
      dikerjakan `drawbox`: kotak beralpha rata meninggalkan garis batas yang
      terlihat jelas dan membelah frame jadi dua bidang, sementara yang dituju
      adalah tepi pekat yang memudar tanpa batas yang bisa ditunjuk.

    `geq` memang berat, tapi cuma jalan SEKALI pada satu gambar diam — bukan
    pada tiap frame video. Berkasnya dipakai ulang untuk semua klip dalam job
    yang sama, karena geometrinya tidak berubah antar klip.
    """
    r = lay.redup
    # round, bukan int: int(0.29 * 100) = 28, jadi dua setelan berbeda bisa
    # berbagi nama berkas dan yang kedua memakai gambar milik yang pertama.
    nama = (f"lapis{g['bw']}x{g['bh']}r{lay.radius}{lay.redup_sisi}"
            f"g{round(r[0] * 100) if r else 0}_{round(r[1] * 100) if r else 0}.png")
    if (workdir / nama).exists():
        return nama

    bagian = []

    if lay.radius:
        rr = lay.radius
        x0, y0 = g["bx"], g["by"]
        x1, y1 = x0 + g["bw"], y0 + g["bh"]
        # Di dalam persegi bersudut bulat -> alpha 0 (tembus), di luar -> 255.
        # Jarak ke pusat lingkaran sudut menentukan di dalam/di luar.
        dalam = (
            f"between(X,{x0 + rr},{x1 - rr})*between(Y,{y0},{y1})"
            f"+between(X,{x0},{x1})*between(Y,{y0 + rr},{y1 - rr})"
            f"+lt(hypot(X-{x0 + rr},Y-{y0 + rr}),{rr})"
            f"+lt(hypot(X-{x1 - rr},Y-{y0 + rr}),{rr})"
            f"+lt(hypot(X-{x0 + rr},Y-{y1 - rr}),{rr})"
            f"+lt(hypot(X-{x1 - rr},Y-{y1 - rr}),{rr})"
        )
        bagian.append(f"255*lt({dalam},1)")

    if r:
        # Pangkat 1.6, bukan lurus: gradasi linear masih menyisakan tepi awal
        # yang terasa sebagai garis. Kurva yang mulai landai lalu menguat
        # membuat permulaannya tidak bisa ditunjuk.
        bagian.append(_gradient_expr(lay))

    # Dua lapisan digabung dengan max, bukan dijumlah: penjumlahan bisa melewati
    # 255 di daerah yang kena keduanya dan menghasilkan tepi keras yang justru
    # mau dihindari.
    alpha = bagian[0] if len(bagian) == 1 else f"max({bagian[0]},{bagian[1]})"

    ff(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
         "-f", "lavfi", "-i", f"color=black:s={OUT_W}x{OUT_H}:d=1",
         "-frames:v", "1",
         "-vf", f"format=rgba,geq=r=0:g=0:b=0:a='{alpha}'",
         nama],
        deadline, cwd=workdir, cap=120,
    )
    return nama


def _render_one(source: Path, workdir: Path, seg: dict, crop: dict,
                src_w: int, src_h: int, deadline, lay=None,
                teks: bool = True) -> Path:
    out = Path("clips") / f"{seg['id']}.mp4"
    # Objek Layout, bukan nama: knob bayangan milik job sudah diterapkan di
    # run(), dan mengambil ulang dari nama akan membuangnya diam-diam.
    lay = lay or layout.ambil("penuh")
    # Tiap klip boleh fallback sendiri: sumber dengan cutaway atau pergantian
    # kamera sering hanya menampilkan satu orang pada sebagian segmen.
    if lay.duo and not crop.get("duo"):
        log.warning("render %s: pasangan duo tidak tersedia — memakai penuh", seg["id"])
        lay = layout.ambil("penuh")
    g = layout.geometri(lay, crop, src_w, src_h)
    mask = _mask(workdir, lay, g, deadline) if layout.butuh_lapisan(lay) else None
    # Nama file polos, tanpa path. Inilah gunanya cwd=workdir: filter subtitles
    # dan movie mem-parse argumennya sendiri, dan path Windows absolut
    # (backslash, titik dua drive, spasi di nama user) harus di-escape berlapis.
    # Dengan nama relatif, tidak ada yang perlu di-escape.
    vf = layout.filtergraph(lay, g, f"{seg['id']}.ass" if teks else None, mask)
    kompleks = None
    if lay.duo:
        a, b = layout.geometri_duo(lay, crop, src_w, src_h)
        cap = f",subtitles={seg['id']}.ass" if teks else ""
        kompleks = (
            # Satu timeline video hidup dibelah menjadi dua. setpts dilakukan
            # sebelum split supaya kedua panel selalu memakai frame dan waktu
            # yang sama; crop-nya tetap, isi kedua panel tidak pernah dibekukan.
            f"[0:v]setpts=PTS-STARTPTS,split=2[va][vb];"
            f"[va]crop={a['cw']}:{a['ch']}:{a['cx']}:{a['cy']},"
            f"scale={OUT_W}:{OUT_H // 2},setsar=1[top];"
            f"[vb]crop={b['cw']}:{b['ch']}:{b['cx']}:{b['cy']},"
            f"scale={OUT_W}:{OUT_H // 2},setsar=1[bottom];"
            f"[top][bottom]vstack=inputs=2{cap}[outv]"
        )
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
            # Layout mentahan tidak punya filter sama sekali, dan `-vf ""`
            # ditolak ffmpeg — jadi flagnya harus hilang, bukan dikosongkan.
            *(["-filter_complex", kompleks, "-map", "[outv]", "-map", "0:a?"]
              if kompleks else (["-vf", vf] if vf else [])),
            # Mentahan dikodekan lebih bagus: berkas ini akan diedit lalu
            # dikodekan ULANG, dan crf 23 di sini berarti dua generasi kompresi
            # bertumpuk pada hasil akhirnya.
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18" if lay.apa_adanya else "23",
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

    lay = layout.terapkan_knob(
        layout.ambil(ctx.get("layout") or settings.CLIP_LAYOUT), ctx.get("gaya"))
    teks = layout.pakai_caption(lay, ctx.get("gaya"))
    log.info("render memakai layout '%s'%s", lay.nama, "" if teks else " tanpa caption")

    rendered = {}
    for seg in ctx["segments_final"]:
        crop = ctx["crops"][seg["id"]]
        # Retry 1x (PRD Bagian 6) = 2 percobaan.
        path = retry(attempts=2, backoff=2.0)(_render_one)(
            source, workdir, seg, crop, src_w, src_h, deadline, lay, teks
        )
        size_mb = path.stat().st_size / 1e6
        if size_mb < 0.05:
            raise RuntimeError(f"{seg['id']}.mp4 kosong ({size_mb:.2f} MB) — render gagal diam-diam")
        log.info("render %s: %.1f MB, %.1fs", seg["id"], size_mb, seg["end"] - seg["start"])
        rendered[seg["id"]] = path

    return {"rendered": rendered}
