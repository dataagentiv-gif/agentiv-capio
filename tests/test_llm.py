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

def test_key_berputar_x_plus_1(keys):
    from llm.client_gemini import _next_key

    keys("a,b,c")
    urutan = [_next_key() for _ in range(6)]
    # Penghitungnya global dan bisa mulai dari posisi mana saja, jadi yang
    # diuji adalah polanya: maju satu tiap panggilan, dan berulang tiap 3.
    assert urutan[3:] == urutan[:3]
    assert set(urutan) == {"a", "b", "c"}
    assert urutan[0] != urutan[1] != urutan[2]


def test_satu_key_selalu_mengembalikan_key_itu(keys):
    from llm.client_gemini import _next_key

    keys("tunggal")
    assert [_next_key() for _ in range(3)] == ["tunggal"] * 3


def test_key_kosong_ditolak_dengan_pesan_jelas(keys):
    from llm.client_gemini import _next_key

    keys("")
    with pytest.raises(LLMError, match="GEMINI_API_KEYS"):
        _next_key()


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
    with pytest.raises(LLMError, match="GEMINI_API_KEYS"):
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

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-key")
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
