"""Stage 6: tentukan jendela crop 9:16 dari posisi wajah.

Input  : ctx[source], ctx[segments_final], ctx[meta]
Output : crop map -> {"c1": {"x": 712, "w": 608}}
"""
import statistics
from functools import lru_cache
from pathlib import Path

from utils.ffmpeg_helpers import run
from utils.logging import get

log = get(__name__)

MODEL = Path(__file__).resolve().parents[2] / "assets" / "blaze_face_short_range.tflite"
SAMPLES = 20        # frame yang dicicipi per segmen
DET_W, DET_H = 640, 360
MIN_HIT_RATIO = 0.3  # di bawah ini dianggap tidak ada wajah sama sekali


@lru_cache(maxsize=1)
def _detector():
    # Import ditunda: mediapipe memuat runtime tflite yang berat, dan proses API
    # tidak pernah menyentuh stage ini.
    import mediapipe as mp
    from mediapipe.tasks import python as mp_py
    from mediapipe.tasks.python import vision

    if not MODEL.exists():
        raise RuntimeError(f"Model face detector tidak ada di {MODEL}")
    # Tasks API, bukan mp.solutions: mp.solutions sudah dihapus dari mediapipe
    # versi sekarang (google-ai-edge/mediapipe#6192).
    opts = vision.FaceDetectorOptions(
        base_options=mp_py.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.5,
    )
    return vision.FaceDetector.create_from_options(opts), mp


def _sample(source: Path, start: float, dur: float, deadline) -> list:
    """Ambil SAMPLES frame RGB dari satu segmen.

    Lewat pipe rawvideo ffmpeg, bukan cv2.VideoCapture: ini satu kali decode
    berurutan, bukan 20 kali seek acak. Output yt-dlp sering VFR dan seek
    CAP_PROP_POS_MSEC di source VFR adalah sumber klasik bug "kadang dapat frame
    yang salah, kadang tidak dapat apa-apa". Bonus: rgb24 persis format yang
    diminta MediaPipe, sementara OpenCV memberi BGR.
    """
    import numpy as np

    proc = run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-v", "error",
            "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{dur:.3f}",
            "-vf", f"fps={SAMPLES / max(dur, 1.0):.4f},scale={DET_W}:{DET_H}",
            "-frames:v", str(SAMPLES),
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ],
        deadline,
        cap=180,
        binary=True,
    )
    n = len(proc.stdout) // (DET_W * DET_H * 3)
    if n == 0:
        return []
    usable = n * DET_W * DET_H * 3
    return list(
        np.frombuffer(proc.stdout[:usable], dtype=np.uint8).reshape(n, DET_H, DET_W, 3)
    )


def _face_center(frames: list) -> float | None:
    """Posisi horizontal wajah, 0.0-1.0. None kalau terlalu sedikit terdeteksi."""
    if not frames:
        return None
    det, mp = _detector()
    xs = []
    for frame in frames:
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
        if res.detections:
            # Wajah terbesar = subjek utama; wajah kecil di latar diabaikan.
            box = max(res.detections, key=lambda d: d.bounding_box.width).bounding_box
            xs.append((box.origin_x + box.width / 2) / DET_W)
    if len(xs) < len(frames) * MIN_HIT_RATIO:
        return None
    # Median, bukan rata-rata: satu frame yang salah deteksi (poster di dinding,
    # penonton lewat) tidak boleh menyeret crop seluruh klip.
    return statistics.median(xs)


def run(ctx: dict) -> dict:
    source: Path = ctx["source"]
    src_w, src_h = int(ctx["meta"]["width"]), int(ctx["meta"]["height"])
    deadline = ctx["deadline"]

    # Lebar jendela 9:16 setinggi frame penuh, dibulatkan genap (libx264 butuh
    # dimensi genap untuk yuv420p).
    win_w = min(src_w, round(src_h * 9 / 16)) & ~1
    center_x = ((src_w - win_w) // 2) & ~1
    # ponytail: source yang lebih sempit dari 9:16 (mis. 1:1) akan ter-stretch
    # vertikal saat di-scale ke 1080x1920. Perbaikannya adalah mode `fit` dengan
    # blur background, yang oleh PRD sengaja ditunda ke versi berikutnya.
    if src_w * 16 < src_h * 9:
        log.warning("source lebih sempit dari 9:16 (%dx%d) — hasil akan ter-stretch", src_w, src_h)

    crops = {}
    for seg in ctx["segments_final"]:
        try:
            frames = _sample(source, seg["start"], seg["end"] - seg["start"], deadline)
            frac = _face_center(frames)
        except Exception as e:  # noqa: BLE001 — fallback center crop, jangan gagalkan job
            log.warning("deteksi wajah %s gagal (%s) — pakai center crop", seg["id"], e)
            frac = None

        if frac is None:
            x = center_x
            log.info("crop %s: center (tidak ada wajah)", seg["id"])
        else:
            x = int(frac * src_w - win_w / 2)
            x = max(0, min(src_w - win_w, x)) & ~1
            log.info("crop %s: x=%d (wajah di %.0f%% lebar)", seg["id"], x, frac * 100)

        crops[seg["id"]] = {"x": x, "w": win_w}

    return {"crops": crops}
