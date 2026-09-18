"""Kegagalan deadline harus menyebut stage mana yang menghabiskan anggaran.

Batas waktu job dibagi seluruh stage, jadi saat terlampaui pertanyaannya selalu
"siapa yang memakannya". Terjadi sungguhan: satu video 26 menit gagal karena
UNDUHANNYA sendiri menghabiskan seluruh 1800 detik, tapi pesannya cuma "deadline
job terlampaui" — terlihat seperti pipeline rusak, padahal cuma perlu waktu
lebih panjang.
"""
import pytest

from worker.orchestrator import _rincian


# --- format rincian ---

def test_stage_paling_boros_disebut_lebih_dulu():
    """Itu satu-satunya angka yang dicari orang saat membaca pesan ini."""
    teks = _rincian({"transcribing": 12.0, "downloading": 400.0, "rendering": 90.0})
    assert teks.startswith("downloading 400s")
    assert teks.index("rendering") < teks.index("transcribing")


def test_detik_dibulatkan_tanpa_desimal():
    """Pesan error dibaca manusia; 400.37281s cuma bikin susah dibaca."""
    assert _rincian({"downloading": 400.37281}) == "downloading 400s"


def test_kosong_menghasilkan_string_kosong():
    """Deadline bisa terlampaui SEBELUM satu stage pun selesai — pemanggilnya
    yang mengganti ini dengan keterangan yang bisa dimengerti."""
    assert _rincian({}) == ""


def test_hasil_menandai_duo_yang_fallback(monkeypatch):
    from worker import orchestrator

    monkeypatch.setattr(
        orchestrator.storage, "save_clip", lambda job, cid, path: f"/{job}/{cid}")
    meta = {"title": "Judul", "caption": "Caption", "hashtags": []}
    seg = {"id": "c1", "start": 0.0, "end": 8.0, "score": 90,
           "hook": "Hook", "reason": "Alasan"}
    ctx = {
        "layout": "duo", "segments_final": [seg],
        "metadata": {"c1": meta}, "rendered": {"c1": "hasil.mp4"},
        "crops": {"c1": {"duo": None}},
    }
    clip = orchestrator._build_clips(ctx, "job-1")[0]
    assert clip["layout"] == "penuh"
    assert clip["layout_fallback"] is True


def test_hasil_mempertahankan_podcast_jika_pasangan_stabil(monkeypatch):
    from worker import orchestrator

    monkeypatch.setattr(
        orchestrator.storage, "save_clip", lambda job, cid, path: f"/{job}/{cid}")
    seg = {"id": "c1", "start": 0.0, "end": 8.0, "score": 90,
           "hook": "Hook", "reason": "Alasan"}
    ctx = {
        "layout": "duo", "segments_final": [seg],
        "metadata": {"c1": {"title": "Judul", "caption": "Caption", "hashtags": []}},
        "rendered": {"c1": "hasil.mp4"},
        "crops": {"c1": {"duo": [{"x": 0}, {"x": 960}]}},
    }
    clip = orchestrator._build_clips(ctx, "job-1")[0]
    assert clip["layout"] == "duo"
    assert clip["layout_fallback"] is False


# --- pesan kegagalan ---

@pytest.fixture
def jalankan(monkeypatch, tmp_path):
    """Jalankan orchestrator dengan stage palsu, tanpa menyentuh jaringan,
    ffmpeg, maupun database sungguhan."""
    from db.models import Status
    from worker import orchestrator

    dicatat = {}

    monkeypatch.setattr(orchestrator.env_store, "reload", lambda: None)
    monkeypatch.setattr(orchestrator.jobs, "get", lambda j: {
        "url": "https://youtu.be/x", "target_clips": 3})
    monkeypatch.setattr(orchestrator.jobs, "update_status", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator.jobs, "fail",
                        lambda jid, err: dicatat.update(error=err))
    monkeypatch.setattr(orchestrator.settings, "WORK_DIR", tmp_path)

    def _pasang(stages):
        monkeypatch.setattr(orchestrator, "STAGES", stages)
        monkeypatch.setattr(orchestrator, "TOTAL_STEPS", len(stages) + 1)
        with pytest.raises(TimeoutError):
            orchestrator.run("00000000-0000-0000-0000-000000000001")
        return dicatat["error"]

    _pasang.Status = Status
    return _pasang


#: Jam semu bersama. Dipakai lewat daftar satu elemen supaya stage bisa
#: memajukannya tanpa `global` — dan JANGAN diganti dengan iterator nilai
#: tetap: `import time` menghasilkan objek modul yang sama di mana-mana, jadi
#: menambal time.monotonic juga menambalnya untuk Deadline, yang ikut
#: memakan nilai-nilai itu dan membuat hasilnya meleset tanpa sebab yang jelas.
JAM = [0.0]


class _Stage:
    """Stage palsu: memajukan jam semu lalu mengembalikan ctx kosong."""

    def __init__(self, detik=0.0, meledak=False):
        self.detik, self.meledak = detik, meledak

    def run(self, ctx):
        JAM[0] += self.detik
        if self.meledak:
            raise TimeoutError("deadline job terlampaui")
        return {}


def test_pesan_menyebut_stage_yang_sudah_selesai(jalankan, monkeypatch):
    from worker import orchestrator

    JAM[0] = 0.0
    monkeypatch.setattr(orchestrator.time, "monotonic", lambda: JAM[0])

    S = jalankan.Status
    pesan = jalankan([
        (S.DOWNLOADING, _Stage(detik=300.0)),
        (S.TRANSCRIBING, _Stage(meledak=True)),
    ])
    assert "downloading 300s" in pesan


def test_pesan_menyarankan_menaikkan_batas(jalankan):
    """Tanpa ini orang tahu apa yang lambat tapi tidak tahu harus berbuat apa."""
    S = jalankan.Status
    pesan = jalankan([(S.DOWNLOADING, _Stage(meledak=True))])
    assert "JOB_TIMEOUT_SEC" in pesan


def test_gagal_sebelum_stage_pertama_tetap_bisa_dibaca(jalankan):
    """Rincian kosong tidak boleh menghasilkan kalimat menggantung."""
    S = jalankan.Status
    pesan = jalankan([(S.DOWNLOADING, _Stage(meledak=True))])
    assert "belum ada stage yang selesai" in pesan


def test_kegagalan_biasa_tidak_ikut_dibungkus(monkeypatch, tmp_path):
    """Hanya TimeoutError yang perlu rincian waktu. Error lain harus tetap
    membawa tipe dan pesannya sendiri, bukan tertutup teks soal batas waktu."""
    from db.models import Status
    from worker import orchestrator

    dicatat = {}
    monkeypatch.setattr(orchestrator.env_store, "reload", lambda: None)
    monkeypatch.setattr(orchestrator.jobs, "get", lambda j: {
        "url": "https://youtu.be/x", "target_clips": 3})
    monkeypatch.setattr(orchestrator.jobs, "update_status", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator.jobs, "fail",
                        lambda jid, err: dicatat.update(error=err))
    monkeypatch.setattr(orchestrator.settings, "WORK_DIR", tmp_path)

    class Rusak:
        def run(self, ctx):
            raise RuntimeError("Transkrip kosong")

    monkeypatch.setattr(orchestrator, "STAGES", [(Status.TRANSCRIBING, Rusak())])
    monkeypatch.setattr(orchestrator, "TOTAL_STEPS", 2)
    with pytest.raises(RuntimeError):
        orchestrator.run("00000000-0000-0000-0000-000000000002")

    assert "Transkrip kosong" in dicatat["error"]
    assert "JOB_TIMEOUT_SEC" not in dicatat["error"]
