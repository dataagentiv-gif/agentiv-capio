"""Pemilihan provider dan rotasi key Gemini.

Rotasi tidak punya gejala yang kelihatan saat rusak: kalau key selalu jatuh ke
indeks yang sama, semuanya tetap jalan sampai key pertama kehabisan kuota, lalu
seluruh job gagal berbarengan tanpa sebab yang jelas.
"""
import pytest

from config.settings import settings
from llm import call_llm
from llm._engine import LLMError, _extract_json


@pytest.fixture
def keys(monkeypatch):
    def _set(value: str):
        monkeypatch.setattr(settings, "GEMINI_API_KEYS", value)
    return _set


# --- parsing GEMINI_API_KEYS ---

def test_key_dipisah_koma(keys):
    keys("k1,k2,k3")
    assert settings.gemini_keys == ["k1", "k2", "k3"]


def test_spasi_dan_koma_sisa_copy_paste_dibuang(keys):
    """`key1, key2,` adalah bentuk yang wajar keluar dari copy-paste."""
    keys(" k1 , k2 ,, ")
    assert settings.gemini_keys == ["k1", "k2"]


def test_satu_key_tanpa_koma_tetap_valid(keys):
    keys("cuma-satu")
    assert settings.gemini_keys == ["cuma-satu"]


def test_kosong_menghasilkan_list_kosong(keys):
    keys("")
    assert settings.gemini_keys == []


# --- rotasi ---
#
# Mekanisme rotasinya sendiri diuji di tests/test_keypool.py. Di sini yang
# diuji adalah sambungannya: client Gemini benar-benar memakai keypool, dan
# indeks yang diambil dilaporkan balik supaya panel status terisi.

def test_client_mengambil_key_lewat_keypool(keys, monkeypatch):
    import keypool
    from llm._engine import _Pemakai

    keys("a,b,c")
    monkeypatch.setattr(keypool, "ambil", lambda pool: (1, "b"))
    pemakai = _Pemakai("gemini", "gemini")
    assert pemakai() == "b"
    assert pemakai.idx == 1


@pytest.mark.parametrize("pool,nama,field", [
    ("gemini", "Gemini", "GEMINI_API_KEYS"),
    ("openrouter", "OpenRouter", "OPENROUTER_API_KEYS"),
])
def test_key_kosong_ditolak_dengan_pesan_jelas(monkeypatch, pool, nama, field):
    """Kedua provider LLM harus menyebut namanya sendiri, bukan pesan generik —
    orang perlu tahu key MANA yang kurang."""
    from llm._engine import call_pool

    monkeypatch.setattr(settings, field, "")
    if pool == "openrouter":
        monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(LLMError, match=f"{nama} API key kosong"):
        call_pool("halo", None, pool=pool, nama=nama,
                  endpoint="http://x", model="m", use_schema=False)


def test_rotasi_dipakai_kedua_provider_llm(monkeypatch):
    """Regresi: rotasi sempat cuma ada di Gemini. Menambah provider tanpa
    rotasi berarti key keduanya tidak pernah terpakai."""
    import httpx

    import keypool
    from llm import client_gemini, client_openrouter

    for field in ("GEMINI_API_KEYS", "OPENROUTER_API_KEYS"):
        monkeypatch.setattr(settings, field, "k1,k2")
    dipakai = []
    monkeypatch.setattr(keypool, "ambil", lambda p: (dipakai.append(p) or (0, "k1")))
    monkeypatch.setattr(keypool, "lapor", lambda *a, **k: None)
    monkeypatch.setattr(httpx, "post", _fake_post({}))

    client_gemini.call_llm("halo")
    client_openrouter.call_llm("halo")
    assert dipakai == ["gemini", "openrouter"]


# --- pemilihan provider ---

def test_provider_tidak_dikenal_ditolak(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    with pytest.raises(LLMError, match="tidak dikenal"):
        call_llm("halo")


@pytest.mark.parametrize("nama", ["gemini", "GEMINI", " Gemini "])
def test_nama_provider_tidak_peduli_huruf_besar_kecil(monkeypatch, keys, nama):
    monkeypatch.setattr(settings, "LLM_PROVIDER", nama)
    keys("")
    # Sampai ke client Gemini (gagal karena key kosong), bukan ditolak dispatcher.
    with pytest.raises(LLMError, match="Gemini API key"):
        call_llm("halo")


# --- badan request ---

def _fake_post(capture, content='{"ok": 1}'):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": content}}]}
    def post(url, headers=None, json=None, timeout=None):
        capture.update(url=url, headers=headers, body=json)
        return R()
    return post


def test_gemini_kirim_json_object_bukan_json_schema(monkeypatch, keys):
    """Layer OpenAI-compatible Gemini belum dipastikan menerima json_schema."""
    import httpx

    from llm import client_gemini

    keys("k1")
    cap = {}
    monkeypatch.setattr(httpx, "post", _fake_post(cap))
    client_gemini.call_llm("halo", {"type": "object"})
    assert cap["body"]["response_format"] == {"type": "json_object"}
    assert "generativelanguage.googleapis.com" in cap["url"]
    assert cap["headers"]["Authorization"] == "Bearer k1"


def test_openrouter_kirim_json_schema(monkeypatch):
    import httpx

    from llm import client_openrouter

    monkeypatch.setattr(settings, "OPENROUTER_API_KEYS", "or-key")
    cap = {}
    monkeypatch.setattr(httpx, "post", _fake_post(cap))
    client_openrouter.call_llm("halo", {"type": "object"})
    assert cap["body"]["response_format"]["type"] == "json_schema"
    assert "openrouter.ai" in cap["url"]


def test_tanpa_schema_tidak_ada_response_format(monkeypatch, keys):
    import httpx

    from llm import client_gemini

    keys("k1")
    cap = {}
    monkeypatch.setattr(httpx, "post", _fake_post(cap))
    client_gemini.call_llm("halo")
    assert "response_format" not in cap["body"]


# --- parsing balasan ---

def test_json_dalam_code_fence_tetap_terbaca():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_dengan_kalimat_pengantar_tetap_terbaca():
    assert _extract_json('Tentu, ini hasilnya:\n[{"a": 1}]') == [{"a": 1}]


def test_bukan_json_sama_sekali_melempar_error():
    import json

    with pytest.raises(json.JSONDecodeError):
        _extract_json("maaf saya tidak bisa membantu")


# --- jeda pada gangguan sementara ---
#
# Terukur di uji beban: tanpa jeda, tiga percobaan terhadap Gemini yang sedang
# 503 habis dalam 4 DETIK dan seluruh job gagal — padahal gangguan seperti itu
# biasanya berlangsung lebih lama.

def test_503_ditunggu_sebelum_dicoba_lagi(monkeypatch, keys):
    import httpx

    from llm import _engine, client_gemini

    keys("k1,k2")
    tidur = []
    monkeypatch.setattr(_engine.time, "sleep", lambda d: tidur.append(d))

    panggilan = []

    class R503:
        status_code = 503
        text = "overloaded"
        def raise_for_status(self):
            raise httpx.HTTPStatusError("503", request=None, response=self)

    def post(url, headers=None, json=None, timeout=None):
        panggilan.append(1)
        return R503()

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(_engine.LLMError):
        client_gemini.call_llm("halo")

    assert len(panggilan) >= 3, "harus mencoba ulang"
    assert tidur, "tidak ada jeda sama sekali di antara percobaan"
    assert tidur == sorted(tidur), "jeda harus makin panjang, bukan tetap"


# --- kuota habis vs rate limit sesaat ---
#
# Dua-duanya HTTP 429, tapi tindakannya berlawanan. Terjadi sungguhan di uji
# beban: dua key free tier kehabisan kuota harian dan job pulang membawa pesan
# "HTTP 429" — yang tidak memberitahu apakah harus menunggu semenit, menambah
# key, atau membayar.

KUOTA = ('{"error":{"code":429,"message":"You exceeded your current quota, '
         'please check your plan and billing details."}}')


def _r429(badan):
    import httpx

    class R:
        status_code = 429
        text = badan
        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=self)
    return R


def _jalankan_429(monkeypatch, badan):
    import httpx

    from llm import _engine, client_gemini

    tidur = []
    monkeypatch.setattr(_engine.time, "sleep", lambda d: tidur.append(d))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _r429(badan)())
    with pytest.raises(_engine.LLMError) as exc:
        client_gemini.call_llm("halo")
    return str(exc.value), tidur


def test_kuota_habis_menyebut_tindakan_yang_benar(monkeypatch, keys):
    keys("k1,k2")
    pesan, _ = _jalankan_429(monkeypatch, KUOTA)
    assert "kuota" in pesan.lower()
    assert "tambah key" in pesan.lower()


def test_kuota_habis_tidak_ditunggu(monkeypatch, keys):
    """Kuota harian tidak pulih dalam hitungan detik, dan semua key sudah
    dicoba — menunggu cuma menahan job semenit sebelum gagal dengan cara sama."""
    keys("k1,k2")
    _, tidur = _jalankan_429(monkeypatch, KUOTA)
    assert tidur == []


def test_rate_limit_sesaat_tetap_ditunggu(monkeypatch, keys):
    """429 biasa justru penyebab utama JEDA ada — jangan ikut dimatikan."""
    keys("k1,k2")
    pesan, tidur = _jalankan_429(monkeypatch, '{"error":{"message":"rate limit"}}')
    assert tidur, "429 sesaat harus tetap dijeda"
    assert "kuota" not in pesan.lower()


def test_key_ditolak_disebut_apa_adanya():
    from llm._engine import _pesan

    assert "key ditolak" in _pesan(401, "invalid api key").lower()


def test_json_rusak_tidak_perlu_ditunggu(monkeypatch, keys):
    """Kegagalan ini soal ISI balasan, bukan kondisi server — menunda tidak
    menambah peluang berhasil, cuma memperlambat."""
    import httpx

    from llm import _engine, client_gemini

    keys("k1")
    tidur = []
    monkeypatch.setattr(_engine.time, "sleep", lambda d: tidur.append(d))
    monkeypatch.setattr(httpx, "post", _fake_post({}, content="bukan json sama sekali"))

    with pytest.raises(_engine.LLMError):
        client_gemini.call_llm("halo")
    assert tidur == []
