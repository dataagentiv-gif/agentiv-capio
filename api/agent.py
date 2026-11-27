"""Agent endpoints; server owns conversation history and approval snapshots."""
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas import JobCreate
from db import agent_sessions as sessions, jobs
from db.models import Job, Status
from agentic import worker
from llm import rute
from utils.ffmpeg_helpers import rmtree_retry

router = APIRouter()


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    brief: str = Field(default="", max_length=12000)
    target_clips: int = Field(default=0, ge=0, le=20)
    request_id: uuid.UUID

    @field_validator("url")
    @classmethod
    def source(cls, value):
        return JobCreate._youtube_only(value)

    @field_validator("brief")
    @classmethod
    def nonempty(cls, value):
        return value.strip()


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    version: int = Field(ge=0)
    editor_seconds: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)


class Message(Mutation):
    text: str = Field(min_length=1, max_length=12000)


class Decision(Mutation):
    candidate_id: str = Field(min_length=1, max_length=100)
    decision: Literal["kept", "rejected", "pending"]


class Render(Mutation):
    candidate_ids: list[str] = Field(min_length=1, max_length=20)
    template_id: str
    adjustments: dict = Field(default_factory=dict)


def gate():
    from api.routes import _pastikan_boleh_memproses
    _pastikan_boleh_memproses()
    import keypool
    if not keypool.keys("gemini"):
        raise HTTPException(400, "Agent membutuhkan API key Gemini. Isi di Setting.")


def check_version(row, version):
    if row.data.get("version", 0) != version:
        raise HTTPException(409, "Shortlist berubah. Muat ulang sesi sebelum melanjutkan.")


def track(row, payload):
    row.data.setdefault("requests", []).append(str(payload.request_id))
    metrics = row.data.setdefault("metrics", {})
    metrics["editor_seconds"] = metrics.get("editor_seconds", 0) + payload.editor_seconds


def dispatch(ident, operation):
    try:
        worker.enqueue(ident, operation)
    except Exception:
        sessions.fail(ident, operation, "Antrean tidak tersedia. Coba ulang ketika worker/Redis siap.")
        raise HTTPException(503, "Antrean tidak tersedia; sesi tersimpan dan dapat dicoba ulang.")


@router.get("/agent")
def page(request: Request):
    from api.routes import templates
    return templates.TemplateResponse(request, "agent.html", {})


@router.get("/agent/{ident}/render")
def render_page(ident: uuid.UUID, request: Request, candidate_ids: list[str] | None = Query(default=None)):
    from api.routes import templates
    session = sessions.get(ident)
    selected = [c["id"] for c in session["candidates"] if c["decision"] == "kept"]
    selected = selected[:20] if candidate_ids is None else candidate_ids
    kept = {c["id"] for c in session["candidates"] if c["decision"] == "kept"}
    if not 1 <= len(selected) <= 20 or len(set(selected)) != len(selected) or any(i not in kept for i in selected):
        raise HTTPException(409, "Pilih 1–20 kandidat yang dipertahankan dari sesi ini.")
    return templates.TemplateResponse(request, "submit.html", {"default_clips": len(selected),
        "agent_session": {"id": str(ident), "version": session["version"], "candidate_ids": selected}})


@router.get("/api/agent/sessions")
def listing():
    return sessions.list_all()


@router.post("/api/agent/sessions", status_code=201)
def create(payload: AgentCreate):
    gate()
    result, fresh = sessions.create(payload.url, payload.brief, payload.target_clips,
                                    str(payload.request_id), rute.daftar()[0])
    if fresh:
        dispatch(result["id"], result["operation_id"])
    return result


@router.get("/api/agent/sessions/{ident}")
def read(ident: uuid.UUID):
    return sessions.get(ident)


@router.post("/api/agent/sessions/{ident}/messages", status_code=202)
def message(ident: uuid.UUID, payload: Message):
    gate()
    with sessions.locked(ident) as (db, row):
        if str(payload.request_id) in row.data.get("requests", []):
            return sessions.public(row)
        sessions.ensure_idle(db, row)
        check_version(row, payload.version)
        if not row.data.get("source_ready"):
            raise HTTPException(409, "Siapkan sumber sebelum mengirim arahan melalui chat.")
        if not payload.text.strip():
            raise HTTPException(422, "Pesan tidak boleh kosong.")
        track(row, payload)
        row.data["messages"].append({"role": "user", "text": payload.text.strip(), "id": str(payload.request_id)})
        row.data["pending"] = payload.text.strip()
        row.operation_id, row.status, row.error = str(payload.request_id), "queued", None
        row.data["progress"] = "Menunggu worker"
    dispatch(ident, str(payload.request_id))
    return sessions.get(ident)


@router.post("/api/agent/sessions/{ident}/decisions")
def decision(ident: uuid.UUID, payload: Decision):
    with sessions.locked(ident) as (db, row):
        if str(payload.request_id) in row.data.get("requests", []):
            return sessions.public(row)
        sessions.ensure_idle(db, row)
        check_version(row, payload.version)
        candidate = next((c for c in row.data["candidates"] if c["id"] == payload.candidate_id), None)
        if candidate is None:
            raise HTTPException(404, "Kandidat tidak ditemukan dalam sesi ini.")
        candidate["decision"] = payload.decision
        track(row, payload)
        row.data["version"] += 1
        row.data.setdefault("decisions", []).append({"candidate_id": payload.candidate_id,
            "decision": payload.decision, "version": row.data["version"]})
    return sessions.get(ident)


@router.post("/api/agent/sessions/{ident}/retry", status_code=202)
def retry(ident: uuid.UUID, payload: Mutation):
    gate()
    with sessions.locked(ident) as (db, row):
        if str(payload.request_id) in row.data.get("requests", []):
            return sessions.public(row)
        sessions.ensure_idle(db, row)
        check_version(row, payload.version)
        if row.status not in ("failed", "cancelled"):
            raise HTTPException(409, "Hanya operasi gagal/dibatalkan yang dapat diulang.")
        track(row, payload)
        row.operation_id, row.status, row.error = str(payload.request_id), "queued", None
        row.data["progress"] = "Menunggu worker"
    dispatch(ident, str(payload.request_id))
    return sessions.get(ident)


@router.post("/api/agent/sessions/{ident}/cancel")
def cancel(ident: uuid.UUID):
    with sessions.locked(ident) as (_, row):
        if row.status == "queued":
            row.status = "cancelled"
        elif row.status in ("preparing", "thinking"):
            row.status = "cancelling"
    return sessions.get(ident)


@router.get("/api/agent/sessions/{ident}/source")
def source(ident: uuid.UUID):
    session = sessions.get(ident)
    path = worker.directory(ident) / "preview.mp4"
    if not session["source_ready"] or not path.is_file():
        raise HTTPException(404, "Preview belum siap.")
    # Starlette FileResponse handles byte ranges (including invalid ranges) for seeking.
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, no-cache"})


@router.post("/api/agent/sessions/{ident}/render", status_code=201)
def render(ident: uuid.UUID, payload: Render):
    gate()
    from pipeline.templates import resolve
    try:
        adjustments = resolve(payload.template_id, payload.adjustments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with sessions.locked(ident) as (db, row):
        existing = next((r for r in row.data.get("renders", []) if r["request_id"] == str(payload.request_id)), None)
        if existing:
            return {"job_id": existing["job_id"]}
        sessions.ensure_idle(db, row)
        check_version(row, payload.version)
        chosen = {c["id"]: c for c in row.data["candidates"] if c["decision"] == "kept"}
        if len(set(payload.candidate_ids)) != len(payload.candidate_ids) or any(i not in chosen for i in payload.candidate_ids):
            raise HTTPException(409, "Pilih kandidat yang dipertahankan dari sesi ini.")
        if not row.data.get("source_ready"):
            raise HTTPException(409, "Sumber belum siap.")
        from agentic.editor import WordRange, validate_candidate
        from utils.ffmpeg_helpers import Deadline
        context = worker.load_context(ident, Deadline(10))
        words = context["words"]
        segments = []
        for key in payload.candidate_ids:
            c = chosen[key]
            try:
                validate_candidate(WordRange(start_idx=c["start_idx"], end_idx=c["end_idx"]), words, context["meta"]["duration"])
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            segments.append({"start_idx": c["start_idx"], "end_idx": c["end_idx"],
                "hook": " ".join(w["w"] for w in words[c["start_idx"]:min(c["end_idx"] + 1, c["start_idx"] + 14)]),
                "hook_title": c["title"], "reason": c["reason"], "score": 0})
        snapshot = {"session_id": str(ident), "version": payload.version, "brief": row.data.get("editorial", {}).get("understanding") or row.brief,
                    "editorial": row.data.get("editorial", {}), "segments": segments, "candidate_ids": payload.candidate_ids}
        job = Job(url=row.url, target_clips=len(segments), layout=payload.template_id, gaya=adjustments,
                  status=Status.QUEUED, agent_snapshot=snapshot,
                  client_request_id=f"agent:{ident}:{payload.request_id}")
        db.add(job)
        db.flush()
        job_id = str(job.id)
        track(row, payload)
        row.data["renders"].append({"job_id": job_id, "version": payload.version, "request_id": str(payload.request_id)})
    from jobqueue.client import enqueue
    try:
        enqueue(job_id)
    except Exception:
        jobs.fail(job_id, "Antrean render tidak tersedia. Coba ulang dari halaman Proses.")
        raise HTTPException(503, f"Antrean gagal. Job {job_id} tersimpan di halaman Proses.")
    return {"job_id": job_id}


@router.delete("/api/agent/sessions/{ident}", status_code=204)
def delete(ident: uuid.UUID):
    with sessions.locked(ident) as (db, row):
        sessions.ensure_idle(db, row)
        # Hold the row lock while removing assets; no new render can claim the source.
        rmtree_retry(worker.directory(ident))
        db.delete(row)
