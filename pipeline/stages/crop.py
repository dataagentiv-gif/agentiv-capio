"""Stage 6: tentukan jendela crop 9:16 dari posisi wajah.

Input  : ctx[source], ctx[segments_final], ctx[meta]
Output : crop map -> {"c1": {"x": 712, "w": 608}}
"""
import statistics
from functools import lru_cache
from pathlib import Path

# Di-alias: tiap stage mengekspor run(ctx) sendiri, dan nama itu akan
# menimpa helper ini di namespace modul.
from utils.ffmpeg_helpers import run as ff
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

    proc = ff(
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


def _face_center(frames: list) -> tuple[float, float] | None:
    """Posisi wajah (x, y) sebagai pecahan 0.0-1.0 dari lebar dan tinggi frame.
    None kalau terlalu sedikit terdeteksi.

    Y ikut dikembalikan walau layout `penuh` tidak memakainya sama sekali:
    jendela 9:16 pada sumber mendatar memakai TINGGI PENUH, jadi tidak pernah
    ada keputusan vertikal di sana. Begitu video ditaruh dalam kotak yang lebih
    pendek dari frame, keputusan itu muncul — dan menebak "ambil tengah" akan
    memotong dagu atau menyisakan ruang menganga di atas kepala, karena orang di
    podcast biasanya duduk di sepertiga atas frame.
    """
    if not frames:
        return None
    det, mp = _detector()
    xs, ys = [], []
    for frame in frames:
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
        if res.detections:
            # Wajah terbesar = subjek utama; wajah kecil di latar diabaikan.
            box = max(res.detections, key=lambda d: d.bounding_box.width).bounding_box
            xs.append((box.origin_x + box.width / 2) / DET_W)
            ys.append((box.origin_y + box.height / 2) / DET_H)
    if len(xs) < len(frames) * MIN_HIT_RATIO:
        return None
    # Median, bukan rata-rata: satu frame yang salah deteksi (poster di dinding,
    # penonton lewat) tidak boleh menyeret crop seluruh klip.
    return statistics.median(xs), statistics.median(ys)


def run(ctx: dict) -> dict:
    from config.settings import settings
    from pipeline import layout

    source: Path = ctx["source"]
    src_w, src_h = int(ctx["meta"]["width"]), int(ctx["meta"]["height"])
    deadline = ctx["deadline"]

    # Layout yang tidak memotong frame tidak punya keputusan untuk diambil di
    # sini. Deteksi wajah tetap berjalan puluhan detik per klip kalau dibiarkan,
    # dan hasilnya dibuang seluruhnya.
    lay = layout.ambil(ctx.get("layout") or settings.CLIP_LAYOUT)
    if lay.apa_adanya:
        log.info("layout '%s' memakai frame apa adanya — deteksi wajah dilewati",
                 lay.nama)
        return {"crops": {s["id"]: {"x": 0, "w": src_w, "fx": None, "fy": None}
                          for s in ctx["segments_final"]}}

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
    berwajah = 0
    for seg in ctx["segments_final"]:
        try:
            frames = _sample(source, seg["start"], seg["end"] - seg["start"], deadline)
            frac = _face_center(frames)
        except Exception as e:  # noqa: BLE001 — fallback center crop, jangan gagalkan job
            # Dua kegagalan yang sangat berbeda lewat jalur ini. Satu klip yang
            # wajahnya tidak terbaca itu wajar, dan center crop memang jawaban
            # yang benar. Tapi detector yang TIDAK BISA DIBUAT sama sekali
            # adalah salah pasang, dan sifatnya permanen: seluruh klip di
            # seluruh job jadi center crop sementara pipeline tetap melapor
            # sukses. Persis itu yang terjadi di sini karena libegl1 tidak ada
            # di image — pelacakan wajah mati total, dan satu-satunya tanda
            # adalah baris WARNING yang terlihat wajar.
            if isinstance(e, (OSError, ImportError)):
                log.error(
                    "PELACAKAN WAJAH MATI (%s). Semua klip akan center crop. "
                    "Ini salah pasang, bukan video tanpa wajah — periksa "
                    "dependency sistem MediaPipe di image.", e,
                )
            else:
                log.warning("deteksi wajah %s gagal (%s) — pakai center crop", seg["id"], e)
            frac = None

        if frac is None:
            fx = fy = None
            x = center_x
            log.info("crop %s: center (tidak ada wajah)", seg["id"])
        else:
            berwajah += 1
            fx, fy = frac
            x = int(fx * src_w - win_w / 2)
            x = max(0, min(src_w - win_w, x)) & ~1
            log.info("crop %s: x=%d (wajah di %.0f%% lebar, %.0f%% tinggi)",
                     seg["id"], x, fx * 100, fy * 100)

        # x/w adalah jendela 9:16 siap pakai untuk layout `penuh`. fx/fy adalah
        # posisi wajah mentah, dipakai layout lain yang menentukan geometrinya
        # sendiri — mereka butuh tahu di mana orangnya, bukan jendela yang sudah
        # terlanjur diputuskan di sini.
        crops[seg["id"]] = {"x": x, "w": win_w, "fx": fx, "fy": fy}

    # Tidak ada satu pun wajah di SELURUH klip berarti sumbernya kemungkinan
    # bukan talking-head — screencast, gameplay, atau animasi. Center crop tetap
    # menghasilkan video yang sah, dan justru itu masalahnya: tidak ada yang
    # gagal, tapi hasilnya bisa jauh dari layak.
    #
    # Terukur pada satu tutorial Excel 16:9: jendela 9:16 hanya menyisakan 34%
    # lebar layar, dan teks di kiri-kanan terpotong di tengah kata. Klipnya
    # terlihat baik-baik saja di daftar hasil sampai benar-benar ditonton.
    if crops and berwajah == 0:
        log.warning(
            "TIDAK ADA WAJAH di seluruh %d klip — sumbernya kemungkinan bukan "
            "talking-head. Semua klip dibingkai center, dan pada layar yang "
            "penuh konten (screencast, gameplay) itu memotong %.0f%% lebar. "
            "Periksa hasilnya sebelum diposting.",
            len(crops), (1 - win_w / src_w) * 100,
        )

    return {"crops": crops}
