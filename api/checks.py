"""Tes koneksi per provider untuk halaman Settings.

Key yang salah adalah penyebab kegagalan paling sering pada orang yang baru
memasang project ini, dan tanpa tombol tes kesalahannya baru muncul belasan
menit kemudian sebagai job gagal di tengah pipeline.

Tiap probe dibuat semurah mungkin: daftar model atau satu permintaan kecil,
bukan transkrip atau upload sungguhan.
"""
import httpx

from config.settings import settings
from utils.logging import get

log = get(__name__)
TIMEOUT = 25.0


def _groq() -> tuple[bool, str]:
    if not settings.GROQ_API_KEY:
        return False, "Key belum diisi"
    r = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        timeout=TIMEOUT,
    )
    if r.status_code == 200:
        return True, "Terhubung"
    if r.status_code == 403:
        return False, "Ditolak (403). Groq memblokir IP datacenter — matikan VPN kalau menyala."
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def _elevenlabs() -> tuple[bool, str]:
    if not settings.ELEVENLABS_API_KEY:
        return False, "Key belum diisi"
    r = httpx.get(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
        timeout=TIMEOUT,
    )
    return (True, "Terhubung") if r.status_code == 200 else (
        False, f"HTTP {r.status_code}: {r.text[:120]}"
    )


def _openrouter() -> tuple[bool, str]:
    if not settings.OPENROUTER_API_KEY:
        return False, "Key belum diisi"
    r = httpx.get(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        timeout=TIMEOUT,
    )
    return (True, "Terhubung") if r.status_code == 200 else (
        False, f"HTTP {r.status_code}: {r.text[:120]}"
    )


def _gemini() -> tuple[bool, str]:
    keys = settings.gemini_keys
    if not keys:
        return False, "Key belum diisi"
    # Tiap key diuji sendiri — satu key mati di antara beberapa key tetap harus
    # ketahuan, bukan tertutup oleh key lain yang kebetulan jalan.
    hasil = []
    for i, k in enumerate(keys, 1):
        r = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            headers={"Authorization": f"Bearer {k}"},
            json={"model": settings.GEMINI_MODEL,
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1},
            timeout=TIMEOUT,
        )
        hasil.append(f"#{i} OK" if r.status_code == 200 else f"#{i} HTTP {r.status_code}")
    ok = all("OK" in h for h in hasil)
    return ok, f"{len(keys)} key: " + ", ".join(hasil)


PROBES = {
    "groq": _groq,
    "elevenlabs": _elevenlabs,
    "openrouter": _openrouter,
    "gemini": _gemini,
}


def run(provider: str) -> dict:
    probe = PROBES.get(provider)
    if probe is None:
        return {"ok": False, "message": f"Provider '{provider}' tidak dikenal"}
    try:
        ok, message = probe()
    except Exception as e:  # noqa: BLE001 — tes koneksi tidak boleh menjatuhkan API
        log.warning("tes %s gagal: %s", provider, e)
        ok, message = False, f"{type(e).__name__}: {e}"[:200]
    return {"ok": ok, "message": message}
