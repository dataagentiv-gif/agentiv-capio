"""Template dipilih per video dan disimpan lengkap di baris job."""
import pytest

from config.settings import settings
from pipeline.templates import TEMPLATES, resolve


def _db_ready():
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="Postgres belum jalan")
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    from api import routes
    monkeypatch.setattr(routes, "enqueue", lambda job_id: None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from api.routes import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cleanup():
    from sqlalchemy import select
    from db.models import Job, session_scope
    with session_scope() as session:
        before = {str(x) for x in session.scalars(select(Job.id)).all()}
    yield
    with session_scope() as session:
        for job in session.scalars(select(Job)).all():
            if str(job.id) not in before:
                session.delete(job)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_template_disimpan_dengan_default(client, cleanup, template_id):
    r = client.post("/jobs", json={"url": URL, "target_clips": 2, "template_id": template_id})
    assert r.status_code == 201, r.text
    job = client.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["template_id"] == template_id
    assert job["adjustments"] == resolve(template_id, {})


def test_adjustment_tidak_relevan_ditolak(client, cleanup):
    r = client.post("/jobs", json={"url": URL, "template_id": "mentahan",
                                    "adjustments": {"caption_motion": "soft_focus"}})
    assert r.status_code == 422


def test_custom_ditolak(client, cleanup):
    r = client.post("/jobs", json={"url": URL, "template_id": "custom"})
    assert r.status_code == 422


def test_retry_lama_ditolak(client, cleanup):
    from db.models import Job, Status, session_scope
    with session_scope() as session:
        job = Job(url=URL, target_clips=2, layout="penuh", status=Status.FAILED)
        session.add(job)
        session.flush()
        job_id = str(job.id)
    r = client.post(f"/jobs/{job_id}/retry")
    assert r.status_code == 409
    assert "submit ulang" in r.text.lower()
