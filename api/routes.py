"""REST API + penyaji web UI.

Route di sini tidak pernah menjalankan pipeline secara sinkron: terima request
-> tulis row awal -> push job_id ke queue -> balas. Sisanya urusan worker.
"""
import base64
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import checks, preview
from api.schemas import JobCreate, JobCreated, JobOut
import keypool
from config import env_store
from config.settings import settings
from db import jobs, models
from jobqueue.client import enqueue
import storage
from utils.ffmpeg_helpers import rmtree_retry
from utils.logging import get

log = get(__name__)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CLIP = re.compile(r"^c\d{1,3}$")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.init()
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
    yield


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


@app.post("/api/settings/test/{provider}")
def test_provider(provider: str):
    return {"provider": provider, **checks.run(provider)}


@app.get("/api/preview.png")
def preview_tampilan(layout: str | None = None, font: str | None = None,
                     ukuran: int | None = None, warna: str | None = None,
                     kata: int | None = None, upper: bool | None = None):
    """Satu frame contoh dengan setelan tampilan yang sedang dipilih.

    Parameternya opsional supaya halaman Setting bisa menampilkan akibat sebuah
    knob SEBELUM disimpan — kalau harus menyimpan dulu, mencoba lima warna
    berarti lima kali menulis .env.
    """
    knob = {k: v for k, v in (
        ("font", font), ("ukuran", ukuran), ("aktif", warna),
        ("kata", kata), ("upper", upper),
    ) if v is not None}
    try:
        png = preview.render(layout, knob)
    except Exception as e:  # noqa: BLE001 — preview gagal jangan menjatuhkan halaman
        log.warning("preview gagal: %s", e)
        raise HTTPException(500, f"Preview gagal dibuat: {e}") from e
    return Response(
        content=png,
        media_type="image/png",
        # Preview berubah tiap knob diputar; menyimpannya di cache justru
        # membuat halaman menampilkan setelan yang sudah tidak berlaku.
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/status")
def config_status():
    """Ringkasan singkat untuk strip status di halaman Submit."""
    # Nama provider = nama pool, jadi tidak ada daftar terpisah yang bisa basi
    # saat provider baru ditambahkan.
    asr_ok = bool(keypool.keys(settings.ASR_PROVIDER))
    llm_ok = bool(keypool.keys(settings.LLM_PROVIDER))
    return {
        "asr": {"provider": settings.ASR_PROVIDER, "ok": asr_ok},
        "llm": {"provider": settings.LLM_PROVIDER, "ok": llm_ok},
        # Penyimpanan lokal tidak pernah "belum dikonfigurasi" — foldernya
        # dibuat sendiri. Tetap dilaporkan supaya strip status di halaman
        # Submit menampilkan ketiga bagian pipeline secara utuh.
        "storage": {"provider": "local", "ok": True},
        "ready": asr_ok and llm_ok,
        "default_clips": settings.TARGET_CLIPS_DEFAULT,
        "min_sec": settings.MIN_CLIP_SEC,
        "max_sec": settings.MAX_CLIP_SEC,
    }


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

@app.post("/jobs", response_model=JobCreated, status_code=201)
def create_job(payload: JobCreate):
    job = jobs.create(payload.url, payload.target_clips)
    try:
        enqueue(job["id"])
    except Exception as e:  # noqa: BLE001
        # Row sudah tertulis tapi tidak akan pernah diambil worker. Ditandai
        # gagal sekarang juga, supaya tidak menggantung di `queued` selamanya.
        jobs.fail(job["id"], f"Gagal push ke queue: {e}")
        raise HTTPException(503, f"Queue tidak bisa dihubungi: {e}") from e
    return JobCreated(job_id=job["id"], status=job["status"])


@app.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    """Hapus job beserta seluruh berkasnya.

    Ikut membuang workdir-nya. Workdir job yang gagal sengaja ditinggal untuk
    diperiksa, dan isinya video sumber mentah — justru itu yang paling cepat
    memenuhi disk kalau tidak pernah dibersihkan.

    Job yang sedang berjalan pun boleh dihapus. Itu disengaja: job yang
    tersangkut karena worker-nya mati tidak punya cara lain untuk dihilangkan.
    Worker yang masih menulis ke row yang sudah hilang akan berhenti sendiri
    tanpa membuat keributan.
    """
    if not _UUID.match(job_id):
        raise HTTPException(404, "Job tidak ditemukan")
    if not jobs.delete(job_id):
        raise HTTPException(404, "Job tidak ditemukan")
    storage.delete_job(job_id)
    rmtree_retry(settings.WORK_DIR / job_id[:8])
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
