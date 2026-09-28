from datetime import datetime, timedelta, timezone
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from db.models import GeminiUsage, session_scope
import uuid

# Tarif Standard paid tier per 1 juta token, USD, diperiksa 2026-09-28.
# Sumber: https://ai.google.dev/gemini-api/docs/pricing
# Ini nilai pembanding, bukan tagihan akun BYOK (free tier/cache bisa berbeda).
PAID_RATES = {
    "gemini-3.5-transcribe": ("2.00", "12.00"),
    "gemini-3.5-flash": ("1.50", "9.00"),
    "gemini-3.5-flash-lite": ("0.30", "2.50"),
    "gemini-3.1-flash-lite": ("0.25", "1.50"),
    "gemini-2.5-flash-lite": ("0.10", "0.40"),
    "gemini-3.7-flash": ("0.75", "3.75"),  # tarif sampai 2026-12-31
}
ALIAS_ASSUMPTIONS = {"gemini-flash-lite-latest": "gemini-3.5-flash-lite"}
PRICE_DATE = "2026-09-28"
PRICE_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"

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
    return {"currency": "USD", "as_of": PRICE_DATE, "source": PRICE_SOURCE,
            "tier": "standard_paid", "models": {
                model: {"input_per_million": float(inp), "output_per_million": float(out)}
                for model, (inp, out) in PAID_RATES.items()
            }, "alias_assumptions": ALIAS_ASSUMPTIONS}


def model_breakdown(records):
    """Jumlahkan per model; token lama tanpa rincian tidak ditebak biayanya."""
    groups = defaultdict(lambda: {"requests": 0, "failed_requests": 0,
                                  "input_tokens": 0, "output_tokens": 0,
                                  "total_tokens": 0, "unpriced_tokens": 0,
                                  "estimated_tokens": False, "cost": Decimal(0)})
    for row in records:
        model = row.model or "unknown"
        item = groups[model]
        inp = max(0, int(row.input_tokens or 0))
        out = max(0, int(row.output_tokens or 0))
        total = max(int(row.total_tokens or 0), inp + out)
        item["requests"] += 1
        item["failed_requests"] += not row.success
        item["input_tokens"] += inp
        item["output_tokens"] += out
        item["total_tokens"] += total
        item["estimated_tokens"] |= bool(row.estimated)
        priced_model = ALIAS_ASSUMPTIONS.get(model, model)
        rate = PAID_RATES.get(priced_model)
        if rate:
            item["cost"] += (Decimal(inp) * Decimal(rate[0]) +
                             Decimal(out) * Decimal(rate[1])) / 1_000_000
            item["unpriced_tokens"] += total - inp - out
        else:
            item["unpriced_tokens"] += total
    models = []
    for model, item in groups.items():
        priced_model = ALIAS_ASSUMPTIONS.get(model, model)
        models.append({"model": model, **{k: v for k, v in item.items() if k != "cost"},
                       "equivalent_cost_usd": round(float(item["cost"]), 6),
                       "price_status": ("alias_assumption" if model in ALIAS_ASSUMPTIONS
                                        else "listed" if priced_model in PAID_RATES else "unavailable"),
                       "priced_as": priced_model if priced_model in PAID_RATES else None})
    models.sort(key=lambda row: (-row["total_tokens"], row["model"]))
    return {"models": models, "requests": sum(row["requests"] for row in models),
            "total_tokens": sum(row["total_tokens"] for row in models),
            "input_tokens": sum(row["input_tokens"] for row in models),
            "output_tokens": sum(row["output_tokens"] for row in models),
            "unpriced_tokens": sum(row["unpriced_tokens"] for row in models),
            "estimated_tokens": any(row["estimated_tokens"] for row in models),
            "equivalent_cost_usd": round(sum(row["equivalent_cost_usd"] for row in models), 6)}
