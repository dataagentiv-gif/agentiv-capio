"""Rotasi model, sumbu kedua di samping rotasi key.

Kuota gratis Gemini dihitung per key DAN per model — terbukti saat kuota yang
habis pulih seketika hanya dengan berpindah model, tanpa menunggu reset harian.
Jadi memutar keduanya mengalikan atapnya, bukan sekadar menggeser beban.

Sumbu kedua ini juga menyelamatkan kasus yang terlihat saat menguji kandidat
model: gemini-flash-latest dan gemini-3.8-flash dua-duanya menjawab 503
"experiencing high demand" pada SETIAP percobaan hari itu. Dengan satu model,
itu job yang gagal.
"""
import httpx
import pytest

from config.settings import settings
from llm import _engine


class _Balasan:
    """Balasan httpx palsu secukupnya untuk _engine.call."""

    def __init__(self, code, isi=""):
        self.status_code = code
        self.text = isi
        self._isi = isi

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("gagal", request=None, response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._isi}}]}


def _panggil(monkeypatch, balasan, models, attempts=4):
    """Jalankan _engine.call dan kembalikan daftar model yang benar-benar dipakai."""
    dipakai = []
    urut = iter(balasan)

    def palsu(url, headers=None, json=None, timeout=None):
        dipakai.append(json["model"])
        return next(urut)

    monkeypatch.setattr(_engine.httpx, "post", palsu)
    monkeypatch.setattr(_engine.time, "sleep", lambda d: None)
    try:
        hasil = _engine.call(
            "p", None, endpoint="http://x", get_key=lambda: "k",
            models=models, use_schema=False, attempts=attempts, label="uji",
        )
    except _engine.LLMError:
        hasil = None
    return dipakai, hasil


OK = '{"segments": []}'


def test_percobaan_pertama_memakai_model_teratas(monkeypatch):
    """Daftarnya urut menurut preferensi, jadi jalur normal harus selalu
    memakai yang terbaik — cadangan benar-benar cuma cadangan."""
    dipakai, _ = _panggil(monkeypatch, [_Balasan(200, OK)], ["a", "b", "c"])
    assert dipakai == ["a"]


def test_model_berikutnya_dipakai_saat_yang_pertama_penuh(monkeypatch):
    """503 'high demand' pada satu model tidak boleh menjatuhkan job selama
    masih ada model lain yang bisa dicoba."""
    dipakai, hasil = _panggil(
        monkeypatch, [_Balasan(503, "high demand"), _Balasan(200, OK)], ["a", "b"])
    assert dipakai == ["a", "b"]
    assert hasil == {"segments": []}


def test_model_berikutnya_dipakai_saat_kuota_habis(monkeypatch):
    """Inti fiturnya: kuota dihitung per model, jadi model berikutnya punya
    jatahnya sendiri dan tidak ikut habis."""
    dipakai, hasil = _panggil(
        monkeypatch,
        [_Balasan(429, "You exceeded your current quota"), _Balasan(200, OK)],
        ["a", "b"],
    )
    assert dipakai == ["a", "b"]
    assert hasil is not None


def test_model_berputar_bukan_berhenti_di_yang_terakhir(monkeypatch):
    dipakai, _ = _panggil(
        monkeypatch, [_Balasan(503, "x")] * 3 + [_Balasan(200, OK)], ["a", "b"],
        attempts=4)
    assert dipakai == ["a", "b", "a", "b"]


def test_satu_model_tetap_jalan_seperti_sebelumnya(monkeypatch):
    """Tidak boleh ada yang berubah untuk pemasangan yang cuma punya satu
    model — itu keadaan bawaan dan mayoritas pemakaian."""
    dipakai, hasil = _panggil(monkeypatch, [_Balasan(200, OK)], ["a"])
    assert dipakai == ["a"] and hasil is not None


def test_daftar_model_kosong_ditolak_dengan_pesan_yang_menyebut_tempatnya(monkeypatch):
    monkeypatch.setattr(_engine.httpx, "post", lambda *a, **k: pytest.fail("tidak boleh memanggil API"))
    with pytest.raises(_engine.LLMError) as e:
        _engine.call("p", None, endpoint="http://x", get_key=lambda: "k",
                     models=[], use_schema=False, label="uji")
    assert "Setting" in str(e.value)


# --- pembacaan setelan ---

def test_bentuk_jamak_menang_atas_bentuk_tunggal(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODELS", "a, b ,c")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "lama")
    assert settings.gemini_models == ["a", "b", "c"]


def test_env_lama_tanpa_bentuk_jamak_tetap_jalan(monkeypatch):
    """.env milik orang yang sudah memasang versi sebelumnya tidak boleh perlu
    disunting supaya jalan lagi."""
    monkeypatch.setattr(settings, "GEMINI_MODELS", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest")
    assert settings.gemini_models == ["gemini-flash-lite-latest"]


def test_koma_sisa_tidak_menghasilkan_model_kosong(monkeypatch):
    """"a,b," dari copy-paste tidak boleh mengirim nama model kosong ke API."""
    monkeypatch.setattr(settings, "GEMINI_MODELS", "a, ,b,")
    assert settings.gemini_models == ["a", "b"]


def test_percobaan_cukup_untuk_menyentuh_tiap_model(monkeypatch):
    """Menambah model tanpa menambah jatah percobaan membuat model terakhir
    tidak pernah kena giliran — fiturnya ada di setelan tapi tidak berjalan."""
    ditangkap = {}
    monkeypatch.setattr(_engine, "call", lambda *a, **k: ditangkap.update(k))
    monkeypatch.setattr(_engine.keypool, "keys", lambda p: ["k1"])
    _engine.call_pool("p", None, pool="gemini", nama="Gemini",
                      endpoint="http://x", models=["a", "b", "c", "d"],
                      use_schema=False, attempts=3)
    assert ditangkap["attempts"] >= 4
