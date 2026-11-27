"""Offline providers for the browser/RQ integration test; never used by production."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import env_store
from config.settings import settings
from sqlalchemy.engine import make_url

if make_url(settings.DATABASE_URL).database != "capio_ui_test":
    raise SystemExit("This test runtime requires the disposable capio_ui_test database")
env_store.reload = lambda: None
settings.MIN_CLIP_SEC, settings.MAX_CLIP_SEC = 2, 6
settings.GEMINI_API_KEYS = "offline-test-only"
settings.WORKER_MODE = "single"

from agentic import worker
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pipeline.stages import metadata

def transcribe(ctx):
    result = {"words": [{"i":i,"w":f"kata{i}","s":float(i),"e":i+.9} for i in range(12)],
              "sentences": [{"text":"kata0 kata1", "s":0, "e":11.9}]}
    for key, value in result.items():
        (ctx["workdir"]/f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
    return result

def answer(messages, info):
    prompt = next(p.content for m in messages for p in m.parts if getattr(p,"part_kind","")=="user-prompt")
    data = json.loads(prompt)
    returns = [p for m in messages for p in m.parts if isinstance(p,ToolReturnPart)]
    overview = not data.get("feedback")
    a = 6 if "alternatif" in data.get("feedback", "").lower() else 0
    if not returns:
        return ModelResponse(parts=[ToolCallPart("read_transcript",{"page_numbers":[0]})] if overview else [ToolCallPart("read_ranges",{"ranges":[{"start_idx":a,"end_idx":a+3}]})])
    output = {"message":"Sumber siap. Beri arahan lewat chat.","overview":{"summary":"Demonstrasi sumber", "topics":[{"start_idx":0,"end_idx":11,"title":"Produk", "summary":"Demonstrasi produk","opening_quote":"kata0 kata1 kata2","closing_quote":"kata9 kata10 kata11"}]}} if overview else {
        "message":"Silakan tinjau kandidat.","recommendations":[{"title":"Pelajaran untuk pemula","reason":"Sudut dari sumber","start_idx":a,"end_idx":a+3}],"editorial":{"understanding":"Tonjolkan kemudahan produk untuk pemula"},"candidates":[{"start_idx":a,"end_idx":a+3,"title":"Kemudahan produk", "reason":"Pesan sesuai brief", "concern":"Periksa konteks",
        "opening_quote":" ".join(f"kata{i}" for i in range(a,a+3)), "closing_quote":" ".join(f"kata{i}" for i in range(a+1,a+4))}]}
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,output)])

worker.transcribe.run = transcribe
worker.GeminiPool = lambda *args: FunctionModel(answer)
metadata.call_llm = lambda *args: {"clips": []}
from db.models import init
init()

if sys.argv[1] == "api":
    import uvicorn
    uvicorn.run("api.routes:app", host="127.0.0.1", port=18086, log_level="warning")
else:
    from worker.runner import main
    main()
