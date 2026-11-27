"""RQ entry point: prepare once, run one turn, release the worker for human review."""
import asyncio
import copy
import json
import time
import uuid

from config import env_store
from config.settings import settings
from db import agent_sessions as sessions
from llm.telemetry import stage
from pipeline.stages import download, transcribe
from utils.ffmpeg_helpers import Deadline, JobCancelled, ffmpeg
from agentic.editor import turn, merge_candidates
from agentic.gemini import GeminiPool


def directory(ident):
    return settings.DATA_DIR.resolve() / "agent" / str(uuid.UUID(str(ident)))


def load_context(ident, deadline):
    root = directory(ident)
    ctx = {"workdir": root, "source": root / "source.mp4", "audio": root / "audio.ogg", "deadline": deadline}
    for key, filename in (("meta", "meta.json"), ("words", "words.json"), ("sentences", "sentences.json")):
        ctx[key] = json.loads((root / filename).read_text(encoding="utf-8"))
    return ctx


def enqueue(ident, operation):
    from jobqueue.client import get_queue
    get_queue().enqueue("agentic.worker.run", str(ident), operation,
        job_timeout=settings.JOB_TIMEOUT_SEC + 900, result_ttl=86400, failure_ttl=604800)


def run(ident, operation):
    from worker.runner import WORKER_ID
    env_store.reload()
    with sessions.locked(ident) as (_, row):
        if row.operation_id != operation or row.status != "queued":
            return
        row.status, row.worker_id, row.error = "preparing", WORKER_ID, None
    started = time.monotonic()
    model = None
    editorial_started = None
    preparation_seconds = 0
    tool_calls = 0
    ctx = {}
    overview_only = False
    def metrics():
        now = time.monotonic()
        return {"model_requests": getattr(model, "attempts", 0), "tool_calls": tool_calls,
                "input_tokens": getattr(model, "input_tokens", 0),
                "output_tokens": getattr(model, "output_tokens", 0),
                "processing_seconds": round(now - started, 2),
                "preparation_seconds": preparation_seconds,
                "editorial_seconds": round(now - editorial_started, 2) if editorial_started is not None else 0}
    def cancelled():
        s = sessions.get(ident)
        return s["operation_id"] != operation or s["status"] == "cancelling"
    deadline = Deadline(settings.JOB_TIMEOUT_SEC, check_cancel=cancelled)
    def progress(text):
        deadline.check(text)
        with sessions.locked(ident) as (_, row):
            row.data["progress"] = text
    try:
        session = sessions.get(ident, internal=True)
        overview_only = bool(session["data"].get("needs_overview") and not session["data"].get("pending"))
        root = directory(ident)
        root.mkdir(parents=True, exist_ok=True)
        ctx = {"url": session["url"], "workdir": root, "deadline": deadline}
        prepared = root / "prepared.json"
        if not prepared.exists():
            with stage(ident, "agent_prepare"):
                if all((root / name).exists() for name in ("source.mp4", "audio.ogg", "meta.json")):
                    ctx.update(source=root / "source.mp4", audio=root / "audio.ogg",
                               meta=json.loads((root / "meta.json").read_text(encoding="utf-8")))
                else:
                    progress("Menyiapkan video sumber")
                    ctx.update(download.run(ctx))
                if not all((root / name).exists() for name in ("words.json", "sentences.json")):
                    progress("Mentranskripsikan sumber")
                    ctx.update(transcribe.run(ctx))
                progress("Menyiapkan preview")
                # Uploads may contain MOV/MKV despite the source.mp4 name. Always make a browser proxy.
                ffmpeg(["-i", str(root / "source.mp4"), "-vf", "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-movflags", "+faststart", str(root / "preview.mp4")], deadline, cap=settings.JOB_TIMEOUT_SEC)
                preparation_seconds = round(time.monotonic() - started, 2)
                prepared.write_text('{"ready":true}', encoding="utf-8")
        ctx = load_context(ident, deadline)
        with sessions.locked(ident) as (_, row):
            if row.status == "cancelling":
                raise JobCancelled()
            row.status = "thinking"
            row.data["source_ready"] = True
            row.data["source_duration"] = ctx["meta"]["duration"]
            row.data["source_title"] = ctx["meta"].get("title", session["url"])
            if row.data.get("needs_overview"):
                row.data.setdefault("overview", {}).setdefault("partial", True)
        progress("Membaca brief dan transkrip")
        editorial_started = time.monotonic()
        with stage(ident, "agent_editor"):
            model = GeminiPool(session["model"], deadline)
            reply, history, usage = asyncio.run(turn(session, ctx, model, progress))
            tool_calls = usage.tool_calls
        deadline.check("save shortlist")
        with sessions.locked(ident) as (_, row):
            if row.operation_id != operation or row.status == "cancelling":
                raise JobCancelled()
            previous = copy.deepcopy(row.data.get("candidates", []))
            row.data["candidates"] = merge_candidates(ident, row.data.get("candidates", []), reply.candidates, ctx["words"], reply.replace_ids)
            old = {c['id']:c for c in previous}
            current = {c['id']:c for c in row.data['candidates']}
            new = len(current.keys()-old.keys())
            updated = sum(c != old[ident] for ident,c in current.items() if ident in old)
            duplicates = sum(uuid.uuid5(uuid.UUID(str(ident)), f'{c.start_idx}:{c.end_idx}').hex[:16] in old for c in reply.candidates)
            summary = {'new':new,'updated':updated,'duplicates':duplicates,
                       'rejected':len(ctx.get('rejected_proposals', {})), 'recommendations':len(reply.recommendations), 'limit_reached':ctx.get('limit_reached'), 'alternatives':ctx.get('request_alternatives',False)}
            row.data['result_summary'] = summary
            recommendations=[]
            for r in reply.recommendations:
                item=r.model_dump();item.update(start=ctx['words'][r.start_idx]['s'],end=ctx['words'][r.end_idx]['e'])
                recommendations.append(item)
            row.data['recommendations'] = recommendations
            if not overview_only and (reply.candidates or reply.recommendations or summary['rejected']):
                if ctx.get('request_alternatives') and not new and not updated and not reply.recommendations:
                    reply.message='Belum ada sudut alternatif baru yang lolos pemeriksaan untuk fokus ini. Pilihan dan rekomendasi sebelumnya tetap tersedia.'
                elif not new and not updated and duplicates:
                    reply.message='Usulan yang lolos sudah ada di shortlist; belum ada alternatif baru yang valid.'
                reply.message=f"{new} kandidat baru ditambahkan; {updated} kandidat diperbarui. " + reply.message
            if reply.editorial is not None:
                row.data["editorial"] = reply.editorial.model_dump()
            elif ctx.get('active_focus'):
                row.data.setdefault('editorial', {})['focus'] = ctx['active_focus']
            if reply.overview is not None:
                overview = reply.overview.model_dump()
                overview.update(ctx["overview_coverage"])
                for topic in overview["topics"]:
                    topic.update(start=ctx["words"][topic["start_idx"]]["s"], end=ctx["words"][topic["end_idx"]]["e"])
                row.data["overview"] = overview
                row.data["needs_overview"] = False
            row.data["history"] = history
            row.data.setdefault("turn_history", []).append({"operation_id": operation, "history": history})
            row.data["version"] = row.data.get("version", 0) + 1
            row.data.setdefault("shortlists", []).append({"version": row.data["version"],
                "candidates": copy.deepcopy(row.data["candidates"]), "message": reply.message, "metrics": metrics(),
                "candidate_rejections": ctx.get("candidate_rejections", []), "result_summary":summary, "recommendations":recommendations})
            row.data["pending"] = ""
            row.data["messages"].append({"role": "assistant", "text": reply.message, "recommendations":recommendations, "result_summary":summary})
            row.data["progress"] = "Siap ditinjau"
            totals = row.data.setdefault("metrics", {})
            for key, value in (("turns", 1),):
                totals[key] = totals.get(key, 0) + value
            row.status, row.worker_id = "ready", None
    except JobCancelled:
        tool_calls = ctx.get("failed_tool_calls", 0)
        sessions.fail(ident, operation, "Dibatalkan. Kandidat sebelumnya tetap tersedia.", "cancelled")
    except Exception as exc:
        tool_calls = ctx.get("failed_tool_calls", 0)
        if ctx.get("failed_history"):
            with sessions.locked(ident) as (_, row):
                row.data.setdefault("turn_history", []).append({"operation_id": operation, "status": "failed", "history": ctx["failed_history"]})
        from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior, ModelHTTPError
        if isinstance(exc, UsageLimitExceeded):
            text = "Batas putaran tercapai. Kandidat sebelumnya tetap tersedia; beri arahan yang lebih spesifik atau coba ulang."
        elif isinstance(exc, UnexpectedModelBehavior):
            text = "Agent belum memenuhi pemeriksaan batas atau konteks kandidat. Sumber dan pilihan sebelumnya tetap tersedia; perjelas arahan atau coba ulang."
        elif isinstance(exc, ModelHTTPError):
            text = f"Gemini menolak permintaan (HTTP {exc.status_code}). Sumber tersimpan; coba ulang atau periksa konfigurasi model."
        elif isinstance(exc, TimeoutError):
            text = "Waktu putaran habis. Coba ulang; persiapan yang selesai tetap digunakan."
        else:
            # Provider exceptions may embed credentials/request bodies. Persist only a safe type.
            from llm import LLMError
            text = str(exc) if isinstance(exc, LLMError) else f"Operasi gagal ({type(exc).__name__}). Coba ulang atau periksa konfigurasi."
        if overview_only and isinstance(exc, (UsageLimitExceeded, UnexpectedModelBehavior, TimeoutError)):
            # A prepared source remains usable even when the optional overview cannot finish.
            with sessions.locked(ident) as (_, row):
                if row.operation_id == operation and row.status != "cancelling" and row.data.get("source_ready"):
                    row.status, row.worker_id, row.error = "ready", None, None
                    row.data["overview"] = {**row.data.get("overview", {}), "partial": True,
                        "warning": "Ringkasan awal belum selesai. Video dan transkrip siap; kamu bisa memberi arahan lewat chat.",
                        "failure_kind": type(exc).__name__}
                    row.data["needs_overview"] = False
                    row.data["progress"] = "Sumber siap; menunggu arahan"
                    row.data["pending"] = ""
                    row.data["version"] = row.data.get("version", 0) + 1
                    row.data["messages"].append({"role": "assistant", "text": row.data["overview"]["warning"]})
                elif row.operation_id == operation:
                    row.status, row.worker_id, row.error = "cancelled", None, "Dibatalkan. Sumber tetap tersedia."
        else:
            sessions.fail(ident, operation, text)
    finally:
        from fastapi import HTTPException
        try:
            with sessions.locked(ident) as (_, row):
                row.data.setdefault("operations", []).append({"operation_id": operation,
                    "status": row.status if row.operation_id == operation else "superseded", "metrics": metrics()})
                totals = row.data.setdefault("metrics", {})
                for key, value in metrics().items():
                    totals[key] = totals.get(key, 0) + value
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            # Deletion after the terminal status is valid; there is no session left to account to.


def render_context(snapshot, ctx):
    source = load_context(snapshot["session_id"], ctx["deadline"])
    for key in ("source", "audio", "meta", "words", "sentences"):
        ctx[key] = source[key]
    ctx["segments_raw"] = snapshot["segments"]
    ctx["editorial_brief"] = snapshot["brief"]
    ctx["approved_ranges"] = True
    return ctx
