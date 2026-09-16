"""Layout dipilih per video, bukan sekali di setelan.

Podcast serius dan potongan lucu tidak memakai bentuk yang sama, dan keputusan
itu diambil saat menempel link. Yang dijaga di sini adalah jalur nilainya:
dari form Submit, masuk ke baris job, lalu terbaca worker saat gilirannya tiba.

Bagian yang paling gampang bocor adalah as_dict(): kolomnya ada di database,
tersimpan dengan benar, tapi tidak ikut diserialisasi — dan JobOut punya
default "penuh", jadi yang terlihat di UI selalu penuh tanpa satu pun error.
Persis itu yang terjadi saat fitur ini pertama disambung.
"""
import pytest

from config.settings import settings


def _db_ready() -> bool:
    try:
        from sqlalchemy import create_engine, text

        probe = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 2})
        with probe.connect() as c:
            c.execute(text("select 1"))
        probe.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _db_ready(), reason="Postgres tidak jalan — `docker compose up -d`"
)


@pytest.fixture(autouse=True)
def jangan_antre(monkeypatch):
    """Test ini memakai Redis yang sama dengan worker produksi; tanpa ini tiap
    pytest benar-benar mengunduh video."""
    from api import routes

    monkeypatch.setattr(routes, "enqueue", lambda job_id: None)


@pytest.fixture
def bersihkan():
    from sqlalchemy import select

    from db.models import Job, session_scope

    with session_scope() as s:
        sebelum = {str(x) for x in s.scalars(select(Job.id)).all()}
    yield
    with session_scope() as s:
        for j in s.scalars(select(Job)).all():
            if str(j.id) not in sebelum:
                s.delete(j)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.routes import app

    with TestClient(app) as c:
        yield c


URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _buat(client, **extra):
    r = client.post("/jobs", json={"url": URL, "target_clips": 2, **extra})
    assert r.status_code in (200, 201), r.text
    return client.get(f"/jobs/{r.json()['job_id']}").json()


# --- jalur nilai ---

@pytest.mark.parametrize("nama", ["penuh", "duo", "kotak", "samping"])
def test_layout_pilihan_tersimpan_dan_terbaca(client, bersihkan, nama):
    """Regresi: kolomnya sempat tersimpan benar tapi tidak ikut as_dict(),
    sehingga UI selalu menampilkan 'penuh' tanpa satu pun error."""
    assert _buat(client, layout=nama)["layout"] == nama


def test_tanpa_layout_ikut_default_setelan(client, bersihkan, monkeypatch):
    monkeypatch.setattr(settings, "CLIP_LAYOUT", "kotak")
    assert _buat(client)["layout"] == "kotak"


def test_default_setelan_ngawur_jatuh_ke_penuh(client, bersihkan, monkeypatch):
    """Nilai lama atau salah ketik di .env jangan menghasilkan job yang gagal
    di stage render — belasan menit setelah submit."""
    monkeypatch.setattr(settings, "CLIP_LAYOUT", "entah-apa")
    assert _buat(client)["layout"] == "penuh"


def test_layout_tidak_dikenal_ditolak_saat_submit(client, bersihkan):
    """Ditolak SEKARANG, bukan nanti: kegagalan di stage render terjadi setelah
    unduhan dan transkrip selesai, jadi salah ketik membuang belasan menit."""
    r = client.post("/jobs", json={"url": URL, "layout": "ngawur"})
    assert r.status_code == 422
    assert "tidak dikenal" in r.text


def test_layout_kosong_bukan_error(client, bersihkan):
    """Form yang preview-nya gagal dimuat tetap mengirim layout kosong —
    itu harus jatuh ke default, bukan menolak submit."""
    assert _buat(client, layout=None)["layout"] in {"penuh", "kotak", "samping"}


def test_layout_mentahan_bisa_dipilih(client, bersihkan):
    assert _buat(client, layout="ori")["layout"] == "ori"


# --- saklar caption ---

def test_caption_mati_selamat_sampai_baris_job(client, bersihkan):
    """Jebakannya `False == 0` di Python: saringan gaya membuang nilai kosong
    dengan `not in (None, "", 0, "0")`, dan False cocok dengan 0 di situ. Kalau
    lolos ke saringan itu, saklarnya terbuang justru saat DIMATIKAN — caption
    tetap terbakar dan tidak ada satu pun error."""
    assert _buat(client, gaya={"caption": False})["gaya"]["caption"] is False


def test_caption_nyala_tidak_disimpan(client, bersihkan):
    """Nyala adalah default. Menyimpannya berarti job lama tanpa kunci ini jadi
    ambigu — dan itu satu-satunya bedanya dengan knob tampilan lain."""
    assert "caption" not in _buat(client, gaya={"caption": True}).get("gaya", {})


def test_caption_mati_tidak_menghapus_knob_lain(client, bersihkan):
    """Orang bisa mematikan caption lalu menyalakannya lagi — warna dan font
    yang sudah disetel jangan ikut hilang."""
    g = _buat(client, gaya={"caption": False, "font": "Anton"})["gaya"]
    assert g["caption"] is False and g["font"] == "Anton"


# --- worker memakai yang tersimpan, bukan yang sedang aktif ---

def test_worker_membaca_layout_dari_baris_job(monkeypatch, tmp_path):
    """Job yang mengantre berjam-jam harus keluar dengan bentuk yang dipilih
    waktu itu, bukan bentuk yang kebetulan aktif saat gilirannya tiba."""
    from db.models import Status
    from worker import orchestrator

    monkeypatch.setattr(orchestrator.env_store, "reload", lambda: None)
    monkeypatch.setattr(orchestrator.jobs, "get", lambda j: {
        "url": URL, "target_clips": 3, "layout": "samping"})
    monkeypatch.setattr(orchestrator.jobs, "update_status", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator.jobs, "fail", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator.settings, "WORK_DIR", tmp_path)
    monkeypatch.setattr(settings, "CLIP_LAYOUT", "kotak")   # setelan BERBEDA

    terlihat = {}

    class Rekam:
        def run(self, ctx):
            terlihat["layout"] = ctx.get("layout")
            raise RuntimeError("berhenti di sini")

    monkeypatch.setattr(orchestrator, "STAGES", [(Status.DOWNLOADING, Rekam())])
    monkeypatch.setattr(orchestrator, "TOTAL_STEPS", 2)
    with pytest.raises(RuntimeError):
        orchestrator.run("00000000-0000-0000-0000-000000000009")

    assert terlihat["layout"] == "samping"
