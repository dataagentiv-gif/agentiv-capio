"""Rotasi berjenjang: tier model di atas rotasi key.

Aturannya: model terbaik dipakai TERUS di seluruh key, dan baru turun ke model
berikutnya setelah kuotanya habis di semua key. Kuota gratis Gemini dihitung
per key DAN per model, jadi "habis" dicatat per pasangan — satu key yang habis
tidak boleh menjatuhkan model itu untuk key lain.

Pulihnya tanpa penjadwalan: tanda habis diberi umur pendek, jadi tier teratas
dicoba ulang dengan sendirinya begitu umurnya lewat.
"""
import httpx
import pytest

from config.settings import settings
from llm import _engine, rute


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


class _PemakaiUji:
    """Peniru _Pemakai secukupnya: berjalan menuruti urutan pasangan."""

    def __init__(self, urut, keys=("k",)):
        self.urut, self.keys = urut, list(keys)
        self.idx, self.model = -1, ""
        self.ditandai = []

    def __call__(self, attempt):
        self.model, self.idx = self.urut[attempt % len(self.urut)]
        return self.keys[self.idx % len(self.keys)], self.model

    def tandai_habis(self):
        self.ditandai.append((self.model, self.idx))


OK = '{"segments": []}'
KUOTA = "You exceeded your current quota"


def _jalan(monkeypatch, balasan, urut, attempts=4, keys=1):
    """(model yang dipakai tiap percobaan, hasil, pemakai)."""
    dipakai = []
    berikut = iter(balasan)

    def palsu(url, headers=None, json=None, timeout=None):
        dipakai.append(json["model"])
        return next(berikut)

    monkeypatch.setattr(_engine.httpx, "post", palsu)
    monkeypatch.setattr(_engine.time, "sleep", lambda d: None)
    pemakai = _PemakaiUji(urut, keys=[f"k{i}" for i in range(keys)])
    try:
        hasil = _engine.call("p", None, endpoint="http://x", pemakai=pemakai,
                             use_schema=False, attempts=attempts, label="uji")
    except _engine.LLMError:
        hasil = None
    return dipakai, hasil, pemakai


# --- urutan pemakaian ---

def test_percobaan_pertama_memakai_tier_teratas(monkeypatch):
    dipakai, _, _ = _jalan(monkeypatch, [_Balasan(200, OK)],
                           [("a", 0), ("b", 0)])
    assert dipakai == ["a"]


def test_seluruh_key_dihabiskan_dulu_sebelum_turun_tier(monkeypatch):
    """Inti aturannya. Kalau tier turun sebelum key kedua dicoba, kuota key
    kedua untuk model TERBAIK tidak pernah terpakai — dan itu justru kuota
    yang paling berharga."""
    dipakai, _, _ = _jalan(monkeypatch, [_Balasan(429, KUOTA)] * 4,
                           [("a", 0), ("a", 1), ("b", 0), ("b", 1)],
                           attempts=4, keys=2)
    assert dipakai == ["a", "a", "b", "b"]


def test_turun_tier_saat_tier_teratas_penuh(monkeypatch):
    """503 'high demand' pada satu model tidak menjatuhkan job selama masih
    ada tier di bawahnya."""
    dipakai, hasil, _ = _jalan(
        monkeypatch, [_Balasan(503, "high demand"), _Balasan(200, OK)],
        [("a", 0), ("b", 0)])
    assert dipakai == ["a", "b"]
    assert hasil == {"segments": []}


# --- tanda habis ---

def test_kuota_habis_ditandai_supaya_job_berikutnya_tidak_mengulang(monkeypatch):
    _, _, pemakai = _jalan(monkeypatch, [_Balasan(429, KUOTA), _Balasan(200, OK)],
                           [("a", 0), ("b", 0)], attempts=2)
    assert pemakai.ditandai == [("a", 0)]


def test_rate_limit_sesaat_tidak_ditandai_habis(monkeypatch):
    """Rate limit pulih dalam hitungan detik. Menandainya sejam membuang tier
    teratas untuk masalah yang sudah beres sebelum job berikutnya mulai."""
    _, _, pemakai = _jalan(monkeypatch,
                           [_Balasan(429, "rate limit exceeded"), _Balasan(200, OK)],
                           [("a", 0), ("b", 0)], attempts=2)
    assert pemakai.ditandai == []


def test_kegagalan_selain_kuota_tidak_ditandai_habis(monkeypatch):
    _, _, pemakai = _jalan(monkeypatch,
                           [_Balasan(503, "high demand"), _Balasan(200, OK)],
                           [("a", 0), ("b", 0)], attempts=2)
    assert pemakai.ditandai == []


# --- penyusunan urutan ---

def test_urutan_menghabiskan_tier_teratas_dulu(monkeypatch):
    monkeypatch.setattr(rute, "_habis", lambda p, m, i: False)
    assert rute.urutan("gemini", ["a", "b"], 2) == [
        ("a", 0), ("a", 1), ("b", 0), ("b", 1)]


def test_pasangan_bertanda_habis_dipindah_ke_belakang(monkeypatch):
    monkeypatch.setattr(rute, "_habis", lambda p, m, i: m == "a")
    assert rute.urutan("gemini", ["a", "b"], 1) == [("b", 0), ("a", 0)]


def test_habis_dicatat_per_pasangan_bukan_per_model(monkeypatch):
    """Kuota dihitung per key DAN per model. Satu key yang habis tidak boleh
    menjatuhkan model itu untuk key lain."""
    monkeypatch.setattr(rute, "_habis", lambda p, m, i: m == "a" and i == 0)
    assert rute.urutan("gemini", ["a", "b"], 2)[0] == ("a", 1)


def test_semua_habis_tetap_menyisakan_sesuatu_untuk_dicoba(monkeypatch):
    """Tandanya cuma dugaan berumur sejam. Membuang semuanya berarti job gagal
    di sisi kita tanpa pernah bertanya ke server."""
    monkeypatch.setattr(rute, "_habis", lambda p, m, i: True)
    assert len(rute.urutan("gemini", ["a", "b"], 2)) == 4


def test_redis_mati_dianggap_semua_layak_dicoba(monkeypatch):
    """Salah menganggap habis menurunkan mutu tiap klip diam-diam; satu
    panggilan gagal jauh lebih murah daripada itu."""
    def meledak():
        raise RuntimeError("redis mati")

    monkeypatch.setattr(rute.keypool, "_redis", meledak)
    assert rute._habis("gemini", "a", 0) is False


# --- status untuk UI ---

def test_status_menyebut_model_yang_sedang_aktif(monkeypatch):
    """Turunnya tier tidak terlihat dari mana pun kalau tidak dilaporkan —
    klipnya tetap keluar, cuma dari model yang lebih rendah."""
    monkeypatch.setattr(rute, "_habis", lambda p, m, i: m == "a")
    s = rute.status("gemini", ["a", "b"], 1)
    assert s["aktif"] == "b"
    assert s["tier"][0]["siap"] is False
    assert s["tier"][1]["siap"] is True


# --- daftar yang berlaku ---

def test_tier_bawaan_dipakai_saat_env_kosong(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODELS", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "")
    assert rute.daftar() == rute.TIER


def test_tulisan_sendiri_menimpa_tier_bawaan(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODELS", "x, y")
    assert rute.daftar() == ["x", "y"]


def test_bawaan_lama_di_env_TIDAK_mematikan_tier(monkeypatch):
    """Nilai ini ada di hampir semua .env yang beredar karena .env.example dulu
    menulisnya — tanpa satu pun pemiliknya pernah memilihnya. Memperlakukannya
    sebagai pilihan sadar membuat seluruh sistem tier mati sejak lahir, dan
    matinya senyap: satu model itu memang jalan."""
    monkeypatch.setattr(settings, "GEMINI_MODELS", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", rute.BAWAAN_LAMA)
    assert rute.daftar() == rute.TIER


def test_model_satuan_yang_dipilih_sendiri_jadi_tier_teratas(monkeypatch):
    """Dihormati, tapi TIDAK menghapus cadangannya — kalau kuotanya habis, job
    tetap punya tempat turun."""
    monkeypatch.setattr(settings, "GEMINI_MODELS", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.7-flash")
    hasil = rute.daftar()
    assert hasil[0] == "gemini-3.7-flash"
    assert len(hasil) > 1
    assert hasil.count("gemini-3.7-flash") == 1


def test_tier_bawaan_hanya_berisi_model_yang_lolos_uji():
    """Daftar ini dipaku di kode justru supaya tidak ada yang menyelipkan model
    yang belum diuji. Yang ditolak punya alasan terukur: gemini-2.5-flash-lite
    mengembalikan 42 segmen saat diminta 7, kelas pro tidak punya jatah gratis,
    dan -preview dipensiunkan tanpa pemberitahuan."""
    assert rute.TIER
    for m in rute.TIER:
        assert "preview" not in m
        assert "pro" not in m
        assert m != "gemini-2.5-flash-lite"
    # Alias wajib ada di daftar: hanya ia yang tidak bisa ikut dipensiunkan,
    # jadi ia jaring terakhir kalau semua nama berversi ditutup Google.
    assert any(m.endswith("-latest") for m in rute.TIER)


def test_percobaan_cukup_untuk_menyentuh_tier_berikutnya(monkeypatch):
    """Menambah tier tanpa menambah jatah percobaan membuat tier terakhir tidak
    pernah kena giliran — fiturnya ada tapi tidak berjalan."""
    ditangkap = {}
    monkeypatch.setattr(_engine, "call", lambda *a, **k: ditangkap.update(k))
    monkeypatch.setattr(_engine.keypool, "keys", lambda p: ["k1"])
    monkeypatch.setattr(_engine.rute, "urutan",
                        lambda pool, m, n: [(x, 0) for x in m])
    _engine.call_pool("p", None, pool="gemini", nama="Gemini",
                      endpoint="http://x", models=["a", "b", "c", "d"],
                      use_schema=False, attempts=3)
    assert ditangkap["attempts"] >= 4


def test_tanpa_key_ditolak_sebelum_memanggil_apa_pun(monkeypatch):
    monkeypatch.setattr(_engine.keypool, "keys", lambda p: [])
    monkeypatch.setattr(_engine.httpx, "post",
                        lambda *a, **k: pytest.fail("tidak boleh memanggil API"))
    with pytest.raises(_engine.LLMError) as e:
        _engine.call_pool("p", None, pool="gemini", nama="Gemini",
                          endpoint="http://x", models=["a"], use_schema=False)
    assert "Setting" in str(e.value)
