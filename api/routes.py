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

from api import checks
from api.schemas import JobCreate, JobCreated, JobOut
from config import env_store
from config.settings import settings
from db import jobs, models
from jobqueue.client import enqueue
from storage.client import REQUIRED as storage_required
from storage.client import get_clip
from utils.logging import get

log = get(__name__)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CLIP = re.compile(r"^c\d{1,3}$")
WEB = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))


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


app = FastAPI(title="Video Clipping Engine", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


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
                headers={"WWW-Authenticate": 'Basic realm="Video Clipping Engine"'},
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


@app.post("/api/settings/test/{provider}")
def test_provider(provider: str):
    return {"provider": provider, **checks.run(provider)}


@app.get("/api/status")
def config_status():
    """Ringkasan singkat untuk strip status di halaman Submit."""
    r2_kurang = [k for k in storage_required if not getattr(settings, k, "")]
    asr_ok = bool(
        settings.GROQ_API_KEY if settings.ASR_PROVIDER == "groq"
        else settings.ELEVENLABS_API_KEY
    )
    llm_ok = bool(
        settings.OPENROUTER_API_KEY if settings.LLM_PROVIDER == "openrouter"
        else settings.gemini_keys
    )
    return {
        "asr": {"provider": settings.ASR_PROVIDER, "ok": asr_ok},
        "llm": {"provider": settings.LLM_PROVIDER, "ok": llm_ok},
        "storage": {"provider": "r2", "ok": not r2_kurang},
        "ready": asr_ok and llm_ok and not r2_kurang,
        "default_clips": settings.TARGET_CLIPS_DEFAULT,
        "min_sec": settings.MIN_CLIP_SEC,
        "max_sec": settings.MAX_CLIP_SEC,
    }


@app.get("/clips/{job_id}/{clip_id}")
def play_clip(job_id: str, clip_id: str, range: str | None = Header(default=None)):
    """Putar klip lewat server ini, bukan lewat URL publik r2.dev.

    Banyak ISP Indonesia memblokir r2.dev di level DNS, jadi link R2 langsung
    tidak kebuka tanpa VPN — sementara menyalakan VPN membuat Groq menolak
    request dengan 403. Route ini memutus lingkaran itu: file diambil dari R2
    lewat endpoint S3 yang tidak diblokir, lalu disalurkan dari localhost.
    """
    # Batas kepercayaan: dua nilai ini masuk ke key objek R2, jadi bentuknya
    # dikunci ketat supaya tidak bisa dipakai menjangkau objek lain.
    if not _UUID.match(job_id) or not _CLIP.match(clip_id):
        raise HTTPException(404, "Klip tidak ditemukan")

    try:
        obj = get_clip(job_id, clip_id, range)
    except Exception as e:  # noqa: BLE001
        log.warning("gagal ambil klip %s/%s: %s", job_id, clip_id, e)
        raise HTTPException(404, "Klip tidak ada di storage") from e

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(obj["ContentLength"])}
    if "ContentRange" in obj:
        headers["Content-Range"] = obj["ContentRange"]
    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=256 * 1024),
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


@app.get("/jobs", response_model=list[JobOut])
def list_jobs():
    return jobs.list_all()


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job tidak ditemukan")
    return job
