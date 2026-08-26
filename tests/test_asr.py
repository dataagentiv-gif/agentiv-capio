"""Pemilihan provider transkrip dan penurunan kalimat.

Scribe tidak mengembalikan pembagian kalimat sama sekali — cuma kata. Padahal
Stage 3 memakai kalimat bertanda baca untuk menentukan titik potong, jadi
kalimatnya diturunkan di client. Kalau penurunan itu rusak, tidak ada yang
error: seluruh transkrip jadi satu kalimat raksasa dan Stage 3 diam-diam
kehilangan semua titik potongnya.
"""
import pytest

import asr
from asr.client_elevenlabs import sentences_from_words
from config.settings import settings


def w(text, s, e):
    return {"w": text, "s": s, "e": e}


# --- penurunan kalimat ---

def test_dipecah_di_titik():
    out = sentences_from_words(
        [w("Halo.", 0.0, 0.5), w("Apa", 0.6, 0.9), w("kabar?", 1.0, 1.4)]
    )
    assert [s["text"] for s in out] == ["Halo.", "Apa kabar?"]


@pytest.mark.parametrize("akhir", ["selesai.", "benar?", "hebat!", "lho...", 'ujarnya."'])
def test_semua_penutup_kalimat_dikenali(akhir):
    out = sentences_from_words([w("Ini", 0.0, 0.3), w(akhir, 0.4, 0.9), w("Lanjut.", 1.0, 1.5)])
    assert len(out) == 2


def test_waktu_kalimat_mengikuti_kata_pertama_dan_terakhir():
    out = sentences_from_words([w("Satu", 1.0, 1.4), w("dua.", 1.5, 2.2)])
    assert out[0]["s"] == 1.0 and out[0]["e"] == 2.2


def test_kalimat_terakhir_tanpa_titik_tetap_ikut():
    """Kalau tidak, kata-kata penutup video hilang begitu saja."""
    out = sentences_from_words([w("Selesai.", 0.0, 0.5), w("menggantung", 0.6, 1.0)])
    assert len(out) == 2
    assert out[1]["text"] == "menggantung"


def test_tanpa_tanda_baca_dipecah_pakai_jeda():
    """Cadangan. Tanpa ini seluruh transkrip jadi satu kalimat raksasa dan
    Stage 3 kehilangan semua titik potongnya."""
    words = [
        w("satu", 0.0, 0.3), w("dua", 0.4, 0.7),      # jeda 1.3s setelah ini
        w("tiga", 2.0, 2.3), w("empat", 2.4, 2.7),
    ]
    out = sentences_from_words(words)
    assert len(out) == 2
    assert out[0]["text"] == "satu dua"
    assert out[1]["text"] == "tiga empat"


def test_kata_kosong_menghasilkan_kalimat_kosong():
    assert sentences_from_words([]) == []


def test_satu_kalimat_utuh_tidak_dipaksa_pecah():
    """Punya tanda baca dan cuma satu kalimat -> jangan jatuh ke mode jeda."""
    out = sentences_from_words([w("Cuma", 0.0, 0.4), w("satu", 3.0, 3.4), w("kalimat.", 3.5, 4.0)])
    assert len(out) == 1


# --- pemilihan provider ---

def test_provider_tidak_dikenal_ditolak(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "deepgram")
    with pytest.raises(RuntimeError, match="tidak dikenal"):
        asr.check_config()


@pytest.mark.parametrize("nama", ["groq", "GROQ", " Groq "])
def test_nama_provider_tidak_peduli_huruf_besar_kecil(monkeypatch, nama):
    monkeypatch.setattr(settings, "ASR_PROVIDER", nama)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        asr.check_config()


def test_key_elevenlabs_kosong_ditolak_dengan_pesan_jelas(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "elevenlabs")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        asr.check_config()


def test_batas_ukuran_beda_jauh_antar_provider(monkeypatch):
    """Groq 25MB, Scribe 3GB — kalau tertukar, audio 1 jam dipecah sia-sia
    atau justru ditolak provider karena kebesaran."""
    monkeypatch.setattr(settings, "ASR_PROVIDER", "groq")
    kecil = asr.size_limit()
    monkeypatch.setattr(settings, "ASR_PROVIDER", "elevenlabs")
    assert asr.size_limit() > kecil * 50
