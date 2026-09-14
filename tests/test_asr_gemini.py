"""Kontrak REST Gemini Transcribe dan perbaikan ucapan yang dibuang model.

Jaringan tidak pernah disentuh. ffmpeg disentuh sekali, di test perakitan
audio gabungan: salah hitung offset di sana tetap exit 0, dan hasilnya caption
yang menyala di detik yang salah.
"""
import subprocess

import pytest

from api import checks
from asr import client_gemini as gemini


class Resp:
    def __init__(self, code=200, data=None, headers=None, text=""):
        self.status_code = code
        self._data = data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._data


def hasil_kata(teks="Halo", start="0.100s", end="0.450s"):
    return {
        "steps": [{
            "content": [{
                "annotations": [{
                    "type": "word_info", "text": teks,
                    "start_offset": start, "end_offset": end,
                }]
            }]
        }]
    }


def kata(w, s, e):
    return {"w": w, "s": s, "e": e}


PER_MENIT = ("You exceeded your current quota, please check your plan and billing "
             "details. * Quota exceeded for metric: generativelanguage.googleapis.com/"
             "generate_content_free_tier_requests, limit: 3, model: gemini-3.5-transcribe "
             "Please retry in 29.28898727s.")
TOKEN = ("You exceeded your current quota. * Quota exceeded for metric: "
         "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, "
         "limit: 10000, model: gemini-3.5-transcribe Please retry in 12.5s.")
HARIAN = ("You exceeded your current quota. * Quota exceeded for metric: "
          "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
          "limit: 25, model: gemini-3.5-transcribe Please retry in 7.48s.")


def pasang_http(monkeypatch, hasil=None, interaksi=None, delete_error=None):
    """interaksi: daftar Resp untuk POST /interactions berturut-turut."""
    panggilan, dihapus = [], []
    antre = list(interaksi or [])

    def post(url, **kwargs):
        panggilan.append((url, kwargs))
        if url.endswith("/upload/v1beta/files"):
            return Resp(headers={"x-goog-upload-url": "https://upload.test/file"})
        if url == "https://upload.test/file":
            return Resp(data={"file": {
                "name": "files/test", "uri": "https://file.test/audio"
            }})
        return antre.pop(0) if antre else Resp(200, hasil or hasil_kata())

    def delete(url, **kwargs):
        dihapus.append(url)
        if delete_error:
            raise delete_error
        return Resp()

    monkeypatch.setattr(gemini.httpx, "post", post)
    monkeypatch.setattr(gemini.httpx, "get", lambda *a, **k: Resp(data={"state": "ACTIVE"}))
    monkeypatch.setattr(gemini.httpx, "delete", delete)
    monkeypatch.setattr(gemini.time, "sleep", lambda _: None)
    # Seluruh audio hening -> tidak ada celah bersuara -> pass perbaikan tidak jalan.
    monkeypatch.setattr(gemini, "_hening", lambda p: (60.0, [(0.0, 60.0)]))
    return panggilan, dihapus


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "audio.ogg"
    p.write_bytes(b"audio")
    return p


# --- parser ---

def test_parser_timestamp_dan_offset():
    out = gemini._annotations(hasil_kata(), 1200.0)
    assert out == [{"w": "Halo", "s": 1200.1, "e": 1200.45}]


def test_parser_menerima_offset_angka():
    out = gemini._annotations(hasil_kata(start=1.25, end=1.75), 0)
    assert out[0]["s"] == 1.25 and out[0]["e"] == 1.75


def test_parser_mengurutkan_kata():
    """Anotasi Gemini tidak selalu urut waktu; deteksi celah butuh urutan."""
    data = hasil_kata("b", "2s", "3s")
    data["steps"][0]["content"][0]["annotations"].append(
        hasil_kata("a", "0s", "1s")["steps"][0]["content"][0]["annotations"][0])
    assert [w["w"] for w in gemini._annotations(data, 0)] == ["a", "b"]


def test_respons_tanpa_timestamp_kata_ditolak(audio, monkeypatch):
    pasang_http(monkeypatch, hasil={"steps": []})
    with pytest.raises(RuntimeError, match="tidak mengembalikan timestamp kata"):
        gemini._panggil("key", audio, 0)


# --- upload & cleanup ---

def test_upload_transcribe_dan_cleanup(audio, monkeypatch):
    panggilan, dihapus = pasang_http(monkeypatch)

    words, sentences = gemini._panggil("key", audio, 10.0)

    assert words[0] == {"w": "Halo", "s": 10.1, "e": 10.45}
    assert sentences[0]["text"] == "Halo"
    assert panggilan[2][1]["json"]["generation_config"]["transcription_config"]["mode"] == {
        "type": "verbatim", "timestamp_granularities": ["word"]
    }
    assert dihapus == [f"{gemini.BASE}/v1beta/files/test"]


def test_file_remote_dihapus_saat_transkripsi_gagal(audio, monkeypatch):
    _, dihapus = pasang_http(monkeypatch, interaksi=[Resp(500, text="gagal")])
    with pytest.raises(RuntimeError, match="HTTP 500"):
        gemini._panggil("key", audio, 0)
    assert dihapus == [f"{gemini.BASE}/v1beta/files/test"]


def test_cleanup_gagal_tidak_membuang_hasil(audio, monkeypatch):
    pasang_http(monkeypatch, delete_error=OSError("putus"))
    words, _ = gemini._panggil("key", audio, 0)
    assert words[0]["w"] == "Halo"


# --- 429: yang ditunggu vs yang dilewati ---

def test_429_per_menit_ditunggu_sesuai_permintaan_server():
    assert gemini._jeda_429(PER_MENIT) == pytest.approx(30.29, abs=0.01)


def test_429_token_per_menit_ditunggu():
    assert gemini._jeda_429(TOKEN) == pytest.approx(13.5)


def test_429_harian_tidak_ditunggu_walau_server_bilang_retry_in_7s():
    """Kalau ini dianggap per menit, job menunggu sia-sia lalu gagal juga."""
    assert gemini._jeda_429(HARIAN) is None


def test_429_per_menit_lalu_berhasil(audio, monkeypatch):
    tidur = []
    pasang_http(monkeypatch, interaksi=[Resp(429, text=PER_MENIT), Resp(200, hasil_kata())])
    monkeypatch.setattr(gemini.time, "sleep", tidur.append)
    assert gemini._minta("key", audio)[0]["w"] == "Halo"
    assert len(tidur) == 1


def test_429_harian_langsung_menyerah_dan_file_dihapus(audio, monkeypatch):
    _, dihapus = pasang_http(monkeypatch, interaksi=[Resp(429, text=HARIAN)])
    with pytest.raises(gemini.KuotaHabis, match="quota_exceeded"):
        gemini._minta("key", audio)
    assert dihapus == [f"{gemini.BASE}/v1beta/files/test"]


def test_rate_limit_yang_tidak_pulih_tidak_ditunggu_selamanya(audio, monkeypatch):
    pasang_http(monkeypatch, interaksi=[Resp(429, text=PER_MENIT)] * 20)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        gemini._minta("key", audio)


def test_perbaikan_pindah_key_saat_kuota_harian_habis(audio, monkeypatch):
    dipakai = []

    def minta(key, path):
        dipakai.append(key)
        if key != "k3":
            raise gemini.KuotaHabis("habis")
        return [kata("ok", 0, 1)]

    monkeypatch.setattr(gemini, "_minta", minta)
    monkeypatch.setattr(gemini.keypool, "keys", lambda pool: ["k1", "k2", "k3"])
    assert gemini._minta_cadangan("k1", audio)[0]["w"] == "ok"
    assert dipakai == ["k1", "k2", "k3"]


def test_retry_memakai_key_berikutnya(audio, monkeypatch):
    keys = iter([(0, "k1"), (1, "k2"), (2, "k3")])
    dipakai, laporan = [], []

    monkeypatch.setattr(gemini.keypool, "ambil", lambda pool: next(keys))
    monkeypatch.setattr(gemini.keypool, "lapor", lambda *a: laporan.append(a))
    monkeypatch.setattr("utils.retry.time.sleep", lambda _: None)

    def panggil(key, path, offset):
        dipakai.append(key)
        if key != "k3":
            raise RuntimeError("sementara")
        return ([{"w": "ok", "s": 0.0, "e": 0.1}], [])

    monkeypatch.setattr(gemini, "_panggil", panggil)
    words, _ = gemini.transcribe(audio, 0)

    assert dipakai == ["k1", "k2", "k3"]
    assert words[0]["w"] == "ok"
    assert [x[2] for x in laporan] == [False, False, True]


# --- deteksi celah bersuara ---

def test_celah_bersuara_jadi_lubang():
    words = [kata("a", 0, 1), kata("b", 5, 6)]
    hening = [(1.0, 2.0)]                     # 1 dari 4 detik celah hening
    assert gemini._lubang(words, 6.0, hening) == [{"a": 1, "b": 5, "ucapan": 3.0}]


def test_celah_hening_bukan_lubang():
    words = [kata("a", 0, 1), kata("b", 5, 6)]
    assert gemini._lubang(words, 6.0, [(1.0, 5.0)]) == []


def test_jeda_napas_bukan_lubang():
    words = [kata("a", 0, 1), kata("b", 1.6, 2)]
    assert gemini._lubang(words, 2.0, []) == []


def test_ujung_video_ikut_diperiksa():
    """Pembukaan video bisa berupa ucapan yang dibuang, bukan musik intro."""
    words = [kata("a", 4, 5)]
    assert gemini._lubang(words, 9.0, []) == [
        {"a": 0.0, "b": 4, "ucapan": 4.0}, {"a": 5, "b": 9.0, "ucapan": 4.0},
    ]


def test_kata_tumpang_tindih_tidak_membuat_lubang_palsu():
    words = [kata("a", 0, 5), kata("b", 1, 2), kata("c", 5.5, 6)]
    assert gemini._lubang(words, 6.0, []) == []


# --- pemetaan waktu audio gabungan ---

def test_kata_dikembalikan_ke_waktu_aslinya():
    tabel = [{"a": 10.0, "b": 12.0, "ca": 0.0, "cb": 2.0},
             {"a": 30.0, "b": 31.0, "ca": 3.0, "cb": 4.0}]
    per = gemini._petakan([kata("x", 0.5, 1.0), kata("y", 3.2, 3.6)], tabel)
    assert per == [[{"w": "x", "s": 10.5, "e": 11.0}], [{"w": "y", "s": 30.2, "e": 30.6}]]


def test_kata_di_jeda_pemisah_dijepit_ke_potongannya():
    tabel = [{"a": 10.0, "b": 12.0, "ca": 0.0, "cb": 2.0},
             {"a": 30.0, "b": 31.0, "ca": 3.0, "cb": 4.0}]
    per = gemini._petakan([kata("ekor", 1.9, 2.3)], tabel)
    assert per[0] == [{"w": "ekor", "s": 11.9, "e": 12.0}] and per[1] == []


def test_rakit_audio_gabungan_dengan_ffmpeg_sungguhan(tmp_path):
    src = tmp_path / "src.ogg"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=6", "-ac", "1", "-ar", "16000",
                    "-c:a", "libopus", str(src)], check=True)
    out = tmp_path / "gabung.ogg"

    tabel = gemini._rakit(src, [{"a": 1.0, "b": 2.0, "ucapan": 1.0},
                                {"a": 3.5, "b": 4.0, "ucapan": 0.5}], out)

    assert [(round(p["ca"], 3), round(p["cb"], 3)) for p in tabel] == [(0.0, 1.0), (2.0, 2.5)]
    durasi = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
        capture_output=True, text=True, check=True).stdout)
    assert durasi == pytest.approx(3.5, abs=0.05)
    assert not out.with_suffix(".raw").exists()


# --- validasi hasil perbaikan ---

def test_potongan_kosong_ditolak():
    assert not gemini._sah([], 5.0, latin=True)


def test_aksara_asing_di_transkrip_latin_ditolak():
    assert not gemini._sah([kata("મમ્મી", 0, 1), kata("આ", 1, 2)], 1.5, latin=True)


def test_aksara_asing_boleh_kalau_sumbernya_memang_bukan_latin():
    assert gemini._sah([kata("日本語", 0, 1)], 1.0, latin=False)


def test_potongan_pendek_cukup_ada_kata():
    assert gemini._sah([kata("portofolio", 0, 1)], 1.2, latin=True)


def test_potongan_panjang_yang_nyaris_kosong_ditolak():
    """Kebocoran bahasa: 16 detik Inggris kembali cuma 3 kata Indonesia."""
    ks = [kata("bahwa", 0, 1), kata("Karena", 1, 2), kata("berarti", 2, 3)]
    assert not gemini._sah(ks, 16.3, latin=True)


def test_ambang_tidak_menolak_ucapan_berjeda():
    """'Prime Minister, Ministers...' 7 kata dalam 7,5 detik itu benar."""
    assert gemini._sah([kata("x", i, i + 1) for i in range(7)], 7.5, latin=True)


# --- alur perbaikan ---

@pytest.fixture
def ada_lubang(monkeypatch):
    lubang = [{"a": float(i * 10), "b": float(i * 10 + 5), "ucapan": 5.0} for i in range(6)]
    monkeypatch.setattr(gemini, "_hening", lambda p: (60.0, []))
    monkeypatch.setattr(gemini, "_lubang", lambda w, d, h: lubang)
    return lubang


def test_kata_pulihan_digabung_urut_waktu(audio, monkeypatch, ada_lubang):
    monkeypatch.setattr(gemini, "_batch", lambda k, p, l, latin: ([kata("pulih", 10, 11)], []))
    out = gemini._perbaiki("key", audio, [kata("awal", 5.5, 6), kata("akhir", 50, 51)])
    assert [w["w"] for w in out] == ["awal", "pulih", "akhir"]


def test_mayoritas_gagal_dipecah_dua_sekali(audio, monkeypatch, ada_lubang):
    """Satu potongan berbahasa pemenang bisa mengunci seluruh gabungan."""
    batch = []

    def palsu(key, path, lubang, latin):
        batch.append(len(lubang))
        if len(batch) == 1:
            return [], lubang
        return [kata("pulih", lubang[0]["a"], lubang[0]["a"] + 1)], []

    monkeypatch.setattr(gemini, "_batch", palsu)
    out = gemini._perbaiki("key", audio, [kata("awal", 5.5, 6)])
    assert batch == [6, 3, 3]
    assert sum(w["w"] == "pulih" for w in out) == 2


def test_sedikit_gagal_tidak_memecah(audio, monkeypatch, ada_lubang):
    batch = []

    def palsu(key, path, lubang, latin):
        batch.append(len(lubang))
        return [], lubang[:2]

    monkeypatch.setattr(gemini, "_batch", palsu)
    gemini._perbaiki("key", audio, [kata("awal", 5.5, 6)])
    assert batch == [6]


def test_perbaikan_gagal_tidak_menggagalkan_transkrip(audio, monkeypatch, ada_lubang):
    def meledak(*a):
        raise gemini.KuotaHabis("habis di semua key")

    monkeypatch.setattr(gemini, "_batch", meledak)
    words = [kata("awal", 5.5, 6)]
    assert gemini._perbaiki("key", audio, words) == words


def test_tanpa_lubang_tidak_ada_request_tambahan(audio, monkeypatch):
    monkeypatch.setattr(gemini, "_hening", lambda p: (6.0, [(0.0, 6.0)]))
    monkeypatch.setattr(gemini, "_batch", lambda *a: pytest.fail("tidak boleh dipanggil"))
    words = [kata("a", 0, 1)]
    assert gemini._perbaiki("key", audio, words) == words


# --- tombol tes di halaman Setting ---

def test_tombol_tes_asr_memeriksa_model_transcribe(monkeypatch):
    urls = []
    monkeypatch.setattr(checks.keypool, "keys", lambda pool: ["key"])
    monkeypatch.setattr(checks.keypool, "lapor", lambda *a: None)
    monkeypatch.setattr(
        checks.httpx, "get",
        lambda url, **kwargs: urls.append(url) or Resp(),
    )
    assert checks.run("gemini-transcribe")["ok"] is True
    assert urls == [
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.5-transcribe"
    ]
