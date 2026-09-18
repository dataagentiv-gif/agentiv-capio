"""REST API + penyaji web UI.

Route di sini tidak pernah menjalankan pipeline secara sinkron: terima request
-> tulis row awal -> push job_id ke queue -> balas. Sisanya urusan worker.
"""
import asyncio
import base64
import re
import secrets
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import bersih, checks, preview
from api.schemas import JobCreate, JobCreated, JobOut
import keypool
from config import env_store
from config.settings import settings
from db import jobs, models
from jobqueue.client import enqueue
import license as lisensi
from llm import rute
from pipeline import layout as layout_mod
import storage
import unggah
from utils.logging import get

log = get(__name__)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CLIP = re.compile(r"^c\d{1,3}$")
_JEDA_VERIFIKASI_LISENSI = 3600
WEB = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))


def _cap_aset() -> str:
    """Cap versi berkas statis, dari waktu ubah terbaru css dan js.

    Dipakai sebagai `?v=` pada tautan aset. Header Cache-Control saja tidak
    cukup: ia hanya berlaku untuk pengambilan BERIKUTNYA, sedangkan salinan
    yang sudah terlanjur tersimpan tidak pernah divalidasi ulang — browser
    memakai HTML baru bersama CSS lama, dan hasilnya tata letak berantakan
    tanpa satu pun pesan error. Mengubah URL-nya membuat salinan lama tidak
    mungkin terpakai, berapa pun umur cache-nya.
    """
    stat = [(WEB / "static" / n).stat().st_mtime for n in ("style.css", "app.js")]
    return format(int(max(stat)), "x")


templates.env.globals["v"] = _cap_aset()
# Fungsinya, bukan hasilnya: license key bisa diisi dari halaman Setting kapan
# saja, dan tautan yang dihitung sekali saat start akan membawa key lama
# seumur proses.
templates.env.globals["wa"] = lisensi.tautan_wa
# Nilai, bukan fungsi: VERSI tidak bisa diubah dari halaman Setting (tidak ada
# di FIELDS env_store.py) dan cuma berubah lewat build image baru — sama
# seperti `v`, aman dihitung sekali saat start.
templates.env.globals["versi"] = settings.VERSI


async def _segarkan_lisensi_berkala():
    """Ambil status rilis baru tanpa membuat polling UI menunggu jaringan."""
    while True:
        await asyncio.sleep(_JEDA_VERIFIKASI_LISENSI)
        if not (settings.LICENSE_KEY or "").strip():
            continue
        try:
            await asyncio.to_thread(lisensi.verifikasi)
        except Exception as e:  # noqa: BLE001 — putaran berikutnya harus tetap hidup
            log.warning("penyegaran lisensi berkala gagal: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WAJIB pertama, sama seperti worker/runner.py: compose memuat .env ke
    # environment container saat container DIBUAT, dan pydantic-settings
    # memprioritaskan environment di atas isi file .env. Tanpa ini, key yang
    # disimpan lewat halaman Setting lalu "hilang lagi" begitu container API
    # di-restart/recreate — file-nya tetap benar, tapi proses baru membaca
    # environment beku dari saat container lahir, bukan file yang sekarang.
    env_store.reload()
    models.init()
    # Verifikasi saat start, dan kegagalannya TIDAK PERNAH menjatuhkan aplikasi.
    # Tanpa key, halaman Setting harus tetap terbuka — di situlah key
    # dimasukkan. Menolak start berarti key tidak akan pernah bisa dimasukkan.
    if (settings.LICENSE_KEY or "").strip():
        try:
            lisensi.verifikasi()
        except Exception as e:  # noqa: BLE001
            log.warning("verifikasi lisensi saat start gagal: %s", e)
    else:
        log.info("LICENSE_KEY belum diisi — aplikasi jalan normal, submit job "
                 "diblokir sampai key dimasukkan di halaman Setting")
    # Peringatan ini ada karena kesalahan yang paling mungkin terjadi bukan
    # serangan canggih, melainkan seseorang mengubah API_HOST agar bisa dibuka
    # dari HP-nya, lalu lupa bahwa /settings memajang status seluruh kredensial.
    if settings.host_terbuka and not settings.AUTH_TOKEN:
        log.warning(
            "API_HOST=%s membuka server ke jaringan TANPA autentikasi. "
            "Halaman /settings bisa dipakai siapa pun untuk melihat status "
            "kredensial dan menimpanya. Isi AUTH_TOKEN di .env, atau kembalikan "
            "API_HOST ke 127.0.0.1.",
            settings.API_HOST,
        )
    log.info(
        "API siap di http://localhost:%d%s",
        settings.API_PORT,
        " (autentikasi aktif)" if settings.AUTH_TOKEN else "",
    )
    # Selalu dijalankan; nyala/mati dibaca dari setelan di tiap putarannya,
    # jadi mengubahnya di halaman Setting tidak butuh restart.
    sapuan = asyncio.create_task(bersih.loop())
    penyegaran_lisensi = asyncio.create_task(_segarkan_lisensi_berkala())
    yield
    sapuan.cancel()
    penyegaran_lisensi.cancel()


class StaticSegar(StaticFiles):
    """StaticFiles yang selalu memvalidasi ulang sebelum memakai cache.

    Starlette mengirim etag dan last-modified tapi tidak mengirim
    Cache-Control, dan tanpa itu browser memakai caching heuristik: file lama
    disajikan tanpa bertanya ke server. Akibatnya, setelah repo di-update,
    halaman tampil rusak — CSS lama tanpa aturan baru, JS lama tanpa fungsi
    baru — dan yang muncul bukan pesan error yang jelas melainkan tata letak
    berantakan plus ReferenceError.

    `no-cache` bukan berarti tidak boleh disimpan, melainkan wajib divalidasi
    dulu. Balasan 304 tetap terjadi, jadi tidak ada beban tambahan.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app = FastAPI(title="CAPIO", lifespan=lifespan)
app.mount("/static", StaticSegar(directory=str(WEB / "static")), name="static")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """HTTP Basic saat AUTH_TOKEN diisi. Kosong = tidak aktif.

    Dipakai Basic, bukan halaman login, karena browser sudah menanganinya
    sendiri — tidak perlu form, cookie, maupun sesi, dan `curl -u` tetap jalan.

    compare_digest, bukan `==`: perbandingan string biasa berhenti di karakter
    pertama yang beda, dan selisih waktunya bisa dipakai menebak token per
    karakter.
    """
    token = settings.AUTH_TOKEN
    if token:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                _, _, sandi = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(sandi, token)
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="CAPIO"'},
            )
    return await call_next(request)


# --- Web UI ---

@app.get("/", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(
        request, "submit.html", {"default_clips": settings.TARGET_CLIPS_DEFAULT}
    )


@app.get("/process", response_class=HTMLResponse)
def process_page(request: Request):
    return templates.TemplateResponse(request, "process.html", {})


@app.get("/results", response_class=HTMLResponse)
def results_page(request: Request):
    return templates.TemplateResponse(request, "results.html", {})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {})


# /history tetap hidup supaya tautan lama tidak mati.
@app.get("/history", response_class=HTMLResponse)
def history_page():
    return RedirectResponse("/results", status_code=308)


# --- Konfigurasi ---

@app.get("/api/settings")
def read_settings():
    return env_store.read_public()


@app.post("/api/settings")
def save_settings(payload: dict):
    changed = env_store.write(payload.get("values") or {})
    # Key baru diverifikasi SEKARANG, bukan menunggu restart. Hasilnya harus
    # tampil dalam hitungan detik — sesi setup remote ditutup dengan melihatnya.
    if "LICENSE_KEY" in changed:
        lisensi.verifikasi()
    if changed:
        # Hasil render lama tidak lagi mewakili setelan yang berlaku.
        preview.bersihkan_cache()
    log.info("settings diubah: %s", ", ".join(changed) or "(tidak ada)")
    return {"changed": changed, **env_store.read_public()}


@app.get("/api/keys/{pool}")
def status_key(pool: str):
    """Status tiap API key: mana yang berikutnya dipakai, hasil pemakaian terakhir."""
    if pool not in keypool.POOLS:
        raise HTTPException(404, f"Pool '{pool}' tidak dikenal")
    return keypool.status(pool)


@app.post("/api/keys/{pool}")
def tambah_key(pool: str, payload: dict):
    """Tambah satu key atau lebih ke pool."""
    if pool not in keypool.POOLS:
        raise HTTPException(404, f"Pool '{pool}' tidak dikenal")
    jumlah, pesan = keypool.tambah(pool, payload.get("key", ""))
    if not jumlah:
        raise HTTPException(400, pesan)
    log.info("key %s ditambah: %s", pool, pesan)
    return {"pesan": pesan, **keypool.status(pool)}


@app.delete("/api/keys/{pool}/{index}")
def hapus_key(pool: str, index: int):
    if pool not in keypool.POOLS:
        raise HTTPException(404, f"Pool '{pool}' tidak dikenal")
    ok, pesan = keypool.hapus(pool, index)
    if not ok:
        raise HTTPException(404, pesan)
    log.info("key %s dihapus: %s", pool, pesan)
    return {"pesan": pesan, **keypool.status(pool)}


@app.post("/api/lisensi/verifikasi")
def verifikasi_lisensi():
    """Tanya server lisensi sekarang juga, lalu kembalikan keadaan terbaru.

    Dipakai tombol Verifikasi ulang, dan dipanggil sendiri setiap kali
    LICENSE_KEY baru disimpan — tanpa itu, sesi setup remote harus ditutup
    tanpa kepastian, dan itu tidak bisa diterima.
    """
    hasil = lisensi.verifikasi()
    return {**hasil, "status": lisensi.status(), "wa": lisensi.tautan_wa()}


@app.post("/api/settings/test/{provider}")
def test_provider(provider: str):
    return {"provider": provider, **checks.run(provider)}


@app.get("/api/layouts")
def daftar_layout():
    """Pilihan tampilan untuk halaman Submit."""
    return {
        "default": layout_mod.ambil(settings.CLIP_LAYOUT).nama,
        "layouts": [
            # `teks` dipakai UI untuk mematikan seluruh knob caption saat
            # layoutnya memang tidak memakai caption — bukan menampilkan kontrol
            # yang diputar tanpa akibat apa pun.
            # `redup` dipakai UI untuk memunculkan knob bayangan hanya di
            # layout yang memang punya bayangan, beserta nilai awalnya.
            {"nama": l.nama, "judul": l.judul, "keterangan": l.keterangan,
             "font_saran": l.font_saran, "teks": l.teks, "redup": l.redup,
             "speaker_side": l.nama == "samping", "duo": l.duo}
            for l in layout_mod.LAYOUTS.values()
        ],
    }


@app.get("/api/preview.png")
def preview_tampilan(layout: str | None = None, font: str | None = None,
                     ukuran: int | None = None, warna: str | None = None,
                     kata: int | None = None, upper: bool | None = None,
                     caption: bool | None = None,
                     redup_luas: int | None = None, redup_gelap: int | None = None,
                     active_word_style: str | None = None,
                     active_word_background_color: str | None = None,
                     active_word_text_color: str | None = None,
                     active_word_border_radius: int | None = None,
                     active_word_padding_x: int | None = None,
                     active_word_padding_y: int | None = None,
                     speaker_side: str | None = None):
    """Contoh caption dengan setelan tampilan yang sedang dipilih.

    Parameternya opsional supaya halaman Setting bisa menampilkan akibat sebuah
    knob SEBELUM disimpan — kalau harus menyimpan dulu, mencoba lima warna
    berarti lima kali menulis .env.
    """
    knob = {k: v for k, v in (
        ("font", font), ("ukuran", ukuran), ("aktif", warna),
        ("kata", kata), ("upper", upper), ("caption", caption),
        ("redup_luas", redup_luas), ("redup_gelap", redup_gelap),
        ("active_word_style", active_word_style),
        ("active_word_background_color", active_word_background_color),
        ("active_word_text_color", active_word_text_color),
        ("active_word_border_radius", active_word_border_radius),
        ("active_word_padding_x", active_word_padding_x),
        ("active_word_padding_y", active_word_padding_y),
        ("speaker_side", speaker_side),
    ) if v is not None}
    try:
        isi, tipe = preview.render(layout, knob)
    except Exception as e:  # noqa: BLE001 — preview gagal jangan menjatuhkan halaman
        log.warning("preview gagal: %s", e)
        raise HTTPException(500, f"Preview gagal dibuat: {e}") from e
    return Response(
        content=isi,
        media_type=tipe,
        # Preview berubah tiap knob diputar; menyimpannya di cache browser
        # justru membuat halaman menampilkan setelan yang sudah tidak berlaku.
        # Yang di-cache adalah hasil render di sisi server, bukan responsnya.
        headers={"Cache-Control": "no-store"},
    )


def _kurang_konfigurasi() -> str | None:
    """"gemini" kalau key-nya masih kosong, None kalau lengkap.

    Transkrip dan LLM sama-sama lewat pool "gemini" sekarang, jadi satu
    pemeriksaan cukup untuk keduanya.
    """
    return None if keypool.keys("gemini") else "gemini"


@app.get("/api/status")
def config_status():
    """Ringkasan singkat untuk strip status di halaman Submit."""
    gemini_ok = bool(keypool.keys("gemini"))
    return {
        # Transkrip dan LLM ditampilkan terpisah karena secara konsep memang
        # dua tahap pipeline berbeda (Stage 2 vs Stage 3/8) — kebetulan saja
        # keduanya sekarang memakai pool key yang sama.
        "asr": {"provider": "gemini", "ok": gemini_ok},
        # Model yang sedang dipakai ikut dilaporkan. Tanpa itu, turunnya tier
        # karena kuota habis benar-benar tidak terlihat dari mana pun: klipnya
        # tetap keluar, cuma dari model yang lebih rendah — persis kelas
        # perubahan yang paling sulit disadari.
        "llm": {
            "provider": "gemini",
            "ok": gemini_ok,
            "model": rute.status("gemini", rute.daftar(), len(keypool.keys("gemini"))),
        },
        # Penyimpanan lokal tidak pernah "belum dikonfigurasi" — foldernya
        # dibuat sendiri. Tetap dilaporkan supaya strip status di halaman
        # Submit menampilkan ketiga bagian pipeline secara utuh.
        "storage": {"provider": "local", "ok": True},
        "lisensi": lisensi.status(),
        "wa": lisensi.tautan_wa(),
        "ready": gemini_ok and lisensi.boleh_submit()[0],
        # Jumlah job yang belum selesai. Dipakai titik penanda di dock, supaya
        # dari halaman mana pun terlihat bahwa masih ada yang berjalan — orang
        # submit lalu pindah halaman, dan sebelumnya tidak ada satu pun tanda.
        #
        # QUEUED IKUT DIHITUNG, berbeda dengan Status.BERJALAN yang sengaja
        # mengecualikannya. Di sana pertanyaannya "apakah ada worker yang
        # memegangnya sekarang"; di sini pertanyaannya "apakah masih ada yang
        # saya tunggu" — dan job yang mengantre jelas termasuk.
        "jalan": sum(
            1 for j in jobs.list_all()
            if j["status"] in models.Status.BERJALAN
            or j["status"] == models.Status.QUEUED
        ),
        "default_clips": settings.TARGET_CLIPS_DEFAULT,
        "min_sec": settings.MIN_CLIP_SEC,
        "max_sec": settings.MAX_CLIP_SEC,
    }


@app.get("/clips/{job_id}/{clip_id}/poster.jpg")
def poster_clip(job_id: str, clip_id: str):
    """Satu frame klip sebagai thumbnail.

    Dibuat SEKALI lalu disimpan di sebelah mp4-nya. Halaman Hasil memuat
    puluhan klip sekaligus; membangkitkan ulang tiap kali halaman dibuka berarti
    puluhan proses ffmpeg untuk gambar yang isinya tidak pernah berubah.

    Diambil pada detik 1.0, bukan detik 0: frame pertama sebuah potongan sering
    masih gelap atau di tengah pergantian shot, dan caption terbakarnya belum
    muncul — padahal caption itu justru yang paling ingin dinilai sekilas.
    """
    # Batas kepercayaan yang SAMA dengan play_clip, sengaja memakai penjaga yang
    # sama persis: dua nilai ini menyusun path di disk, dan penjaga versi kedua
    # yang lambat laun berbeda adalah cara paling sunyi untuk membocorkannya.
    if not _UUID.match(job_id) or not _CLIP.match(clip_id):
        raise HTTPException(404, "Klip tidak ditemukan")

    poster = storage.poster_path(job_id, clip_id)
    if not poster.is_file():
        sumber = storage.clip_path(job_id, clip_id)
        if not sumber.is_file():
            raise HTTPException(404, "Klip tidak ada di storage")
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error",
                 "-ss", "1.0", "-i", str(sumber), "-frames:v", "1",
                 "-vf", "scale=240:-2", "-q:v", "5", str(poster)],
                check=True, timeout=60,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("poster %s/%s gagal dibuat: %s", job_id, clip_id, e)
            raise HTTPException(404, "Poster gagal dibuat") from e

    return FileResponse(
        poster,
        media_type="image/jpeg",
        # Isinya tidak akan pernah berubah untuk id yang sama — id klip tidak
        # pernah dipakai ulang di dalam satu job.
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@app.get("/clips/{job_id}/{clip_id}")
def play_clip(job_id: str, clip_id: str, range: str | None = Header(default=None)):
    """Putar klip.

    Melayani file dari CLIPS_DIR dengan dukungan header Range, sehingga video
    bisa digeser posisinya, bukan cuma diputar dari awal.
    """
    # Batas kepercayaan: dua nilai ini menyusun path file di disk, jadi
    # bentuknya dikunci ketat supaya tidak bisa dipakai keluar dari CLIPS_DIR.
    if not _UUID.match(job_id) or not _CLIP.match(clip_id):
        raise HTTPException(404, "Klip tidak ditemukan")

    try:
        potongan, panjang, content_range = storage.open_clip(job_id, clip_id, range)
    except Exception as e:  # noqa: BLE001
        log.warning("gagal ambil klip %s/%s: %s", job_id, clip_id, e)
        raise HTTPException(404, "Klip tidak ada di storage") from e

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(panjang)}
    if content_range:
        headers["Content-Range"] = content_range
    return StreamingResponse(
        potongan,
        # 206 saat browser meminta sebagian: tanpa itu pemutar video tidak bisa
        # menggeser posisi, cuma bisa memutar dari awal.
        status_code=206 if range else 200,
        media_type="video/mp4",
        headers=headers,
    )


# --- REST API ---

def _pastikan_boleh_memproses() -> None:
    """Gerbang bersama submit baru dan proses ulang."""
    boleh, alasan = lisensi.boleh_submit()
    if not boleh:
        raise HTTPException(403, alasan)

    kurang = _kurang_konfigurasi()
    if kurang:
        raise HTTPException(
            400,
            f"API key untuk {kurang} belum diisi. Buka halaman Setting dulu — "
            "tanpa itu job akan gagal setelah videonya terlanjur diunduh.",
        )


@app.post("/jobs", response_model=JobCreated, status_code=201)
def create_job(payload: JobCreate):
    # Ditolak SEKARANG, bukan dibiarkan gagal di tengah pipeline. Tanpa key,
    # job tetap mengunduh videonya lebih dulu — beberapa menit sampai satu jam —
    # baru berhenti di stage transkrip. Halaman Submit sudah mematikan
    # tombolnya, tapi itu penjaga di browser saja: permintaan langsung ke API
    # tetap bisa membuat job yang sejak awal pasti gagal.
    # Gerbang lisensi ada DI SINI, bukan cuma di tombol halaman Submit: tombol
    # yang di-disable bisa dilewati dengan satu perintah curl. Dibaca dari token
    # tersimpan, tanpa memanggil server — submit tidak boleh pernah menunggu
    # jaringan.
    _pastikan_boleh_memproses()

    # Layout kosong berarti ikut default di Setting. Diselesaikan di sini, bukan
    # dibiarkan kosong sampai render: nilai yang tersimpan di baris job harus
    # tetap menjelaskan bentuk klipnya walau defaultnya berubah setelah itu.
    job = jobs.create(
        payload.url, payload.target_clips,
        payload.layout or layout_mod.ambil(settings.CLIP_LAYOUT).nama,
        payload.gaya,
    )
    try:
        enqueue(job["id"])
    except Exception as e:  # noqa: BLE001
        # Row sudah tertulis tapi tidak akan pernah diambil worker. Ditandai
        # gagal sekarang juga, supaya tidak menggantung di `queued` selamanya.
        jobs.fail(job["id"], f"Gagal push ke queue: {e}")
        raise HTTPException(503, f"Queue tidak bisa dihubungi: {e}") from e
    return JobCreated(job_id=job["id"], status=job["status"])


@app.post("/jobs/{job_id}/retry", response_model=JobCreated)
def retry_job(job_id: str):
    """Ulangi job gagal dengan input, gaya, dan source yang sama."""
    if not _UUID.match(job_id):
        raise HTTPException(404, "Job tidak ditemukan")
    lama = jobs.get(job_id)
    if lama is None:
        raise HTTPException(404, "Job tidak ditemukan")
    if lama["status"] != "failed":
        raise HTTPException(409, "Hanya job gagal yang dapat diproses ulang")

    _pastikan_boleh_memproses()
    job = jobs.retry(job_id)
    if job is None:
        # Status berubah setelah pemeriksaan di atas: biasanya tombol diklik
        # dua kali atau poller sudah melihat job kembali berjalan.
        raise HTTPException(409, "Job ini sudah diproses ulang")
    try:
        enqueue(job["id"])
    except Exception as e:  # noqa: BLE001
        jobs.fail(job["id"], f"Gagal push proses ulang ke queue: {e}")
        raise HTTPException(503, f"Queue tidak bisa dihubungi: {e}") from e
    return JobCreated(job_id=job["id"], status=job["status"])


@app.post("/api/unggah", status_code=201)
async def unggah_berkas(berkas: UploadFile):
    """Terima satu berkas video, kembalikan penandanya untuk dipakai submit.

    Dipisah dari POST /jobs, bukan digabung jadi satu form multipart. Unggahan
    berkas berukuran giga memakan waktu menit-menitan, dan menggabungkannya
    berarti seluruh parameter job ikut tersandera selama itu — sementara
    halaman Submit ingin menampilkan kemajuan unggahan lebih dulu, baru
    mengirim job saat berkasnya sudah aman di server.

    Ditulis MENGALIR per potongan, tidak dibaca sekaligus: satu berkas 2 GB
    yang dibaca utuh ke memori akan menjatuhkan proses API di mesin dengan RAM
    pas-pasan — dan itu justru mesin yang dipakai orang menjalankan ini.
    """
    nama = Path(berkas.filename or "video").name
    if Path(nama).suffix.lower() not in unggah.EKSTENSI:
        raise HTTPException(
            400,
            f"Format {Path(nama).suffix or 'ini'} tidak didukung. Pakai video "
            "biasa seperti MP4, MOV, MKV, atau WEBM.",
        )

    ident, tujuan = unggah.baru()
    besar = 0
    try:
        with tujuan.open("wb") as keluar:
            while potong := await berkas.read(4 * 1024 * 1024):
                besar += len(potong)
                keluar.write(potong)
    except Exception as e:  # noqa: BLE001
        # Berkas separuh jalan tidak boleh ditinggal: ia tidak akan pernah jadi
        # job, dan ukurannya justru paling besar saat gagal di tengah.
        unggah.bersihkan(ident)
        log.warning("unggahan %s gagal: %s", nama, e)
        raise HTTPException(500, f"Berkas gagal disimpan: {e}") from e

    if besar == 0:
        unggah.bersihkan(ident)
        raise HTTPException(400, "Berkasnya kosong.")

    unggah.catat_nama(ident, nama)
    log.info("unggahan diterima: %s (%.1f MB)", nama, besar / 1e6)
    return {"sumber": f"{unggah.AWALAN}{ident}", "nama": nama, "bytes": besar}


@app.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    """Hapus job beserta seluruh berkasnya.

    Ikut membuang workdir-nya. Workdir job yang gagal sengaja ditinggal untuk
    diperiksa, dan isinya video sumber mentah — justru itu yang paling cepat
    memenuhi disk kalau tidak pernah dibersihkan.

    Job antre/berjalan tidak boleh dihapus. Menghapus row saja tidak membatalkan
    eksekusi RQ: worker tetap sibuk tanpa terlihat di UI dan job lain tampak
    menunggu selamanya. Job yang worker-nya mati akan otomatis menjadi gagal
    ketika worker menyala lagi, lalu aman dihapus atau diproses ulang.
    """
    if not _UUID.match(job_id):
        raise HTTPException(404, "Job tidak ditemukan")
    hasil = bersih.hapus_job(job_id)
    if hasil == "missing":
        raise HTTPException(404, "Job tidak ditemukan")
    if hasil == "active":
        raise HTTPException(
            409,
            "Job masih antre atau berjalan. Tunggu sampai selesai atau gagal sebelum menghapusnya.",
        )
    log.info("job %s dihapus beserta berkasnya", job_id)
    return Response(status_code=204)


@app.delete("/jobs/{job_id}/clips/{clip_id}", status_code=204)
def delete_clip(job_id: str, clip_id: str):
    """Hapus satu klip: berkasnya dan entrinya di daftar klip job."""
    if not _UUID.match(job_id) or not _CLIP.match(clip_id):
        raise HTTPException(404, "Klip tidak ditemukan")
    if not jobs.remove_clip(job_id, clip_id):
        raise HTTPException(404, "Klip tidak ditemukan")
    storage.delete_clip(job_id, clip_id)
    log.info("klip %s/%s dihapus", job_id, clip_id)
    return Response(status_code=204)


@app.get("/jobs", response_model=list[JobOut])
def list_jobs():
    return jobs.list_all()


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job tidak ditemukan")
    return job
