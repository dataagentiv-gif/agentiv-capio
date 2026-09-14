"""Rotasi key Gemini dan penanganan balasan LLM.

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

def test_pemakai_mengambil_pasangan_sesuai_urutan(keys):
    """Sejak rotasi jadi berjenjang, urutan (key, model) diputuskan
    llm/rute.py — bukan penghitung putar di keypool. Yang diuji di sini
    sambungannya: _Pemakai benar-benar menuruti urutan itu dan mengingat
    indeksnya supaya hasilnya bisa dilaporkan balik ke panel status."""
    from llm._engine import _Pemakai

    keys("a,b,c")
    pemakai = _Pemakai("gemini", ["a", "b", "c"], [("m1", 1), ("m2", 2)])
    assert pemakai(0) == ("b", "m1")
    assert pemakai.idx == 1
    assert pemakai(1) == ("c", "m2")
    assert pemakai.idx == 2


def test_key_kosong_ditolak_dengan_pesan_jelas(keys):
    """Menyebut nama providernya, bukan pesan generik — orang perlu tahu key
    MANA yang kurang."""
    keys("")
    with pytest.raises(LLMError, match="Gemini API key kosong"):
        call_llm("halo")


def test_env_lama_berisi_provider_yang_dibuang_tetap_bisa_dimuat(tmp_path):
    """Groq dan OpenRouter sudah dibuang, tapi .env milik client lama masih
    memuat barisnya. Satu baris yang tidak terbaca membuat SELURUH konfigurasi
    gagal dimuat — dan aplikasinya tidak bisa start sama sekali."""
    from config.settings import Settings

    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openrouter\nOPENROUTER_API_KEYS=or\n"
                   "OPENROUTER_MODEL=x\nGROQ_API_KEYS=gsk\nGROQ_API_KEY=gsk\n",
                   encoding="utf-8")
    Settings(_env_file=env)


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
