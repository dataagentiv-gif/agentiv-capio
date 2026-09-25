from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from db.models import GeminiUsage, session_scope
import uuid
from config.settings import settings

def record(job_id, stage, model, input_tokens=0, output_tokens=0, total_tokens=None, estimated=False, success=True):
    try:
        jid = uuid.UUID(str(job_id)) if job_id else None
    except Exception:
        jid = None
    total = total_tokens if total_tokens is not None else input_tokens + output_tokens
    with session_scope() as s:
        s.add(GeminiUsage(job_id=jid, stage=str(stage or "unknown"), model=str(model or "unknown"),
                          input_tokens=max(0, int(input_tokens or 0)), output_tokens=max(0, int(output_tokens or 0)),
                          total_tokens=max(0, int(total or 0)), estimated=bool(estimated), success=bool(success)))

def _since(period):
    return {"day": 1, "7d": 7, "30d": 30}.get(period)

def rows(period="all", job_id=None):
    with session_scope() as s:
        q = select(GeminiUsage).order_by(GeminiUsage.created_at.asc())
        days = _since(period)
        if days:
            q = q.where(GeminiUsage.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
        if job_id:
            try: job_id = uuid.UUID(str(job_id))
            except (ValueError, TypeError): return []
            q = q.where(GeminiUsage.job_id == job_id)
        return list(s.scalars(q).all())

def prices():
    return {"input_per_million": float(settings.GEMINI_INPUT_PRICE_PER_MILLION),
            "output_per_million": float(settings.GEMINI_OUTPUT_PRICE_PER_MILLION),
            "service_per_clip": float(settings.CLIP_SERVICE_PRICE), "currency": settings.USAGE_CURRENCY}
