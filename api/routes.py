"""REST API + penyaji web UI.

Route di sini tidak pernah menjalankan pipeline secara sinkron: terima request
-> tulis row awal -> push job_id ke queue -> balas. Sisanya urusan worker.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.schemas import JobCreate, JobCreated, JobOut
from config.settings import settings
from db import jobs, models
from jobqueue.client import enqueue
from utils.logging import get

log = get(__name__)
WEB = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.init()
    log.info("API siap di http://localhost:%d", settings.API_PORT)
    yield


app = FastAPI(title="Video Clipping Engine", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


# --- Web UI ---

@app.get("/", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(
        request, "submit.html", {"default_clips": settings.TARGET_CLIPS_DEFAULT}
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    return templates.TemplateResponse(request, "history.html", {})


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
