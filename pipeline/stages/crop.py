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

ASSETS = Path(__file__).resolve().parents[2] / "assets"
MODEL_DEKAT = ASSETS / "blaze_face_short_range.tflite"
MODEL_JAUH = ASSETS / "blaze_face_full_range.tflite"
SAMPLES = 20        # frame yang dicicipi per segmen
DET_W, DET_H = 640, 360
MIN_HIT_RATIO = 0.3  # di bawah ini dianggap tidak ada wajah sama sekali
MIN_PAIR_AREA = 0.003  # abaikan wajah sangat kecil seperti foto/poster di latar
MIN_PAIR_AREA_RATIO = 0.25  # kedua pembicara harus punya skala yang masih sebanding
MIN_PAIR_GAP = 0.17  # cukup terpisah untuk dua medium-shot tanpa menolak sofa rapat
MIN_DUO_CROP_RATIO = 0.8  # jangan upscale crop sempit menjadi panel 1080px
MAX_PAIR_X_SHIFT = 0.10  # posisi kursi harus tetap, bukan kamera berganti-ganti
MAX_PAIR_Y_SHIFT = 0.12


@lru_cache(maxsize=2)
def _detector(jauh: bool = False):
    # Import ditunda: mediapipe memuat runtime tflite yang berat, dan proses API
    # tidak pernah menyentuh stage ini.
    import mediapipe as mp
    from mediapipe.tasks import python as mp_py
    from mediapipe.tasks.python import vision

    model = MODEL_JAUH if jauh else MODEL_DEKAT
    if not model.exists():
        raise RuntimeError(f"Model face detector tidak ada di {model}")
    # Tasks API, bukan mp.solutions: mp.solutions sudah dihapus dari mediapipe
    # versi sekarang (google-ai-edge/mediapipe#6192).
    opts = vision.FaceDetectorOptions(
        base_options=mp_py.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.5,
    )
    return vision.FaceDetector.create_from_options(opts), mp


def _sample(source: Path, start: float, dur: float, deadline, count: int = SAMPLES) -> list:
    """Ambil sejumlah frame RGB dari satu segmen.

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
            "-vf", f"fps={count / max(dur, 1.0):.4f},scale={DET_W}:{DET_H}",
            "-frames:v", str(count),
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


def _face_observations(frames: list, jauh: bool = False) -> list[list[dict]]:
    """Semua wajah per sampel dalam koordinat ternormalisasi."""
    if not frames:
        return []
    det, mp = _detector(jauh)
    hasil = []
    for frame in frames:
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
        baris = []
        for d in res.detections:
            b = d.bounding_box
            baris.append({
                "x": (b.origin_x + b.width / 2) / DET_W,
                "y": (b.origin_y + b.height / 2) / DET_H,
                "area": (b.width * b.height) / (DET_W * DET_H),
                "width": b.width / DET_W,
            })
        hasil.append(baris)
    return hasil


def _face_pair_from_observations(observations: list[list[dict]]) -> list[dict] | None:
    """Posisi statis dua orang yang duduk tetap, atau None bila tidak cocok."""
    if not observations:
        return None
    pasangan = []
    for faces in observations:
        penting = [f for f in faces if f["area"] >= MIN_PAIR_AREA]
        # V1 sengaja khusus dua orang. Memilih dua dari tiga membuat panel bisa
        # berganti orang tanpa ada cara yang jujur untuk menjelaskannya.
        if len(penting) >= 3:
            return None
        if len(penting) != 2:
            continue
        kiri, kanan = sorted(penting, key=lambda f: f["x"])
        if min(kiri["area"], kanan["area"]) / max(kiri["area"], kanan["area"]) \
                < MIN_PAIR_AREA_RATIO:
            continue
        pasangan.append((kiri, kanan))

    minimum = max((len(observations) * 9 + 9) // 10, len(observations) - 2)
    if len(pasangan) < minimum:
        return None

    hasil = []
    for sisi in (0, 1):
        xs = [p[sisi]["x"] for p in pasangan]
        ys = [p[sisi]["y"] for p in pasangan]
        fx, fy = statistics.median(xs), statistics.median(ys)
        if any(abs(x - fx) > MAX_PAIR_X_SHIFT for x in xs) or \
                any(abs(y - fy) > MAX_PAIR_Y_SHIFT for y in ys):
            return None
        hasil.append({"fx": fx, "fy": fy})
    return hasil


def _face_pair(frames: list) -> list[dict] | None:
    # Wide-shot podcast membuat setiap wajah kecil di dalam frame. Model dekat
    # yang tepat untuk crop satu pembicara sering mengembalikan nol di sini;
    # model full-range memang dilatih untuk komposisi seperti ini.
    return _face_pair_from_observations(_face_observations(frames, jauh=True))


def _center_from_observations(observations: list[list[dict]]) -> tuple[float, float] | None:
    """Median wajah utama dari hasil deteksi yang sudah tersedia."""
    utama = [max(faces, key=lambda f: f["area"]) for faces in observations if faces]
    if not utama:
        return None
    return statistics.median(f["x"] for f in utama), statistics.median(f["y"] for f in utama)


def _pair_fits_duo(pair: list[dict], src_w: int, src_h: int) -> bool:
    """Tolak split yang tidak bisa menghasilkan dua medium-shot yang layak."""
    if pair[1]["fx"] - pair[0]["fx"] < MIN_PAIR_GAP:
        return False
    tengah = (pair[0]["fx"] + pair[1]["fx"]) * src_w / 2
    crop_ideal = src_h * 0.78 * 9 / 8
    return min(tengah, src_w - tengah) >= crop_ideal * MIN_DUO_CROP_RATIO


def _tracked_shots(observations: list[list[dict]], duration: float, src_w: int,
                   src_h: int, template_id: str, words: list[dict],
                   start: float) -> list[dict]:
    """Titik cut crop relatif klip; wajah sesaat tidak boleh merebut fokus."""
    if not observations:
        return []
    from pipeline.templates import TEMPLATES

    panel_h = TEMPLATES[template_id]["visual"]["panel_height"]
    crop_w = min(src_w, src_h * 1080 / panel_h)
    tracks: list[list[tuple[int, dict]]] = []
    visible: list[list[tuple[int, dict]]] = []
    for i, faces in enumerate(observations):
        used = set()
        frame = []
        for face in sorted((f for f in faces if f["area"] >= MIN_PAIR_AREA),
                           key=lambda f: f["area"], reverse=True):
            candidates = []
            for ti, track in enumerate(tracks):
                if ti in used or i - track[-1][0] > 6:
                    continue
                last = track[-1][1]
                distance = abs(face["x"] - last["x"]) + abs(face["y"] - last["y"]) * 0.5
                if distance < 0.20:
                    candidates.append((distance, ti))
            ti = min(candidates)[1] if candidates else len(tracks)
            if ti == len(tracks):
                tracks.append([])
            tracks[ti].append((i, face))
            used.add(ti)
            frame.append((ti, face))
        visible.append(frame)
    if not tracks:
        return []

    # Pilih orang yang sudah terlihat di awal dan paling konsisten, bukan
    # median lintas dua orang yang bisa jatuh persis di ruang kosong.
    early = {ti for frame in visible[:3] for ti, _ in frame}
    pool = early or set(range(len(tracks)))
    primary = max(pool, key=lambda ti: (len(tracks[ti]),
                                       sum(face["area"] for _, face in tracks[ti])))
    primary_faces = [face for _, face in tracks[primary]]
    leftmost = min(f["x"] - f.get("width", 0.08) / 2 for f in primary_faces)
    rightmost = max(f["x"] + f.get("width", 0.08) / 2 for f in primary_faces)
    # Satu bingkai yang memuat seluruh gerak alami lebih baik daripada cut
    # bolak-balik hanya karena pembicara sedikit menggeser kepalanya.
    steady_center = ((leftmost + rightmost) / 2
                     if (rightmost - leftmost) * src_w <= crop_w
                     else statistics.median(f["x"] for f in primary_faces[:3]))
    pair_center = None
    pair_ids = set()
    if template_id == "blur_atas_bawah":
        stable = sorted(range(len(tracks)), key=lambda ti: len(tracks[ti]), reverse=True)[:2]
        if len(stable) == 2 and all(len(tracks[ti]) >= len(observations) * 0.6 for ti in stable):
            pair_faces = [f for ti in stable for _, f in tracks[ti]]
            left = min(f["x"] - f.get("width", 0.08) / 2 for f in pair_faces)
            right = max(f["x"] + f.get("width", 0.08) / 2 for f in pair_faces)
            if (right - left) * src_w <= crop_w:
                pair_center = (left + right) / 2
                pair_ids = set(stable)
    shots: list[dict] = []
    active = primary
    center = None
    missed = 0
    interval = duration / len(observations)

    def safe(face: dict, at: float) -> bool:
        left = max(0.0, min(src_w - crop_w, at * src_w - crop_w / 2))
        half = face.get("width", 0.08) * src_w / 2
        px = face["x"] * src_w
        return left + half <= px <= left + crop_w - half

    def pause_near(at: float) -> float:
        gaps = []
        for a, b in zip(words, words[1:]):
            gap = b["s"] - a["e"]
            mid = (a["e"] + b["s"]) / 2 - start
            if gap >= 0.16 and 0 < mid < duration and abs(mid - at) <= 1.0:
                gaps.append((abs(mid - at), mid))
        return min(gaps)[1] if gaps else at

    for i, frame in enumerate(visible):
        found = dict(frame)
        face = found.get(active)
        if face is None:
            missed += 1
            if missed < 2:
                continue
            alternatives = [(ti, f) for ti, f in frame
                            if any(j == i - 1 for j, _ in tracks[ti])]
            if not alternatives:
                continue
            active, face = max(alternatives, key=lambda pair: pair[1]["area"])
        else:
            missed = 0

        # Panel Blur dapat menampung dua pembicara tanpa mengubah layout.
        focus = face["x"]
        if center is None and active == primary:
            focus = steady_center
        pair_fits = False
        if pair_center is not None:
            focus = pair_center
            pair_fits = True
        elif template_id == "blur_atas_bawah" and len(frame) > 1:
            left = min(f["x"] - f.get("width", 0.08) / 2 for _, f in frame)
            right = max(f["x"] + f.get("width", 0.08) / 2 for _, f in frame)
            if (right - left) * src_w + crop_w * 0.12 <= crop_w:
                focus = (left + right) / 2
                pair_fits = True
        if center is not None:
            checked = [(ti, f) for ti, f in frame if ti in pair_ids] if pair_ids else frame
            keep = (all(safe(f, center) for _, f in checked) if pair_fits
                    else safe(face, center))
            if keep or abs(focus - center) * src_w < 8:
                continue

        at = 0.0 if not shots else max(0.0, (i - 0.5) * interval)
        if shots:
            at = pause_near(at)
            if at - shots[-1]["at"] < 2.0:
                continue
        center = focus
        shots.append({"at": round(at, 3), "center": round(center, 5)})
    return shots


def run(ctx: dict) -> dict:
    if "template_id" in ctx:
        return _template_crops(ctx)
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
        dur = seg["end"] - seg["start"]
        try:
            if lay.duo:
                frames = _sample(source, seg["start"], dur, deadline)
                observations = _face_observations(frames, jauh=True)
                pasangan = _face_pair_from_observations(observations)
                if pasangan and not _pair_fits_duo(pasangan, src_w, src_h):
                    pasangan = None
                frac = ((pasangan[0]["fx"], pasangan[0]["fy"])
                        if pasangan else _center_from_observations(observations))
            else:
                frames = _sample(source, seg["start"], dur, deadline)
                pasangan = None
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
            pasangan = None

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
        crops[seg["id"]] = {"x": x, "w": win_w, "fx": fx, "fy": fy,
                            "duo": pasangan}
        if lay.duo and not pasangan:
            log.warning("podcast 2 orang %s: komposisi tidak stabil — memakai penuh",
                        seg["id"])
        elif lay.duo:
            log.info("podcast 2 orang %s: posisi dikunci sepanjang klip", seg["id"])

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


def _template_crops(ctx: dict) -> dict:
    """Satu keputusan wajah dan sisi untuk seluruh durasi setiap klip."""
    src_w, src_h = int(ctx["meta"]["width"]), int(ctx["meta"]["height"])
    win_w = max(2, min(src_w, round(src_h * 9 / 16)) & ~1)
    result = {}
    custom = ctx.get("template_id") == "custom"
    options = ctx.get("adjustments", {})
    for seg in ctx["segments_final"]:
        face = None
        shots = []
        if ctx["template_id"] in ("full_screen", "blur_atas_bawah"):
            try:
                duration = seg["end"] - seg["start"]
                frames = _sample(ctx["source"], seg["start"], duration,
                                 ctx["deadline"], min(120, max(20, round(duration))))
                observations = _face_observations(frames, jauh=True)
                if sum(bool(f) for f in observations) < len(frames) * MIN_HIT_RATIO:
                    observations = _face_observations(frames)
                shots = _tracked_shots(observations, duration, src_w, src_h,
                                       ctx["template_id"], ctx.get("words", []), seg["start"])
                if shots:
                    face = shots[0]["center"], None
                log.info("crop %s: %d posisi, %d cut", seg["id"], len(shots), max(0, len(shots) - 1))
            except Exception as exc:  # noqa: BLE001 - center crop tetap valid
                log.warning("pelacakan wajah %s gagal: %s; memakai tengah", seg["id"], exc)
        elif ctx["template_id"] != "mentahan" and (not custom or options.get("focus_mode") == "face"):
            try:
                face = _face_center(_sample(ctx["source"], seg["start"],
                                            seg["end"] - seg["start"], ctx["deadline"]))
            except Exception as exc:  # noqa: BLE001 - center crop tetap valid
                log.warning("deteksi wajah %s gagal: %s; memakai tengah", seg["id"], exc)
        fx, fy = face if face else (None, None)
        px = fx if fx is not None else 0.5
        x = max(0, min(src_w - win_w, round(px * src_w - win_w / 2))) & ~1
        # Wajah di kanan => ruang lebih aman di kiri. Saat pusat/no-face,
        # pilih pembicara kiri secara deterministik untuk seluruh klip.
        side = "kanan" if fx is not None and fx > 0.55 else "kiri"
        result[seg["id"]] = {"x": x, "w": win_w, "fx": fx, "fy": fy,
                              "speaker_side": side}
        if shots:
            result[seg["id"]]["shots"] = shots
        if custom:
            result[seg["id"]]["custom_options"] = options
    return {"crops": result}
