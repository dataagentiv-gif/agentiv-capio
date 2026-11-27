"""Agent contracts. No external requests; Postgres tests use a disposable schema.

Set CAPIO_AGENT_TEST_DB to a test Postgres URL to run the storage/render checks.
"""
import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent, ModelMessagesTypeAdapter
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart, TextPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from agentic import editor, worker, gemini, overview
from config.settings import settings
from utils.ffmpeg_helpers import Deadline, JobCancelled, ffmpeg, probe


def words():
    return [{"i": i, "w": f"kata{i}", "s": float(i), "e": i + .9} for i in range(12)]


def candidate(a=0, b=3):
    return editor.Candidate(start_idx=a, end_idx=b, title="Pesan brand", reason="Sesuai brief", concern="Periksa konteks", opening_quote=" ".join(f"kata{i}" for i in range(a,a+3)), closing_quote=" ".join(f"kata{i}" for i in range(b-2,b+1)))


@pytest.fixture(autouse=True)
def small_clips(monkeypatch):
    monkeypatch.setattr(settings, "MIN_CLIP_SEC", 2)
    monkeypatch.setattr(settings, "MAX_CLIP_SEC", 6)
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")


def test_candidates_are_source_anchored_and_kept_immutable():
    raw=candidate().model_dump();raw.pop("closing_quote")
    with pytest.raises(ValueError):editor.Candidate(**raw)
    ident = str(uuid.uuid4())
    previous = editor.merge_candidates(ident, [], [candidate()], words())
    previous[0]["decision"] = "kept"
    updated = editor.merge_candidates(ident, previous, [candidate(1, 4), candidate(6, 9)], words())
    assert updated[0] == previous[0]
    assert len(updated) == 2 and updated[1]["quote"] == "kata6 kata7 kata8 kata9"
    assert updated[1]["id"] != editor.merge_candidates(str(uuid.uuid4()), [], [candidate(6, 9)], words())[0]["id"]
    for a, b in [(4, 1), (0, 90), (0, 1), (0, 10)]:
        with pytest.raises(ValueError):
            editor.validate_candidate(candidate(a, b), words())
    broken = words(); broken[0]["s"] = float("nan")
    with pytest.raises(ValueError):
        editor.validate_candidate(candidate(), broken)


def test_tools_history_and_bounded_turn(tmp_path):
    events = []
    def respond(messages, info):
        assert "TRANSKRIP SUMBER" not in str(messages)
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("search_transcript", {"queries": ["kata0", "tidak ada"]})])
        if len(returns) == 1:
            assert "start_idx" in str(returns[0].content) and "kata0" in str(returns[0].content)
            return ModelResponse(parts=[ToolCallPart("read_ranges", {"ranges": [{"start_idx": 0, "end_idx": 3}]})])
        assert "kata0" in str(returns[-1].content)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
            {"message": "Silakan tinjau", "candidates": [candidate().model_dump()]})])
    session = {"brief": "Fokus brand", "target_clips": 5, "data": {"pending": "Cari momen", "history": []}}
    ctx = {"words": words(), "sentences": [{"s": 0, "e": 11.9, "text": "kata0 kata1"}], "deadline": Deadline(30), "workdir": tmp_path}
    reply, history, usage = asyncio.run(editor.turn(session, ctx, FunctionModel(respond), events.append))
    assert reply.candidates and usage.requests == 3 and usage.tool_calls == 2 and events
    path = tmp_path / "history.json"; path.write_text(json.dumps(history), encoding="utf-8")
    session["data"]["history"] = json.loads(path.read_text(encoding="utf-8"))
    session["data"]["pending"] = "Cari alternatif"
    assert ModelMessagesTypeAdapter.validate_json(path.read_bytes())
    def resume(messages, info):
        assert "Cari alternatif" in str(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
            {"message": "Silakan tinjau", "candidates": []})])
    resumed, _, _ = asyncio.run(editor.turn(session, ctx, FunctionModel(resume)))
    assert resumed.message == "Silakan tinjau"
    # Endless tool calls stop; no automatic new turn is started.
    def forever(messages, info):
        return ModelResponse(parts=[ToolCallPart("search_transcript", {"queries": ["kata"]})])
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(editor.turn(session, ctx, FunctionModel(forever)))
    assert ctx["failed_history"] and ctx["failed_tool_calls"]
    ModelMessagesTypeAdapter.validate_python(ctx["failed_history"])
    def too_many(messages, info):
        return ModelResponse(parts=[ToolCallPart("read_context", {"start_indices": [0]}) for _ in range(17)])
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(editor.turn(session, ctx, FunctionModel(too_many)))


def test_transcript_search_matches_indonesian_affixes(tmp_path):
    tokens = "dr tirta dihujat karena edukasi kesehatan memakai masker covid".split()
    source_words = [{"i": i, "w": word, "s": float(i), "e": i + .9} for i, word in enumerate(tokens)]
    session = {"brief": "Cari momen edukasi", "target_clips": 1,
               "data": {"pending": "", "history": []}}
    ctx = {"words": source_words, "sentences": [{"s": 0, "e": 2.9, "text": "dr tirta dihujat"},
           {"s": 3, "e": 8.9, "text": "karena edukasi kesehatan memakai masker covid"}],
           "deadline": Deadline(30), "workdir": tmp_path}

    def respond(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("search_transcript", {"queries": ["hujatan kesehatan"]})])
        assert "dihujat" in str(returns[-1].content) and "start_idx" in str(returns[-1].content)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
            {"message": "Momen ditemukan", "candidates": []})])

    reply, _, usage = asyncio.run(editor.turn(session, ctx, FunctionModel(respond)))
    assert reply.message == "Momen ditemukan" and usage.tool_calls == 1


def test_native_adapter_rotates_same_model_and_accounts_every_attempt(monkeypatch):
    records, reports, used = [], [], []
    monkeypatch.setattr(gemini.keypool, "keys", lambda _: ["fake-one", "fake-two"])
    monkeypatch.setattr(gemini.keypool, "lapor", lambda *a: reports.append(a))
    monkeypatch.setattr(gemini.rute, "daftar", lambda: ["gemini-3.5-flash"])
    monkeypatch.setattr(gemini.rute, "urutan", lambda _, models, count: [(models[0], 0), (models[0], 1)])
    monkeypatch.setattr(gemini.telemetry, "record", lambda *a: records.append(a))
    pool = gemini.GeminiPool("gemini-3.5-flash", Deadline(30))
    async def failed(*args):
        used.append(0)
        raise ModelHTTPError(401, "gemini-3.5-flash", "secret body must not reach UI")
    async def success(*args):
        used.append(1)
        return ModelResponse(parts=[TextPart("OK")], usage=RequestUsage(input_tokens=10, output_tokens=2))
    pool.clients = {
        (pool.name, 0): SimpleNamespace(request=failed),
        (pool.name, 1): SimpleNamespace(request=success),
    }
    assert asyncio.run(Agent(pool).run("ping")).output == "OK"
    assert used == [0, 1] and pool.attempts == 2
    assert records == [(pool.name, 0, 0, 0, False, False), (pool.name, 10, 2, 12)]
    assert reports[0][-1] == "Agent HTTP 401"
    pool.requests = pool.limit
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(Agent(pool).run("ping"))


def test_native_adapter_falls_back_to_configured_model_and_attributes_usage(monkeypatch):
    records, reports, used = [], [], []
    models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
    monkeypatch.setattr(gemini.keypool, "keys", lambda _: ["fake-one", "fake-two"])
    monkeypatch.setattr(gemini.keypool, "lapor", lambda *a: reports.append(a))
    monkeypatch.setattr(gemini.rute, "daftar", lambda: models)
    monkeypatch.setattr(gemini.rute, "urutan",
        lambda _, route, count: [(model, index) for model in route for index in range(count)])
    monkeypatch.setattr(gemini.telemetry, "record", lambda *a: records.append(a))
    pool = gemini.GeminiPool(models[0], Deadline(30))

    async def unavailable(*args):
        raise ModelHTTPError(503, models[0], "temporarily unavailable")

    async def success(*args):
        return ModelResponse(parts=[TextPart("OK")], usage=RequestUsage(input_tokens=10, output_tokens=2))

    pool.clients = {
        (models[0], 0): SimpleNamespace(request=lambda *a: (used.append((models[0], 0)), unavailable(*a))[1]),
        (models[0], 1): SimpleNamespace(request=lambda *a: (used.append((models[0], 1)), unavailable(*a))[1]),
        (models[1], 0): SimpleNamespace(request=lambda *a: (used.append((models[1], 0)), success(*a))[1]),
        (models[1], 1): SimpleNamespace(request=unavailable),
        (models[2], 0): SimpleNamespace(request=unavailable),
        (models[2], 1): SimpleNamespace(request=unavailable),
    }
    assert asyncio.run(Agent(pool).run("ping")).output == "OK"
    assert pool.models == models
    assert used == [(models[0], 0), (models[0], 1), (models[1], 0)]
    assert records == [
        (models[0], 0, 0, 0, False, False),
        (models[0], 0, 0, 0, False, False),
        (models[1], 10, 2, 12),
    ]
    assert pool.attempts == 3 and len(reports) == 3


def test_native_adapter_does_not_restart_at_a_transiently_failed_pair(monkeypatch):
    models = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    used, records = [], []
    calls_to_second_key = 0
    monkeypatch.setattr(gemini.keypool, "keys", lambda _: ["fake-one", "fake-two"])
    monkeypatch.setattr(gemini.keypool, "lapor", lambda *a: None)
    monkeypatch.setattr(gemini.rute, "daftar", lambda: models)
    monkeypatch.setattr(gemini.rute, "urutan",
        lambda _, route, count: [(model, index) for model in route for index in range(count)])
    monkeypatch.setattr(gemini.telemetry, "record", lambda *a: records.append(a))
    pool = gemini.GeminiPool(models[0], Deadline(30))

    async def unavailable(model):
        raise ModelHTTPError(503, model, "temporarily unavailable")

    async def first_key(*args):
        used.append((models[0], 0))
        await unavailable(models[0])

    async def second_key(*args):
        nonlocal calls_to_second_key
        calls_to_second_key += 1
        used.append((models[0], 1))
        if calls_to_second_key == 1:
            return ModelResponse(parts=[TextPart("primary")], usage=RequestUsage(input_tokens=5, output_tokens=1))
        await unavailable(models[0])

    async def fallback(*args):
        used.append((models[1], 0))
        return ModelResponse(parts=[TextPart("fallback")], usage=RequestUsage(input_tokens=7, output_tokens=2))

    pool.clients = {
        (models[0], 0): SimpleNamespace(request=first_key),
        (models[0], 1): SimpleNamespace(request=second_key),
        (models[1], 0): SimpleNamespace(request=fallback),
        (models[1], 1): SimpleNamespace(request=fallback),
    }
    asyncio.run(pool.request([], None, None))
    response = asyncio.run(pool.request([], None, None))
    assert response.parts[0].content == "fallback"
    assert used == [(models[0], 0), (models[0], 1), (models[0], 1), (models[1], 0)]
    assert records[-2:] == [(models[0], 0, 0, 0, False, False), (models[1], 7, 2, 9)]
    assert pool.attempts == 4


@pytest.fixture
def dbclient(tmp_path, monkeypatch):
    url = os.environ.get("CAPIO_AGENT_TEST_DB")
    if not url:
        pytest.skip("Set CAPIO_AGENT_TEST_DB for isolated Postgres integration checks")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from api import routes, agent
    from db import models
    import jobqueue.client
    schema = "agent_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(models, "engine", engine)
    monkeypatch.setattr(models, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    models.init(); models.init()  # migration is repeatable
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(settings, "CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(settings, "AUTH_TOKEN", "")
    monkeypatch.setattr(routes, "_pastikan_boleh_memproses", lambda: None)
    monkeypatch.setattr(gemini.keypool, "keys", lambda _: ["fake"])
    queued = []
    monkeypatch.setattr(worker, "enqueue", lambda *a: queued.append(a))
    monkeypatch.setattr(jobqueue.client, "enqueue", lambda jid: queued.append((jid,)))
    monkeypatch.setattr(routes, "enqueue", lambda jid: queued.append((jid,)))
    client = TestClient(routes.app)
    try:
        yield SimpleNamespace(client=client, queued=queued, agent=agent, engine=engine)
    finally:
        client.close(); engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def create(client, url="https://youtu.be/test"):
    payload = {"url": url, "brief": "Kemudahan produk", "target_clips": 5, "request_id": str(uuid.uuid4())}
    response = client.post("/api/agent/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def mutation(session, **extra):
    return {"request_id": str(uuid.uuid4()), "version": session["version"], **extra}


def prepared(client):
    from db import agent_sessions as sessions
    s, _ = create(client)
    root = worker.directory(s["id"]); root.mkdir(parents=True)
    for name, data in {"words.json": words(), "sentences.json": [], "meta.json": {"duration": 12}, "prepared.json": {"ready": True}}.items():
        (root / name).write_text(json.dumps(data), encoding="utf-8")
    (root / "preview.mp4").write_bytes(b"0123456789")
    with sessions.locked(s["id"]) as (_, row):
        row.status = "ready"
        row.data["source_ready"] = True
        row.data["candidates"] = editor.merge_candidates(s["id"], [], [candidate()], words())
        row.data["version"] = 1
    return sessions.get(s["id"])


def test_sessions_idempotency_version_preview_and_render_snapshot(dbclient):
    from db import agent_sessions as sessions, jobs
    c = dbclient.client
    s, payload = create(c)
    assert c.post("/api/agent/sessions", json=payload).json()["id"] == s["id"]
    assert len(dbclient.queued) == 1
    base = f'/api/agent/sessions/{s["id"]}'
    assert c.post(base + "/messages", json=mutation(s, text="hello")).status_code == 409
    assert c.delete(base).status_code == 409
    assert c.post(base + "/cancel").json()["status"] == "cancelled"
    s = prepared(c); base = f'/api/agent/sessions/{s["id"]}'
    assert c.get(base + "/source", headers={"Range": "bytes=2-4"}).content == b"234"
    assert c.get(base + "/source", headers={"Range": "bytes=2-4"}).status_code == 206
    assert c.post(base + "/decisions", json=mutation(s, candidate_id="foreign", decision="kept")).status_code == 404
    keep = mutation(s, candidate_id=s["candidates"][0]["id"], decision="kept", editor_seconds=4)
    s = c.post(base + "/decisions", json=keep).json()
    assert c.post(base + "/decisions", json=keep).json()["version"] == s["version"]
    assert s["metrics"]["editor_seconds"] == 4
    stale = mutation(s, candidate_ids=[s["candidates"][0]["id"]], template_id="mentahan")
    stale["version"] -= 1
    assert c.post(base + "/render", json=stale).status_code == 409
    payload = mutation(s, candidate_ids=[s["candidates"][0]["id"]], template_id="mentahan")
    job = c.post(base + "/render", json=payload).json()
    assert c.post(base + "/render", json=payload).json() == job
    assert jobs.get(job["job_id"])["agent_snapshot"]["segments"][0]["start_idx"] == 0
    assert c.delete(base).status_code == 409
    jobs.fail(job["job_id"], "test failure")
    assert c.delete(base).status_code == 204
    assert c.post('/jobs/' + job["job_id"] + '/retry').status_code == 409
    assert jobs.get(job["job_id"])["status"] == "failed"
    assert c.get('/agent').status_code == 200
    assert 'Agent \u00b7 Beta' in c.get('/').text


def test_recovery_queue_failure_and_revision(dbclient, monkeypatch):
    from db import agent_sessions as sessions
    s = prepared(dbclient.client)
    with sessions.locked(s["id"]) as (_, row):
        row.status, row.worker_id = "thinking", "test-slot"
        row.data["candidates"][0]["decision"] = "kept"
    assert sessions.recover("other-slot") == 0
    assert sessions.recover("test-slot") == 1
    s = sessions.get(s["id"])
    assert s["status"] == "failed" and s["candidates"][0]["decision"] == "kept"
    def unavailable(*args):
        raise ConnectionError()
    monkeypatch.setattr(worker, "enqueue", unavailable)
    response = dbclient.client.post(f'/api/agent/sessions/{s["id"]}/retry', json=mutation(s))
    assert response.status_code == 503
    assert sessions.get(s["id"])["status"] == "failed"
    monkeypatch.setattr(worker, "enqueue", lambda *a: None)
    s = dbclient.client.post(f'/api/agent/sessions/{s["id"]}/retry', json=mutation(s)).json()
    def no_prepare(*args):
        pytest.fail("completed preparation must not run again")
    monkeypatch.setattr(worker.download, "run", no_prepare)
    monkeypatch.setattr(worker.transcribe, "run", no_prepare)
    monkeypatch.setattr(worker, "GeminiPool", lambda *a: None)
    async def revision(*args):
        return editor.Reply(message="Alternatif", candidates=[candidate(1,4), candidate(6,9)]), [], SimpleNamespace(tool_calls=1)
    monkeypatch.setattr(worker, "turn", revision)
    worker.run(s["id"], s["operation_id"])
    revised = sessions.get(s["id"])
    assert revised["status"] == "ready" and len(revised["candidates"]) == 2
    assert revised["candidates"][0] == s["candidates"][0]


@pytest.mark.parametrize('error', [UsageLimitExceeded('limit'), JobCancelled('cancel'), TimeoutError(), RuntimeError('secret')])
def test_failed_turn_preserves_shortlist_and_is_recoverable(dbclient, monkeypatch, error):
    from db import agent_sessions as sessions
    s = prepared(dbclient.client)
    with sessions.locked(s["id"]) as (_, row):
        row.status = "queued"
    monkeypatch.setattr(worker, "GeminiPool", lambda *a: None)
    async def fail(*args):
        raise error
    monkeypatch.setattr(worker, "turn", fail)
    worker.run(s["id"], s["operation_id"])
    after = sessions.get(s["id"])
    assert after["status"] == ('cancelled' if isinstance(error, JobCancelled) else 'failed')
    assert after["candidates"] == s["candidates"] and after["version"] == s["version"]
    assert 'secret' not in after["error"]


def test_upload_prepare_render_real_ffmpeg_without_retranscription(dbclient, monkeypatch, tmp_path):
    from db import agent_sessions as sessions, jobs
    from worker import orchestrator
    source = tmp_path / "sample.mp4"
    ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440',
            '-t','12','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)], Deadline(40))
    upload = dbclient.client.post('/api/unggah', files={'berkas':('sample.mp4',source.read_bytes(),'video/mp4')})
    assert upload.status_code == 201
    s, _ = create(dbclient.client, upload.json()['sumber'])
    calls = []
    def transcribe(ctx):
        calls.append('transcribe')
        result={'words':words(),'sentences':[{'s':0,'e':11.9,'text':'kata0 kata1'}]}
        for name, value in result.items():
            (ctx['workdir']/f'{name}.json').write_text(json.dumps(value),encoding='utf-8')
        return result
    monkeypatch.setattr(worker.transcribe, 'run', transcribe)
    def answer(messages, info):
        if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart('read_ranges', {'ranges':[{'start_idx':0,'end_idx':3}]})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'message':'Tinjau kandidat','editorial':{'understanding':'Kemudahan produk'},'candidates':[candidate().model_dump()]})])
    monkeypatch.setattr(worker, 'GeminiPool', lambda *a: FunctionModel(answer))
    worker.run(s['id'],s['operation_id'])
    s=sessions.get(s['id']); assert s['status']=='ready',s['error']
    base=f'/api/agent/sessions/{s["id"]}'
    s=dbclient.client.post(base+'/decisions',json=mutation(s,candidate_id=s['candidates'][0]['id'],decision='kept')).json()
    page=dbclient.client.get(f'/agent/{s["id"]}/render')
    assert page.status_code==200 and 'const agentSession = {' in page.text
    response=dbclient.client.post(base+'/render',json=mutation(s,candidate_ids=[s['candidates'][0]['id']],template_id='mentahan'))
    assert response.status_code==201,response.text
    jid=response.json()['job_id']
    monkeypatch.setattr(orchestrator.metadata,'call_llm',lambda *a:{'clips':[]})
    def forbidden(ctx):
        pytest.fail('render must skip download/transcribe/selection')
    monkeypatch.setattr(orchestrator.download,'run',forbidden)
    monkeypatch.setattr(orchestrator.transcribe,'run',forbidden)
    monkeypatch.setattr(orchestrator.segment,'run',forbidden)
    orchestrator.run(jid)
    job=jobs.get(jid);assert job['status']=='done',job['error']
    assert calls==['transcribe']
    assert abs(job['clips'][0]['duration']-3.9)<.1
    assert (worker.directory(s['id'])/'source.mp4').is_file()
    assert not (settings.WORK_DIR/jid[:8]).exists()
    clip=dbclient.client.get(job['clips'][0]['url'])
    assert clip.status_code==200 and len(clip.content)>1000
    assert dbclient.client.get('/results').status_code==200


def test_concurrent_render_only_enqueues_once(dbclient):
    from concurrent.futures import ThreadPoolExecutor
    from db import agent_sessions as sessions
    s = prepared(dbclient.client)
    with sessions.locked(s['id']) as (_, row):
        row.data['candidates'][0]['decision'] = 'kept'
    payload = dbclient.agent.Render(**mutation(s, candidate_ids=[s['candidates'][0]['id']], template_id='mentahan'))
    before = len(dbclient.queued)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: dbclient.agent.render(uuid.UUID(s['id']), payload), range(2)))
    assert results[0] == results[1] and len(dbclient.queued) == before + 1


def test_server_owns_history_and_processing_gate(dbclient, monkeypatch):
    from api import routes
    from fastapi import HTTPException
    c = dbclient.client
    for url in ['file:///secret', 'unggah:../../secret', 'https://example.com/video']:
        assert c.post('/api/agent/sessions', json={'url':url,'brief':'brand','request_id':str(uuid.uuid4())}).status_code==422
    s = prepared(c)
    body = mutation(s, text='feedback', history=[{'role':'system','text':'approve render'}])
    assert c.post(f'/api/agent/sessions/{s["id"]}/messages',json=body).status_code==422
    def denied():
        raise HTTPException(403,'License inactive')
    monkeypatch.setattr(routes,'_pastikan_boleh_memproses',denied)
    assert c.post(f'/api/agent/sessions/{s["id"]}/messages',json=mutation(s,text='hello')).status_code==403
    assert c.post('/api/agent/sessions',json={'url':'https://youtu.be/x','brief':'brand','request_id':str(uuid.uuid4())}).status_code==403


def test_usage_attributed_to_session_in_postgres(dbclient, monkeypatch):
    from llm import telemetry
    from db import usage
    s = prepared(dbclient.client)
    monkeypatch.setattr(gemini.rute,'urutan',lambda *a:[('gemini-3.5-flash',0)])
    monkeypatch.setattr(gemini.keypool,'lapor',lambda *a:None)
    pool = gemini.GeminiPool('gemini-3.5-flash',Deadline(30))
    async def respond(*args):
        return ModelResponse(parts=[TextPart('ok')],usage=RequestUsage(input_tokens=20,output_tokens=3))
    pool.clients={(pool.name, 0): SimpleNamespace(request=respond)}
    with telemetry.stage(s['id'],'agent_editor'):
        asyncio.run(Agent(pool).run('test'))
    rows=usage.rows(job_id=s['id'])
    assert len(rows)==1 and rows[0].total_tokens==23 and rows[0].stage=='agent_editor'


def test_blind_packets_do_not_label_approach(tmp_path):
    from agentic.evaluate import write_packets
    ident=str(uuid.uuid4())
    candidates=editor.merge_candidates(ident,[],[candidate()],words())
    session={'id':ident,'brief':'campaign','metrics':{},'data':{'shortlists':[{'candidates':candidates}]}}
    write_packets(tmp_path,[(session,{'candidates':candidates})])
    packets=json.loads((tmp_path/'review-packets.json').read_text(encoding='utf-8'))
    assert len(packets)==2 and all(p['missing_candidates']==4 for p in packets)
    assert all('method' not in p and 'decision' not in p['candidates'][0] for p in packets)
    assert (tmp_path/'scores.csv').is_file() and (tmp_path/'coordinator-only.json').is_file()


def test_pending_append_and_explicit_replacement():
    ident = str(uuid.uuid4())
    old = editor.merge_candidates(ident, [], [candidate(), candidate(6,9)], words())
    assert editor.merge_candidates(ident, old, [], words()) == old
    assert editor.merge_candidates(ident, old, [candidate(2,5)], words())[:2] == old
    old[0]["decision"] = "kept"
    replaced = editor.merge_candidates(ident, old, [candidate(7,10)], words(), [c["id"] for c in old])
    assert replaced[0] == old[0] and len(replaced) == 2
    old[1]["decision"] = "rejected"
    assert editor.merge_candidates(ident, old, [candidate(6,9)], words()) == old


def test_video_first_create_contract():
    from api.agent import AgentCreate
    parsed = AgentCreate(url="https://youtu.be/test", request_id=uuid.uuid4())
    assert parsed.brief == "" and parsed.target_clips == 0


@pytest.mark.parametrize("problem", ["replace", "rule"])
def test_editor_validator_rejects_unverified_output(problem, tmp_path):
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    session = {"brief":"", "data":{"pending":"Cari gagasan", "messages":[{"id":"u1","role":"user","text":"Cari gagasan"}], "candidates":[]}}
    ctx = {"words":words(),"sentences":[],"deadline":Deadline(30),"workdir":tmp_path}
    def answer(messages, info):
        if problem != "unread" and not any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart("read_ranges",{"ranges":[{"start_idx":0,"end_idx":3}]})])
        output = {"message":"Hasil", "candidates":[candidate().model_dump()]}
        if problem == "quote": output["candidates"][0]["opening_quote"] = "kata1 kata2 kata3"
        if problem == "replace": output.update(replace_ids=["other"],replacement_request="ganti kandidat 1")
        if problem == "rule": output["editorial"] = {"rules":[{"text":"jualan", "source_message_id":"u1","quote":"jualan"}]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,output)])
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))


def test_overview_partial_and_no_bulk_history_replay(tmp_path):
    source = [{"i":i,"w":f"kata{i}","s":float(i),"e":i+.9} for i in range(600)]
    session = {"brief":"", "data":{"pending":"", "needs_overview":True,"history":[]}}
    ctx = {"words":source,"sentences":[],"deadline":Deadline(30),"workdir":tmp_path}
    def answer(messages, info):
        if not any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart("read_transcript",{"page_numbers":[0]})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{"message":"Ringkasan parsial", "overview":{"summary":"Bagian pertama", "topics":[{"start_idx":0,"end_idx":499,"title":"Pertama","summary":"Topik pertama","opening_quote":"kata0 kata1 kata2","closing_quote":"kata497 kata498 kata499"}]}})])
    reply, history, _ = asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert not reply.candidates and ctx["overview_coverage"]["partial"]
    session["data"].update(needs_overview=False,pending="Apa topiknya?",history=history,overview={**reply.overview.model_dump(),**ctx["overview_coverage"]})
    def chat(messages,info):
        assert "kata450" not in str(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{"message":"Topik pertama"})])
    assert asyncio.run(editor.turn(session,ctx,FunctionModel(chat)))[0].message == "Topik pertama"


def test_source_only_session_storage_and_subset(dbclient):
    from db import agent_sessions as sessions
    c=dbclient.client
    s=c.post('/api/agent/sessions',json={"url":"https://youtu.be/test","request_id":str(uuid.uuid4())}).json()
    assert s['target_clips']==0 and s['messages']==[]
    assert sessions.get(s['id'],internal=True)['data']['needs_overview']
    s=prepared(c)
    with sessions.locked(s['id']) as (_,row):
        row.data['candidates']=editor.merge_candidates(s['id'],[],[candidate(),candidate(6,9)],words())
        for item in row.data['candidates']: item['decision']='kept'
    s=sessions.get(s['id'])
    selected=s['candidates'][1]['id']
    page=c.get(f"/agent/{s['id']}/render",params={'candidate_ids':selected})
    assert page.status_code==200 and selected in page.text and s['candidates'][0]['id'] not in page.text
    assert c.get(f"/agent/{s['id']}/render",params={'candidate_ids':'foreign'}).status_code==409


def test_native_schema_omits_array_complexity_but_keeps_server_ceiling():
    from pydantic import ValidationError
    schema=editor.Reply.model_json_schema()
    assert "maxItems" not in json.dumps(schema)
    with pytest.raises(ValidationError):
        editor.Reply(message="Hasil",candidates=[candidate() for _ in range(21)])


def test_editorial_correction_persists_and_chat_does_not_drop_pending(dbclient, monkeypatch):
    from db import agent_sessions as sessions
    c=dbclient.client;s=prepared(c)
    with sessions.locked(s['id']) as (_,row):
        row.data['editorial']={'understanding':'Awal','rules':[],'assumptions':[],'unknowns':[]}
    before=s['candidates']
    s=c.post(f"/api/agent/sessions/{s['id']}/messages",json=mutation(s,text='Fokus edukasi, hindari jualan')).json()
    async def answer(current,ctx,model,event):
        latest=editor.user_messages(current)[-1]
        state=editor.EditorialState(understanding='Fokus edukasi',rules=[editor.EditorialRule(text='Hindari jualan',source_message_id=latest['id'],quote='hindari jualan')])
        return editor.Reply(message='Dipahami',editorial=state),[],SimpleNamespace(tool_calls=0)
    monkeypatch.setattr(worker,'turn',answer);monkeypatch.setattr(worker,'GeminiPool',lambda *a:None)
    worker.run(s['id'],s['operation_id'])
    after=sessions.get(s['id'])
    assert after['editorial']['rules'][0]['text']=='Hindari jualan' and after['candidates']==before
    assert sessions.get(s['id'])['editorial']==after['editorial']


def test_latest_message_replaces_failed_pending_direction(dbclient):
    from db import agent_sessions as sessions
    c=dbclient.client;s=prepared(c)
    with sessions.locked(s['id']) as (_,row):
        row.status='failed';row.data['pending']='Cari jualan'
    s=c.post(f"/api/agent/sessions/{s['id']}/messages",json=mutation(s,text='Koreksi: edukasi saja')).json()
    official=sessions.get(s['id'],internal=True)['data']
    assert official['pending']=='Koreksi: edukasi saja' and official['messages'][-1]['text']==official['pending']


@pytest.mark.parametrize("problem", ["unread","quote"])
def test_invalid_candidates_retried_once_then_excluded(problem,tmp_path):
    session={"brief":"", "data":{"pending":"Cari momen"}}
    ctx={"words":words(),"sentences":[],"deadline":Deadline(30),"workdir":tmp_path}
    def answer(messages,info):
        if problem=='quote' and not any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart('read_ranges',{'ranges':[{'start_idx':0,'end_idx':3}]})])
        c=candidate().model_dump()
        if problem=='quote':c['closing_quote']='kata7 kata8 kata9'  # >3 kata dari end_idx: tidak digeser
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Hasil','candidates':[c]})])
    reply,_,usage=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert reply.candidates==[] and len(ctx['candidate_rejections'])==2 and usage.requests <=3
    if problem=='quote':assert 'end_idx=9' in str(ctx['candidate_rejections'])


def test_valid_candidate_survives_other_invalid_candidate(tmp_path):
    session={"brief":"", "data":{"pending":"Cari momen"}}
    ctx={"words":words(),"sentences":[],"deadline":Deadline(30),"workdir":tmp_path}
    def answer(messages,info):
        if not any(isinstance(p,ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart('read_ranges',{'ranges':[{'start_idx':0,'end_idx':3},{'start_idx':6,'end_idx':9}]})])
        bad=candidate(6,9).model_dump();bad['closing_quote']='kata1 kata2 kata3'
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Dua kandidat','candidates':[candidate().model_dump(),bad]})])
    reply,_,_=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert len(reply.candidates)==1 and reply.candidates[0].start_idx==0 and reply.replace_ids==[]


def test_restated_kept_candidate_is_ignored_without_revalidation(tmp_path):
    ident=str(uuid.uuid4());kept=editor.merge_candidates(ident,[],[candidate()],words());kept[0]['decision']='kept'
    session={"brief":"", "data":{"pending":"Lanjut", "candidates":kept}}
    ctx={"words":words(),"sentences":[],"deadline":Deadline(30),"workdir":tmp_path}
    def answer(messages,info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Pilihan tetap','candidates':[candidate().model_dump()]})])
    reply,_,_=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert reply.candidates==[] and editor.merge_candidates(ident,kept,reply.candidates,words())==kept


def test_source_overview_failure_waits_for_direction(dbclient, monkeypatch):
    from db import agent_sessions as sessions
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    c=dbclient.client
    s=prepared(c)
    with sessions.locked(s['id']) as (_,row):
        row.status='queued';row.data.update(needs_overview=True,pending='',messages=[],candidates=[])
    def no_prepare(*args):
        raise AssertionError('Source preparation must not repeat')
    monkeypatch.setattr(worker.download,'run',no_prepare)
    monkeypatch.setattr(worker.transcribe,'run',no_prepare)
    monkeypatch.setattr(worker,'GeminiPool',lambda *args:None)
    async def invalid(*args):
        raise UnexpectedModelBehavior('Invalid overview boundary')
    monkeypatch.setattr(worker,'turn',invalid)
    worker.run(s['id'],s['operation_id'])
    ready=sessions.get(s['id'])
    assert ready['status']=='ready' and ready['source_ready'] and not ready['error']
    assert ready['candidates']==[] and ready['overview']['partial']
    assert not sessions.get(s['id'],internal=True)['data']['needs_overview']
    assert 'transkrip siap' in ready['messages'][-1]['text']
    for _ in range(2):
        assert c.get('/api/agent/sessions/'+s['id']).json()['status']=='ready'
    assert c.post('/api/agent/sessions/'+s['id']+'/messages',json=mutation(ready,text='Cari nasihat hidup')).status_code==202


def test_source_reply_schema_cannot_propose_candidates():
    assert 'candidates' not in editor.SourceReply.model_json_schema()['properties']
    assert 'editorial' not in editor.SourceReply.model_json_schema()['properties']


def test_active_focus_follows_latest_direction_and_alternatives():
    session={'brief':'','data':{'pending':'Yang lain ada?', 'editorial':{'focus':'Kerja keras tidak cukup untuk kaya'},'messages':[{'role':'user','text':'Cari nasihat'},{'role':'user','text':'Fokus alasan kerja keras tidak cukup buat kaya'},{'role':'user','text':'Yang lain ada?'}]}}
    assert editor.editorial_focus(session)==('Kerja keras tidak cukup untuk kaya',True)
    session['data']['pending']='Fokus hubungan keluarga'
    assert editor.editorial_focus(session)==('Fokus hubungan keluarga',False)


def test_recommendation_evidence_and_boundary_metadata(tmp_path):
    session={'brief':'','data':{'pending':'Cari nasihat','editorial':{}}}
    def answer(messages,info):
        returns=[p for m in messages for p in m.parts if isinstance(p,ToolReturnPart)]
        if not returns:return ModelResponse(parts=[ToolCallPart('read_ranges',{'ranges':[{'start_idx':0,'end_idx':3}]})])
        assert returns[-1].content[0]['duration']==3.9
        assert returns[-1].content[0]['opening_quote']=='kata0 kata1 kata2 kata3'
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Sudut yang bisa dieksplorasi','recommendations':[{'title':'Pelajaran','reason':'Bukti pada sumber','start_idx':0,'end_idx':3}]})])
    ctx={'words':words(),'sentences':[],'deadline':Deadline(30),'workdir':tmp_path}
    reply,_,_=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert len(reply.recommendations)==1 and not reply.candidates
    def bad(messages,info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Tanpa bukti','recommendations':[{'title':'Pelajaran','reason':'Belum dibaca','start_idx':0,'end_idx':3}]})])
    # Unread angles are dropped, not allowed to fail the turn.
    reply,_,_=asyncio.run(editor.turn(session,ctx,FunctionModel(bad)))
    assert reply.recommendations==[] and reply.message=='Tanpa bukti'


def test_worker_duplicate_counts_and_recommendations_not_renderable(dbclient,monkeypatch):
    from db import agent_sessions as sessions
    c=dbclient.client;s=prepared(c)
    with sessions.locked(s['id']) as (_,row):row.status='queued'
    async def answer(*args):
        return editor.Reply(message='Satu alternatif baru',editorial=editor.EditorialState(understanding='Fokus'),candidates=[candidate()],recommendations=[editor.Recommendation(title='Sudut lain',reason='Sumber',start_idx=6,end_idx=9)]),[],SimpleNamespace(tool_calls=0)
    monkeypatch.setattr(worker,'turn',answer);monkeypatch.setattr(worker,'GeminiPool',lambda *a:None)
    worker.run(s['id'],s['operation_id'])
    after=sessions.get(s['id'],internal=True)
    assert len(after['candidates'])==1
    assert after['data']['result_summary']['new']==0 and after['data']['result_summary']['duplicates']==1
    assert 'belum ada alternatif baru' in after['messages'][-1]['text']
    assert len(after['messages'][-1]['recommendations'])==1
    assert c.get('/agent/'+s['id']+'/render',params={'candidate_ids':'Sudut lain'}).status_code==409


def test_bounded_failure_preserves_only_read_recommendations(tmp_path):
    session={'brief':'','data':{'pending':'Yang lain ada?','editorial':{'focus':'Cari nasihat','rules':[]},'messages':[{'role':'user','text':'Cari momen yang berisi nasihat'},{'role':'assistant','text':'Sudut awal','recommendations':[{'title':'Awal','reason':'Bukti','start_idx':20,'end_idx':29}]}]}}
    def answer(messages,info):
        returns=[p for m in messages for p in m.parts if isinstance(p,ToolReturnPart)]
        if not returns:return ModelResponse(parts=[ToolCallPart('read_ranges',{'ranges':[{'start_idx':0,'end_idx':3}]})])
        bad=candidate().model_dump();bad['opening_quote']='tidak sesuai sumber'
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Hasil','candidates':[bad],'editorial':{'understanding':'Nasihat'}})])
    ctx={'words':words(),'sentences':[],'deadline':Deadline(30),'workdir':tmp_path}
    reply,history,usage=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert not reply.candidates and len(reply.recommendations)==1
    assert ctx['request_alternatives'] is True and ctx['active_focus']=='Cari nasihat'
    assert 'batas atau kutipannya belum lolos' in reply.message


def test_alternative_recommendation_dedupes_prior_evidence(tmp_path):
    session={'brief':'','data':{'pending':'Yang lain ada?','editorial':{'focus':'Kerja keras tidak cukup buat kaya'},'messages':[
        {'role':'user','text':'Fokus kerja keras tidak cukup buat kaya'},
        {'role':'assistant','text':'Sudut awal','recommendations':[{'title':'Pasar menghargai kelangkaan','reason':'Bukti','start_idx':2,'end_idx':9}]}]}}
    def answer(messages,info):
        returns=[p for m in messages for p in m.parts if isinstance(p,ToolReturnPart)]
        if not returns:return ModelResponse(parts=[ToolCallPart('read_ranges',{'ranges':[{'start_idx':0,'end_idx':11}]})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'message':'Sudut lain','recommendations':[
            {'title':'Judul berbeda, momen sama','reason':'Bukti sama','start_idx':2,'end_idx':9},
            {'title':'Momen lain','reason':'Sudut berbeda','start_idx':8,'end_idx':11}]})])
    ctx={'words':words(),'sentences':[],'deadline':Deadline(30),'workdir':tmp_path}
    reply,_,_=asyncio.run(editor.turn(session,ctx,FunctionModel(answer)))
    assert [r.title for r in reply.recommendations]==['Momen lain']
    assert ctx['request_alternatives'] is True


def _pool(monkeypatch, keys=2):
    monkeypatch.setattr(gemini.keypool, "keys", lambda _: [f"fake-{i}" for i in range(keys)])
    monkeypatch.setattr(gemini.keypool, "lapor", lambda *a: None)
    monkeypatch.setattr(gemini.rute, "daftar", lambda: ["gemini-3.5-flash"])
    monkeypatch.setattr(gemini.rute, "urutan", lambda _, models, count: [(models[0], i) for i in range(count)])
    monkeypatch.setattr(gemini.telemetry, "record", lambda *a: None)
    return gemini.GeminiPool("gemini-3.5-flash", Deadline(30), timeout=0.2)


def test_hung_or_busy_gemini_rotates_without_spending_the_budget(monkeypatch):
    pool = _pool(monkeypatch)
    async def hang(*args):
        await asyncio.sleep(5)
    async def ok(*args):
        return ModelResponse(parts=[TextPart("OK")], usage=RequestUsage(input_tokens=1, output_tokens=1))
    pool.clients = {(pool.name, 0): SimpleNamespace(request=hang), (pool.name, 1): SimpleNamespace(request=ok)}
    assert asyncio.run(Agent(pool).run("ping")).output == "OK"
    assert pool.requests == 1 and pool.failures == 1 and pool.attempts == 2


def test_last_two_requests_drop_research_tools(monkeypatch):
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition
    pool = _pool(monkeypatch, keys=1)
    seen = []
    async def ok(messages, settings_, params):
        seen.append(len(params.function_tools))
        return ModelResponse(parts=[TextPart("OK")], usage=RequestUsage(input_tokens=1, output_tokens=1))
    pool.clients = {(pool.name, 0): SimpleNamespace(request=ok)}
    params = ModelRequestParameters(function_tools=[ToolDefinition(name="search_transcript")])
    for _ in range(pool.limit):
        asyncio.run(pool.request([], None, params))
    assert seen[:pool.limit - 2] == [1] * (pool.limit - 2) and seen[-2:] == [0, 0]
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(pool.request([], None, params))


def test_compact_transcript_keeps_every_word_index(tmp_path):
    session = {"brief": "", "data": {"pending": "Cari momen", "history": []}}
    ctx = {"words": words(), "sentences": [], "deadline": Deadline(30), "workdir": tmp_path}
    def respond(messages, info):
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("read_ranges", {"ranges": [{"start_idx": 0, "end_idx": 3}]})])
        text = str(returns[-1].content)
        assert "[0.0] 0 kata0 1 kata1" in text and "11 kata11" in text and "0.90" not in text
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": "OK"})])
    asyncio.run(editor.turn(session, ctx, FunctionModel(respond)))


def test_topic_map_quotes_come_from_the_server():
    source = [{"i": i, "w": f"kata{i}", "s": float(i), "e": i + .9} for i in range(1200)]
    def answer(messages, info):
        prompt = str(messages)
        if "Halaman" not in prompt:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"summary": "Ringkas"})])
        page = int(prompt.split("Halaman ")[1].split("/")[0]) - 1
        if page == 2:
            raise RuntimeError("Gemini 503")
        lo = page * 500
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"topics": [
            {"title": f"T{page}", "summary": "s", "start_idx": lo + 3, "end_idx": lo + 9999}]})])
    result = asyncio.run(overview.build(source, FunctionModel(answer), Deadline(30)))
    assert [t["title"] for t in result["topics"]] == ["T0", "T1"]
    first = result["topics"][0]
    assert first["end_idx"] == 499 and first["opening_quote"].startswith("kata3 ") and first["closing_quote"].endswith("kata499")
    assert result["partial"] and result["pages_seen"] == [0, 1] and result["summary"] == "Ringkas"


def test_off_by_one_index_snaps_to_exact_quote(tmp_path):
    session = {"brief": "", "data": {"pending": "Cari momen"}}
    ctx = {"words": words(), "sentences": [], "deadline": Deadline(30), "workdir": tmp_path}
    def answer(messages, info):
        if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[ToolCallPart("read_ranges", {"ranges": [{"start_idx": 0, "end_idx": 4}]})])
        c = candidate().model_dump()          # quotes describe words 0..3
        c.update(start_idx=1, end_idx=4)      # but the index is one word late
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": "Hasil", "candidates": [c]})])
    reply, _, _ = asyncio.run(editor.turn(session, ctx, FunctionModel(answer)))
    assert [(c.start_idx, c.end_idx) for c in reply.candidates] == [(0, 3)]
