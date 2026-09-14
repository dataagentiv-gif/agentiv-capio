"""Mesin untuk provider yang bicara protokol OpenAI chat/completions.

Dulu dipakai bersama OpenRouter dan Gemini; sekarang tinggal Gemini, tapi
parameternya dibiarkan — URL endpoint, dari mana API key diambil, dan apakah
provider-nya menerima response_format bertipe json_schema — karena itulah yang
membedakan provider OpenAI-compatible mana pun yang nanti ditambahkan.
"""
import json
import re
import time

import httpx

import keypool
from llm import rute
from utils.logging import get

log = get(__name__)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class LLMError(RuntimeError):
    pass


# Jeda sebelum percobaan berikutnya, untuk kegagalan yang sifatnya sementara.
# Terukur di pemakaian: tanpa jeda, tiga percobaan terhadap Gemini yang sedang
# 503 habis dalam 4 DETIK dan seluruh job gagal — padahal gangguannya biasanya
# berlangsung lebih lama dari itu. Menggempur server yang sedang penuh secepat
# itu bukan cuma sia-sia, tapi memperparah keadaannya.
JEDA = (3, 8, 20, 30, 30)


def _tunggu(sementara: bool, attempt: int, label: str) -> None:
    if not sementara:
        return
    detik = JEDA[min(attempt, len(JEDA) - 1)]
    log.info("%s: gangguan sementara, tunggu %ds sebelum coba lagi", label, detik)
    time.sleep(detik)


class _Pemakai:
    """Memilih pasangan (key, model) untuk tiap percobaan, dan mengingat mana
    yang sedang dipakai supaya hasilnya bisa dilaporkan balik.

    Urutannya sudah ditentukan `rute.urutan`: seluruh key untuk tier teratas
    lebih dulu, baru turun tier. Satu instance per panggilan, jadi tidak ada
    state yang menetap antar panggilan maupun antar thread.
    """

    def __init__(self, pool: str, keys: list[str], urut: list[tuple[str, int]]):
        self.pool, self.keys, self.urut = pool, keys, urut
        self.idx, self.model = -1, ""

    def __call__(self, attempt: int) -> tuple[str, str]:
        self.model, self.idx = self.urut[attempt % len(self.urut)]
        # Yang di-log indeksnya, tidak pernah key-nya.
        log.debug("%s pakai key #%d model %s", self.pool, self.idx + 1, self.model)
        return self.keys[self.idx], self.model

    def tandai_habis(self) -> None:
        if self.idx >= 0:
            rute.tandai_habis(self.pool, self.model, self.idx)


def call_pool(prompt, response_schema, *, pool: str, nama: str, **kw):
    """call() dengan rotasi key dan pelaporan status.

    Dipakai bersama semua provider LLM: yang membedakan mereka cuma endpoint,
    model, dan apakah json_schema diterima — bukan cara merotasi key. Menulis
    ulang logika ini per provider hanya menghasilkan dua salinan yang lambat
    laun berbeda.
    """
    daftar = keypool.keys(pool)
    if not daftar:
        raise LLMError(f"{nama} API key kosong — isi di halaman Setting")

    models = kw.pop("models", None) or []
    urut = rute.urutan(pool, models, len(daftar))

    # Cukup percobaan supaya tier berikutnya sempat kena giliran saat tier
    # teratas habis di semua key. Dibatasi 6 supaya kegagalan yang sebenarnya
    # (JSON ngawur) tidak diulang belasan kali — dan karena urutannya sudah
    # menaruh pasangan yang bertanda habis di belakang, enam percobaan pertama
    # hampir selalu yang paling menjanjikan.
    kw["attempts"] = min(max(kw.get("attempts", 3), len(daftar), len(models)), 6)

    pemakai = _Pemakai(pool, daftar, urut)
    try:
        hasil = call(prompt, response_schema, pemakai=pemakai, label=pool, **kw)
    except Exception as e:
        if pemakai.idx >= 0:
            keypool.lapor(pool, pemakai.idx, False, f"{type(e).__name__}: {e}")
        raise
    if pemakai.idx >= 0:
        keypool.lapor(pool, pemakai.idx, True, "OK")
    return hasil


def _kuota_habis(code: int, badan: str) -> bool:
    """Bedakan kuota yang benar-benar habis dari rate limit sesaat.

    Dua-duanya HTTP 429, tapi artinya berlawanan. Rate limit per menit pulih
    sendiri dalam hitungan detik — itu justru alasan JEDA ada. Kuota harian
    baru pulih besok, dan seluruh key sudah dicoba di percobaan sebelumnya,
    jadi menunggu untuk itu cuma menahan job satu menit sebelum gagal sama saja.
    """
    return code == 429 and "exceeded your current quota" in badan.lower()


def _pesan(code: int, badan: str) -> str:
    """Terjemahkan HTTP error jadi kalimat yang menyebut tindakan yang benar.

    "HTTP 429" saja tidak memberitahu apa pun yang bisa ditindaklanjuti: orang
    tidak tahu apakah harus menunggu semenit, menambah key, atau membayar.
    """
    if _kuota_habis(code, badan):
        return (
            "kuota API habis. Free tier dibatasi per hari per key — tunggu "
            "resetnya, tambah key di halaman Setting, atau naikkan plan."
        )
    if code == 429:
        return "kena rate limit dan belum pulih setelah beberapa kali dicoba."
    if code in (401, 403):
        return "API key ditolak. Periksa kembali key di halaman Setting."
    if code >= 500:
        return f"server provider bermasalah (HTTP {code}). Coba lagi nanti."
    return f"HTTP {code}"


def _extract_json(text: str):
    """Model kadang membungkus JSON dalam code fence walau diminta raw."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: ambil blok kurung terluar. Menangani kasus model menambah
        # kalimat pengantar sebelum JSON-nya.
        for open_c, close_c in (("[", "]"), ("{", "}")):
            i, j = cleaned.find(open_c), cleaned.rfind(close_c)
            if i != -1 and j > i:
                return json.loads(cleaned[i : j + 1])
        raise


def call(
    prompt: str,
    response_schema: dict | None,
    *,
    endpoint: str,
    pemakai,
    use_schema: bool,
    attempts: int = 3,
    label: str = "llm",
):
    """Panggil LLM, kembalikan hasil yang sudah di-parse jadi objek Python.

    `pemakai(attempt)` mengembalikan pasangan (key, model) untuk percobaan itu.
    Urutannya sudah diputuskan di luar sini — seluruh key untuk tier teratas
    lebih dulu, baru turun tier — jadi fungsi ini tidak perlu tahu apa pun soal
    kuota, tier, maupun pool.
    """
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    if response_schema:
        body["response_format"] = (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
            if use_schema
            # Provider yang belum dipastikan menerima json_schema cukup diminta
            # JSON bebas. Bentuknya tetap terjaga karena prompt sudah menyebut
            # tiap field, stage memvalidasi hasilnya sendiri, dan error parsing
            # disuntikkan balik ke prompt di percobaan berikutnya.
            else {"type": "json_object"}
        )

    last_err, last_raw = "", ""
    for attempt in range(attempts):
        key, model = pemakai(attempt)
        body["model"] = model
        if attempt:
            log.info("%s percobaan %d: model %s, key #%d",
                     label, attempt + 1, model, pemakai.idx + 1)
        if last_err:
            body["messages"] = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        f"Output di atas ditolak parser: {last_err}\n"
                        "Balas ULANG dengan JSON valid saja, tanpa penjelasan, "
                        "tanpa code fence."
                    ),
                },
            ]
        try:
            r = httpx.post(
                endpoint,
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=180.0,
            )
            r.raise_for_status()
            last_raw = r.json()["choices"][0]["message"]["content"]
            return _extract_json(last_raw)

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            badan = e.response.text
            last_err, last_raw = f"HTTP {code}", ""
            log.warning(
                "%s percobaan %d/%d gagal (model %s, key #%d): HTTP %d %s",
                label, attempt + 1, attempts, model, pemakai.idx + 1,
                code, badan[:200],
            )
            # Kuota pasangan ini dicatat habis supaya job BERIKUTNYA langsung
            # turun tier tanpa mengulangi panggilan yang sudah pasti gagal.
            # Hanya untuk kuota yang benar-benar habis: rate limit sesaat pulih
            # dalam hitungan detik, dan menandainya sejam membuang tier teratas
            # untuk masalah yang sudah beres sebelum job berikutnya mulai.
            if _kuota_habis(code, badan):
                pemakai.tandai_habis()
            if attempt == attempts - 1:
                raise LLMError(
                    f"{label} gagal setelah {attempts}x: {_pesan(code, badan)}"
                ) from e
            # Kuota harian yang habis tidak pulih dalam hitungan detik, dan
            # semua key sudah dicoba di percobaan sebelumnya. Menunggu di sini
            # cuma menahan job selama satu menit sebelum gagal dengan cara yang
            # persis sama.
            _tunggu(
                (code >= 500 or code == 429) and not _kuota_habis(code, badan),
                attempt, label,
            )

        except httpx.HTTPError as e:
            last_err, last_raw = f"koneksi: {e}", ""
            if attempt == attempts - 1:
                raise LLMError(f"{label} gagal setelah {attempts}x: {e}") from e
            _tunggu(True, attempt, label)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            log.warning("%s percobaan %d/%d: JSON invalid — %s", label, attempt + 1, attempts, last_err)
            if attempt == attempts - 1:
                raise LLMError(
                    f"{label}: JSON invalid setelah {attempts}x. Terakhir: {last_err}"
                ) from e
            # Tanpa jeda: kegagalan ini soal ISI balasan, bukan kondisi server.
            # Percobaan ulangnya membawa pesan error sebagai umpan balik, dan
            # menundanya tidak menambah peluang berhasil sama sekali.
