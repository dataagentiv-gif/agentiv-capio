"""Session transactions. Every mutation locks the session, including render approval."""
import copy
import uuid
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select

from db.models import AgentSession, Job, Status, session_scope

ACTIVE = {"queued", "preparing", "thinking", "cancelling"}


def public(row):
    d = row.data
    return {"id": str(row.id), "url": row.url, "brief": row.brief,
            "source_title": d.get("source_title", ""), "target_clips": row.target_clips, "model": row.model,
            "status": row.status, "operation_id": row.operation_id, "error": row.error,
            "version": d.get("version", 0), "messages": d.get("messages", []),
            "candidates": d.get("candidates", []), "renders": d.get("renders", []),
            "source_ready": d.get("source_ready", False), "metrics": d.get("metrics", {}),
            "progress": d.get("progress", ""), "overview": d.get("overview", {}),
            "editorial": d.get("editorial", {}), "source_duration": d.get("source_duration"),
            "created_at": row.created_at.isoformat() if row.created_at else None}


def get(ident, internal=False):
    with session_scope() as db:
        row = db.get(AgentSession, uuid.UUID(str(ident)))
        if row is None:
            raise HTTPException(404, "Sesi tidak ditemukan")
        result = public(row)
        if internal:
            result["data"] = copy.deepcopy(row.data)
        return result


def list_all():
    with session_scope() as db:
        return [{"id": str(r.id), "brief": (r.data.get("source_title") or r.brief or ("Video unggahan" if r.url.startswith("unggah:") else r.url))[:140], "status": r.status}
                for r in db.scalars(select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(100))]


@contextmanager
def locked(ident):
    with session_scope() as db:
        row = db.scalar(select(AgentSession).where(AgentSession.id == uuid.UUID(str(ident))).with_for_update())
        if row is None:
            raise HTTPException(404, "Sesi tidak ditemukan")
        row.data = copy.deepcopy(row.data)
        yield db, row
        from sqlalchemy.orm.attributes import flag_modified
        if row in db:
            flag_modified(row, "data")


def ensure_idle(db, row):
    if row.status in ACTIVE:
        raise HTTPException(409, "Sesi masih bekerja. Tunggu atau batalkan dahulu.")
    ids = [uuid.UUID(r["job_id"]) for r in row.data.get("renders", [])]
    if ids and db.scalar(select(Job.id).where(Job.id.in_(ids), Job.status.in_([Status.QUEUED, *Status.BERJALAN]))):
        raise HTTPException(409, "Render sesi masih berjalan.")


def create(url, brief, target, request_id, model):
    from sqlalchemy.exc import IntegrityError
    def existing():
        with session_scope() as db:
            r = db.scalar(select(AgentSession).where(AgentSession.create_request_id == request_id))
            return public(r) if r else None
    old = existing()
    if old:
        return old, False
    try:
        with session_scope() as db:
            row = AgentSession(url=url, brief=brief, target_clips=0, model=model,
                operation_id=request_id, create_request_id=request_id, data={
                    "version": 0, "history": [], "candidates": [], "renders": [],
                    "requests": [request_id], "messages": [{"role": "user", "text": brief, "id": request_id}] if brief else [],
                    "needs_overview": not bool(brief), "editorial": {}, "overview": {},
                    "pending": brief, "metrics": {"editor_seconds": 0}})
            db.add(row)
            db.flush()
            return public(row), True
    except IntegrityError:
        old = existing()
        if old:
            return old, False
        raise


def fail(ident, operation, message, status="failed"):
    with locked(ident) as (_, row):
        if row.operation_id == operation and row.status in ACTIVE:
            row.status, row.error = status, message
            row.worker_id = None


def recover(worker_id):
    with session_scope() as db:
        rows = db.scalars(select(AgentSession).where(
            AgentSession.worker_id == worker_id, AgentSession.status.in_(["preparing", "thinking", "cancelling"])).with_for_update()).all()
        for row in rows:
            row.status = "failed"
            row.error = "Worker berhenti. Coba ulang; hasil yang sudah tersimpan tetap tersedia."
            row.worker_id = None
        return len(rows)
