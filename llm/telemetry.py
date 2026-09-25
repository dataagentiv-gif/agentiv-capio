from contextvars import ContextVar
from contextlib import contextmanager
from db import usage

_ctx = ContextVar("gemini_usage_context", default=(None, "unknown"))

@contextmanager
def stage(job_id, name):
    token = _ctx.set((job_id, name))
    try:
        yield
    finally:
        _ctx.reset(token)

def record(model, input_tokens, output_tokens, total_tokens, estimated=False, success=True):
    job_id, name = _ctx.get()
    if job_id is not None:
        usage.record(job_id, name, model, input_tokens, output_tokens, total_tokens, estimated, success)
