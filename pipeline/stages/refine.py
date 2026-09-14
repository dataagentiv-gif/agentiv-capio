"""Stage 4: geser batas segmen ke jeda alami.

Menggantikan Silero VAD + PySceneDetect di PRD dengan dua filter ffmpeg. Silero
menarik torch + torchaudio (~2.4GB wheel Windows) hanya untuk mencari batas
hening, dan PySceneDetect men-decode seluruh file satu jam padahal yang
dibutuhkan cuma jendela +/-1.5 detik di sekitar tiap batas.

Input  : ctx[segments_raw], ctx[audio], ctx[source], ctx[meta]
Output : segments_final.json -> tambah field id, start, end (detik, sudah snap)
"""
import json
import re
from pathlib import Path

from config.settings import settings
# Di-alias: tiap stage mengekspor run(ctx) sendiri, dan nama itu akan
# menimpa helper ini di namespace modul.
from utils.ffmpeg_helpers import run as ff
from utils.ffmpeg_helpers import silences
from utils.logging import get

log = get(__name__)

_PTS = re.compile(r"pts_time:([\d.]+)")

SCENE_THRESHOLD = 0.35
SCENE_WINDOW = 1.5  # detik yang dipindai di kiri-kanan tiap batas
LEAD_IN = 0.08      # mundurkan start sedikit supaya fonem pertama tidak terpotong
TAIL = 0.15         # majukan end sedikit supaya kata terakhir tidak terasa dipotong


def _scene_cuts(source: Path, t: float, deadline) -> list[float]:
    """Potongan visual di sekitar t saja, bukan di seluruh video."""
    t0 = max(0.0, t - SCENE_WINDOW)
    proc = ff(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-v", "info",
            "-ss", f"{t0:.3f}", "-i", str(source),
            "-t", f"{2 * SCENE_WINDOW:.3f}",
            "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',metadata=print",
            "-an", "-f", "null", "-",
        ],
        deadline,
        cap=120,
    )
    # +t0 karena input seek me-rebase pts filtergraph ke nol.
    cuts = [t0 + float(m) for m in _PTS.findall(proc.stderr)]
    # Frame pertama setelah seek tidak punya pendahulu di filtergraph sehingga
    # scene score-nya selalu 1.0. Itu bukan potongan sungguhan.
    return [c for c in cuts if c - t0 > 0.1]


# Bobot jarak saat menilai kandidat hening. Kandidat dinilai
# `durasi_hening - JARAK_PENALTI * jarak`, jadi hening 1.5 detik yang berjarak
# 1 detik masih mengalahkan hening 0.3 detik yang berjarak 0.1 detik.
JARAK_PENALTI = 0.5


def _snap(t: float, sils, cuts, edge: str, drift: float) -> float:
    """Potongan visual menang atas jeda audio — pergantian shot adalah batas
    alami yang lebih kuat daripada sekadar jeda bicara.

    Di antara sesama jeda audio, yang dipilih adalah yang PALING PANJANG, bukan
    yang paling dekat. Hening 1.5 detik adalah penutup gagasan; hening 0.3 detik
    cuma tarikan napas. Memilih berdasarkan kedekatan membuat tarikan napas yang
    kebetulan lebih dekat mengalahkan batas yang sebenarnya.
    """
    near = [c for c in cuts if abs(c - t) <= drift]
    if near:
        return min(near, key=lambda c: abs(c - t))

    # start: mulai tepat setelah hening SELESAI. end: berhenti tepat saat hening MULAI.
    cand = [
        (e if edge == "start" else s, e - s)
        for s, e in sils
        if abs((e if edge == "start" else s) - t) <= drift
    ]
    if not cand:
        return t
    return max(cand, key=lambda c: c[1] - JARAK_PENALTI * abs(c[0] - t))[0]


def run(ctx: dict) -> dict:
    segments = ctx["segments_raw"]
    words = ctx["words"]
    workdir: Path = ctx["workdir"]
    deadline = ctx["deadline"]
    duration = float(ctx["meta"]["duration"])
    drift = settings.SNAP_MAX_DRIFT

    # Stage deterministik, tidak di-retry. Kalau deteksi gagal, jatuh ke
    # timestamp asli — batas yang tidak di-snap masih menghasilkan klip yang
    # layak, sedangkan batas yang di-snap ke hening palsu justru lebih buruk.
    try:
        sils = silences(ctx["audio"], duration, deadline,
                        settings.SILENCE_NOISE_DB, settings.SILENCE_MIN_DUR)
    except Exception as e:  # noqa: BLE001
        log.warning("silencedetect gagal (%s) — batas dipakai apa adanya", e)
        sils = []
    if not sils:
        # Penyebab paling sering: musik latar. Musik MENAIKKAN lantai
        # kebisingan, jadi tidak ada momen yang pernah turun di bawah ambang.
        # Naluri pertama orang adalah menurunkan ambangnya, dan itu justru
        # memperparah — terukur: audio bicara bermusik -24dB menghasilkan 0 jeda
        # pada ambang -30dB, tetap 0 di -35 dan -40, tapi 15 jeda begitu ambang
        # dinaikkan ke -20dB. Tanpa keterangan arah ini, setelan yang tersedia
        # justru menuntun ke arah yang salah.
        log.warning(
            "Tidak ada hening terdeteksi pada ambang %s dB — batas klip TIDAK "
            "digeser ke jeda alami, jadi potongannya lebih kasar. Kalau "
            "sumbernya bermusik latar, NAIKKAN SILENCE_NOISE_DB (misal ke -20), "
            "jangan diturunkan: musik menaikkan lantai kebisingan sehingga "
            "ambang yang lebih rendah makin mustahil tercapai.",
            settings.SILENCE_NOISE_DB,
        )

    final = []
    for n, s in enumerate(segments, start=1):
        raw_start = words[s["start_idx"]]["s"]
        raw_end = words[s["end_idx"]]["e"]
        try:
            cuts_a = _scene_cuts(ctx["source"], raw_start, deadline)
            cuts_b = _scene_cuts(ctx["source"], raw_end, deadline)
        except Exception as e:  # noqa: BLE001
            log.warning("scene detect gagal (%s) — pakai jeda audio saja", e)
            cuts_a = cuts_b = []

        start = max(0.0, _snap(raw_start, sils, cuts_a, "start", drift) - LEAD_IN)
        end = min(duration, _snap(raw_end, sils, cuts_b, "end", drift) + TAIL)

        # Snap tidak boleh melanggar kontrak durasi. Hening panjang di dekat
        # batas bisa memendekkan klip di bawah minimum tanpa penjaga ini.
        if not (settings.MIN_CLIP_SEC <= end - start <= settings.MAX_CLIP_SEC):
            log.warning(
                "snap c%d menghasilkan %.1fs, di luar rentang — kembali ke batas asli",
                n, end - start,
            )
            start, end = raw_start, raw_end

        final.append({"id": f"c{n}", **s, "start": round(start, 3), "end": round(end, 3)})
        log.info(
            "c%d: %.2f-%.2f (geser %+.2f/%+.2f), %.1fs",
            n, start, end, start - raw_start, end - raw_end, end - start,
        )

    (workdir / "segments_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"segments_final": final}
