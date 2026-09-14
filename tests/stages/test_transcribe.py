"""Stage 2, khususnya cabang chunking yang belum pernah jalan di produksi.

`_chunks()` baru aktif kalau audio melebihi batas provider — pada Groq itu 24 MB
≈ 2,3 jam, dan video terpanjang yang pernah diproses baru 26 menit. Jadi seluruh
logika penggabungannya belum pernah diuji oleh kenyataan.

Yang berisiko di situ bukan pemanggilan ASR-nya, melainkan penyatuannya: tiap
chunk mengembalikan timestamp yang dimulai dari nol, dan kalau offset-nya salah
seluruh caption bergeser diam-diam — tidak ada yang gagal, klipnya cuma
kehilangan sinkronisasi. Index kata juga dipakai LLM di Stage 3 untuk menunjuk
batas segmen, jadi penomoran yang bolong menghasilkan potongan di tempat yang
salah.

Semua itu logika murni, jadi diuji dengan ASR dipalsukan — tanpa mengunduh
apa pun.
"""
import json

import pytest

from pipeline.stages import transcribe


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "audio.ogg").write_bytes(b"x" * 100)
    return {
        "audio": tmp_path / "audio.ogg",
        "workdir": tmp_path,
        "deadline": None,
        "meta": {"duration": 3000.0},
    }


def kata(w, s, e):
    return {"w": w, "s": s, "e": e}


@pytest.fixture
def palsu(monkeypatch):
    """Ganti provider ASR dan ffmpeg dengan yang tidak menyentuh apa pun."""
    monkeypatch.setattr(transcribe, "ffmpeg", lambda *a, **k: None)
    monkeypatch.setattr(transcribe.asr, "check_config", lambda: None)
    monkeypatch.setattr(transcribe.asr, "duration_limit", lambda: float("inf"))

    def _pasang(batas, hasil_per_chunk):
        """hasil_per_chunk: daftar (words, sentences) sebelum offset."""
        panggilan = []
        monkeypatch.setattr(transcribe.asr, "size_limit", lambda: batas)

        def fake(path, offset):
            i = len(panggilan)
            panggilan.append(offset)
            w, s = hasil_per_chunk[min(i, len(hasil_per_chunk) - 1)]
            # Provider sungguhan sudah menambahkan offset sebelum kembali,
            # jadi yang dipalsukan pun harus begitu.
            return (
                [kata(x["w"], x["s"] + offset, x["e"] + offset) for x in w],
                [{"text": y["text"], "s": y["s"] + offset, "e": y["e"] + offset}
                 for y in s],
            )

        monkeypatch.setattr(transcribe.asr, "transcribe", fake)
        return panggilan
    return _pasang


# --- kapan chunking dipakai ---

def test_audio_kecil_tidak_dipecah(ctx, palsu):
    panggilan = palsu(10_000, [([kata("a", 0, 1)], [])])
    transcribe.run(ctx)
    assert panggilan == [0.0], "audio di bawah batas tidak boleh dipecah"


def test_audio_besar_dipecah_per_20_menit(ctx, palsu):
    """3000 detik / 1200 = 2,5 -> 3 chunk."""
    panggilan = palsu(10, [([kata("a", 0, 1)], [])])
    transcribe.run(ctx)
    assert panggilan == [0.0, 1200.0, 2400.0]


def test_tepat_di_batas_tidak_dipecah(ctx, palsu):
    """`<=` bukan `<`: file berukuran persis batas masih diterima provider."""
    panggilan = palsu(100, [([kata("a", 0, 1)], [])])
    transcribe.run(ctx)
    assert len(panggilan) == 1


def test_batas_durasi_provider_memicu_chunking(ctx, palsu, monkeypatch):
    panggilan = palsu(10_000, [([kata("a", 0, 1)], [])])
    monkeypatch.setattr(transcribe.asr, "duration_limit", lambda: 1200.0)
    transcribe.run(ctx)
    assert panggilan == [0.0, 1200.0, 2400.0]


# --- penggabungan chunk ---

def test_offset_tiap_chunk_ditambahkan(ctx, palsu):
    """Inilah kegagalan paling berbahaya: kalau offset hilang, seluruh caption
    chunk kedua dan seterusnya bergeser tanpa satu pun error."""
    palsu(10, [([kata("a", 0, 1)], []), ([kata("b", 5, 6)], []),
               ([kata("c", 10, 11)], [])])
    out = transcribe.run(ctx)
    assert [w["s"] for w in out["words"]] == [0, 1205, 2410]


def test_index_dinomori_ulang_berurutan(ctx, palsu):
    """`i` dipakai LLM di Stage 3 untuk menunjuk batas segmen. Lompatan atau
    duplikat membuat potongan jatuh di tempat yang salah."""
    palsu(10, [([kata("a", 0, 1), kata("b", 2, 3)], [])])
    out = transcribe.run(ctx)
    assert [w["i"] for w in out["words"]] == list(range(len(out["words"])))


def test_kata_diurutkan_berdasarkan_waktu(ctx, palsu):
    """Provider bisa mengembalikan urutan yang tidak rapi; caption karaoke
    mengandalkan urutan waktu, bukan urutan kedatangan."""
    palsu(10, [([kata("b", 5, 6), kata("a", 0, 1)], [])])
    out = transcribe.run(ctx)
    assert [w["s"] for w in out["words"]] == sorted(w["s"] for w in out["words"])


def test_kalimat_dari_semua_chunk_ikut_terkumpul(ctx, palsu):
    """Kalimat adalah bahan Stage 3 untuk menentukan titik potong. Kalau chunk
    kedua hilang, separuh video kehilangan seluruh anchor-nya."""
    palsu(10, [([kata("a", 0, 1)], [{"text": "Satu.", "s": 0, "e": 1}])])
    out = transcribe.run(ctx)
    assert len(out["sentences"]) == 3
    assert [s["s"] for s in out["sentences"]] == [0, 1200, 2400]


def test_kalimat_diurutkan_berdasarkan_waktu(ctx, palsu):
    palsu(10, [([kata("a", 0, 1)], [{"text": "B.", "s": 9, "e": 10},
                                    {"text": "A.", "s": 1, "e": 2}])])
    out = transcribe.run(ctx)
    assert [s["s"] for s in out["sentences"]] == sorted(
        s["s"] for s in out["sentences"])


# --- kegagalan ---

def test_transkrip_kosong_melempar_error(ctx, palsu):
    """Job 'selesai' dengan nol klip adalah kegagalan senyap yang paling
    membingungkan — lebih baik gagal dengan sebab yang disebut."""
    palsu(10_000, [([], [])])
    with pytest.raises(RuntimeError, match="Transkrip kosong"):
        transcribe.run(ctx)


def test_key_diperiksa_sebelum_transkrip_dimulai(ctx, monkeypatch):
    """Salah konfigurasi harus ketahuan sebelum audio dikirim, bukan setelah
    beberapa chunk terlanjur ditagih."""
    monkeypatch.setattr(transcribe.asr, "check_config",
                        lambda: (_ for _ in ()).throw(RuntimeError("key kosong")))
    monkeypatch.setattr(transcribe.asr, "transcribe",
                        lambda *a: pytest.fail("tidak boleh dipanggil"))
    with pytest.raises(RuntimeError, match="key kosong"):
        transcribe.run(ctx)


# --- keluaran ---

def test_words_dan_sentences_ditulis_ke_workdir(ctx, palsu, tmp_path):
    palsu(10_000, [([kata("a", 0, 1)], [{"text": "A.", "s": 0, "e": 1}])])
    transcribe.run(ctx)
    w = json.loads((tmp_path / "words.json").read_text(encoding="utf-8"))
    assert w[0]["i"] == 0 and w[0]["w"] == "a"
    assert (tmp_path / "sentences.json").exists()


def test_kontrak_field_kata_dijaga(ctx, palsu):
    """Stage 5 membaca w/s/e dan Stage 3 membaca i. Field tambahan dari
    provider tidak boleh ikut bocor ke kontrak."""
    palsu(10_000, [([kata("a", 0, 1)], [])])
    out = transcribe.run(ctx)
    assert set(out["words"][0]) == {"i", "w", "s", "e"}


def test_chunk_membaca_nama_file_audio_yang_sebenarnya(tmp_path, monkeypatch):
    """Nama file sempat ditulis literal "audio.ogg" di perintah ffmpeg,
    sementara nama sebenarnya datang lewat argumen. Selama keduanya kebetulan
    sama tidak ada yang terlihat — dan cabang ini cuma hidup pada audio >2,3
    jam, jadi kerusakannya akan menunggu lama sebelum ketahuan."""
    dipakai = []
    monkeypatch.setattr(transcribe, "ffmpeg",
                        lambda args, *a, **k: dipakai.append(args[args.index("-i") + 1]))
    monkeypatch.setattr(transcribe.asr, "check_config", lambda: None)
    monkeypatch.setattr(transcribe.asr, "size_limit", lambda: 10)
    monkeypatch.setattr(transcribe.asr, "transcribe",
                        lambda p, off: ([kata("a", off, off + 1)], []))

    (tmp_path / "suara-lain.ogg").write_bytes(b"x" * 100)
    transcribe.run({
        "audio": tmp_path / "suara-lain.ogg", "workdir": tmp_path,
        "deadline": None, "meta": {"duration": 2000.0},
    })
    assert dipakai and set(dipakai) == {"suara-lain.ogg"}
