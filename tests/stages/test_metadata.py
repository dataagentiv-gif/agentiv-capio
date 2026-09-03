"""Stage 8 tidak boleh menjatuhkan job, apa pun yang dibalas LLM.

Klip videonya sendiri sudah jadi dan tetap berguna tanpa judul yang bagus, jadi
kegagalan di sini turun jadi fallback — job tetap `done` (PRD Bagian 3). Itu
keputusan yang benar, tapi juga berarti stage ini penuh jalur yang lewat tanpa
suara: LLM yang membalas separuh, salah id, atau judul kosong semuanya diam-diam
berubah jadi judul cadangan. Kalau salah satunya rusak, tidak ada yang gagal —
hasilnya cuma jadi lebih buruk.
"""
import pytest

from pipeline.stages import metadata


def seg(i: str, hook: str = "Ini kalimat pembuka klip"):
    return {"id": i, "hook": hook, "reason": "alasan"}


@pytest.fixture
def jalankan(tmp_path, monkeypatch):
    """Jalankan stage dengan balasan LLM yang ditentukan test."""
    def _run(balasan, segments=None):
        if isinstance(balasan, Exception):
            def fake(*a, **k):
                raise balasan
        else:
            def fake(*a, **k):
                return balasan
        monkeypatch.setattr(metadata, "call_llm", fake)
        ctx = {"segments_final": segments or [seg("c1"), seg("c2")],
               "workdir": tmp_path}
        return metadata.run(ctx)["metadata"]
    return _run


# --- jalur normal ---

def test_balasan_lengkap_dipakai_apa_adanya(jalankan):
    out = jalankan({"clips": [
        {"id": "c1", "title": "Judul Satu", "caption": "Cap satu", "hashtags": ["a"]},
        {"id": "c2", "title": "Judul Dua", "caption": "Cap dua", "hashtags": ["b"]},
    ]})
    assert out["c1"]["title"] == "Judul Satu"
    assert out["c2"]["caption"] == "Cap dua"


def test_hasil_ditulis_ke_workdir(jalankan, tmp_path):
    jalankan({"clips": [{"id": "c1", "title": "T", "caption": "", "hashtags": []}]})
    assert (tmp_path / "metadata.json").exists()


# --- LLM gagal total ---

def test_llm_meledak_semua_klip_pakai_fallback(jalankan):
    """Job harus tetap selesai: video-nya sudah jadi."""
    out = jalankan(RuntimeError("provider mati"))
    assert set(out) == {"c1", "c2"}
    assert out["c1"]["title"] == "Ini kalimat pembuka klip"
    assert out["c1"]["caption"] == ""
    assert out["c1"]["hashtags"] == []


def test_fallback_memotong_hook_panjang_jadi_judul(jalankan):
    panjang = "kata " * 40
    out = jalankan(RuntimeError("x"), [seg("c1", panjang)])
    assert len(out["c1"]["title"]) <= 60


def test_fallback_tanpa_hook_memakai_id(jalankan):
    """Judul kosong di UI tidak memberi tahu klip mana yang mana."""
    out = jalankan(RuntimeError("x"), [seg("c1", "")])
    assert out["c1"]["title"] == "c1"


# --- balasan yang tidak utuh ---

def test_klip_yang_tidak_dibalas_jatuh_ke_fallback(jalankan):
    """LLM sering membalas lebih sedikit dari yang diminta."""
    out = jalankan({"clips": [
        {"id": "c1", "title": "Ada", "caption": "c", "hashtags": []},
    ]})
    assert out["c1"]["title"] == "Ada"
    assert out["c2"]["title"] == "Ini kalimat pembuka klip"


def test_id_yang_tidak_dikenal_diabaikan(jalankan):
    """Id karangan tidak boleh menimpa klip mana pun."""
    out = jalankan({"clips": [
        {"id": "c99", "title": "Nyasar", "caption": "", "hashtags": []},
    ]})
    assert "c99" not in out
    assert out["c1"]["title"] == "Ini kalimat pembuka klip"


def test_judul_kosong_dianggap_gagal(jalankan):
    """Judul kosong lebih buruk daripada hook mentah — di UI klipnya jadi
    tidak bisa dibedakan dari yang lain."""
    out = jalankan({"clips": [
        {"id": "c1", "title": "   ", "caption": "ada", "hashtags": ["x"]},
    ]})
    assert out["c1"]["title"] == "Ini kalimat pembuka klip"


def test_balasan_berbentuk_list_tanpa_pembungkus(jalankan):
    """Sebagian model membalas array telanjang walau schema meminta objek."""
    out = jalankan([{"id": "c1", "title": "Langsung", "caption": "", "hashtags": []}])
    assert out["c1"]["title"] == "Langsung"


def test_entri_bukan_objek_dilewati(jalankan):
    out = jalankan({"clips": ["bukan objek", None,
                              {"id": "c1", "title": "Sah", "caption": "", "hashtags": []}]})
    assert out["c1"]["title"] == "Sah"


# --- pembersihan nilai ---

def test_hashtag_dibersihkan(jalankan):
    """Tanda pagar ganda dan huruf besar bikin tag tidak konsisten saat
    diposting."""
    out = jalankan({"clips": [
        {"id": "c1", "title": "T", "caption": "",
         "hashtags": ["#Bisnis", "  UMKM  ", "", "Startup"]},
    ]})
    assert out["c1"]["hashtags"] == ["bisnis", "umkm", "startup"]


def test_hashtag_dibatasi_enam(jalankan):
    out = jalankan({"clips": [
        {"id": "c1", "title": "T", "caption": "",
         "hashtags": [f"t{i}" for i in range(20)]},
    ]})
    assert len(out["c1"]["hashtags"]) == 6


def test_judul_kepanjangan_dipotong(jalankan):
    out = jalankan({"clips": [
        {"id": "c1", "title": "x" * 500, "caption": "", "hashtags": []},
    ]})
    assert len(out["c1"]["title"]) == 100


def test_hashtags_bukan_list_tidak_bikin_crash(jalankan):
    out = jalankan({"clips": [
        {"id": "c1", "title": "T", "caption": "", "hashtags": None},
    ]})
    assert out["c1"]["hashtags"] == []


def test_semua_segmen_selalu_dapat_entri(jalankan):
    """Kontrak ke _build_clips: ctx["metadata"][seg["id"]] diakses langsung,
    jadi id yang bolong akan jadi KeyError setelah render selesai — belasan
    menit kerja terbuang di langkah terakhir."""
    out = jalankan({"clips": []}, [seg(f"c{i}") for i in range(1, 6)])
    assert set(out) == {"c1", "c2", "c3", "c4", "c5"}
