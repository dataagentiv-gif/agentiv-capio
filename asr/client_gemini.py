"""Provider Gemini 3.5 Transcribe dengan timestamp per kata.

Audio diunggah lewat Files API, dipakai sekali untuk transkripsi, lalu segera
dihapus. Model ini menerima paling lama 30 menit saat word timestamp aktif;
MAX_DURATION_SEC dibuat 20 menit supaya Stage 2 memecahnya dengan margin aman.

Model ini hanya menulis SATU bahasa per request dan membuang ucapan bahasa lain
tanpa tanda apa pun: HTTP 200, tanpa error, tanpa huruf asing. Terukur pada 5
video — talking-head Indonesia berkutip Inggris kehilangan 27,9% detik
bicaranya, video bilingual 30,9%, berita Indonesia murni 1,7% (lantai
kebisingan detektornya). Klaim dokumentasi soal code-switching hanya berlaku
di audio <=30 detik tanpa timestamp; `language_codes` cuma memilih bahasa mana
yang dibuang, pin dua bahasa pun tetap membuang satu.

Karena itu setiap transkrip diperiksa: celah antar kata yang menurut ffmpeg
BERSUARA adalah ucapan yang dibuang. Semua celah dipotong pas di batas kata,
disambung jadi satu audio, lalu ditranskrip sekali lagi. Isinya bukan bahasa
yang tadi menang, jadi tidak ada yang bisa mengunci. Pada dua video uji,
detik bicara tanpa kata turun ke 4,4% dan 2,2% dengan satu request tambahan.
"""
import re
import time
from pathlib import Path

import httpx

import keypool
from asr import rasio_non_latin, sentences_from_words
from config.settings import settings
from utils.ffmpeg_helpers import Deadline, ffmpeg, probe, run, silences
from utils.logging import get
from utils.retry import retry

log = get(__name__)

BASE = "https://generativelanguage.googleapis.com"
MODEL = "gemini-3.5-transcribe"
MIME = "audio/ogg"
SIZE_LIMIT = 2 * 1024 * 1024 * 1024
MAX_DURATION_SEC = 1200.0

SR = 16000
CELAH_MIN = 1.0       # celah antar kata yang dicurigai berisi ucapan yang dibuang
SUARA_MIN = 0.7       # detik bersuara minimal di dalam celah itu
JEDA_GABUNG = 1.0     # hening di antara potongan dalam audio gabungan
PENDEK = 3.0          # potongan sependek ini cukup "ada kata"
KATA_PER_DETIK = 0.5  # potongan lebih panjang: di bawah ini = bocor atau mengarang
# Batas per menit dan per hari free tier memakai NAMA metrik yang sama
# (`generate_content_free_tier_requests`, terukur 3 dan 25); hanya angkanya
# yang membedakan. `retry in` tidak bisa dipakai: saat kuota harian habis pun
# servernya bilang "retry in 7s".
# ponytail: ambang angka; ganti kalau Google menaikkan RPM free tier melewati ini
HARIAN_MIN = 20
TUNGGU_MAKS = 150.0   # total detik menunggu rate limit per request


class KuotaHabis(RuntimeError):
    """Kuota harian satu project habis; menunggu tidak akan menolong hari ini."""


def check_config() -> None:
    if not settings.gemini_keys:
        raise RuntimeError("Gemini API key kosong — isi di halaman Setting")


def _wajib_ok(r: httpx.Response, tahap: str) -> None:
    if not 200 <= r.status_code < 300:
        raise RuntimeError(
            f"Gemini Transcribe HTTP {r.status_code} saat {tahap}: {r.text[:300]}"
        )


def _detik(nilai) -> float:
    teks = str(nilai or "").strip()
    if teks.endswith("s"):
        teks = teks[:-1]
    try:
        return float(teks)
    except ValueError as e:
        raise RuntimeError(f"Timestamp Gemini tidak valid: {nilai!r}") from e


def _annotations(data: dict, offset: float) -> list[dict]:
    """Kata bertimestamp, urut waktu. Kosong kalau model tidak menulis apa pun —
    wajar untuk potongan musik, jadi keputusan menolaknya ada di pemanggil."""
    words = []
    for step in data.get("steps") or []:
        for content in step.get("content") or []:
            for ann in content.get("annotations") or []:
                if ann.get("type") != "word_info":
                    continue
                teks = str(ann.get("text") or "").strip()
                if not teks:
                    continue
                start = _detik(ann.get("start_offset")) + offset
                end = _detik(ann.get("end_offset")) + offset
                if end > start:
                    words.append({"w": teks, "s": start, "e": end})
    # Anotasi tidak selalu urut: "Iya." bisa tercatat sesudah kata yang
    # diucapkan setelahnya. Deteksi celah membutuhkan urutan waktu.
    return sorted(words, key=lambda w: w["s"])


def _upload(key: str, path: Path) -> tuple[str, str]:
    ukuran = path.stat().st_size
    mulai = httpx.post(
        f"{BASE}/upload/v1beta/files",
        headers={
            "x-goog-api-key": key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(ukuran),
            "X-Goog-Upload-Header-Content-Type": MIME,
        },
        json={"file": {"display_name": path.name}},
        timeout=60.0,
    )
    _wajib_ok(mulai, "memulai upload")
    upload_url = mulai.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Gemini Files API tidak mengembalikan URL upload")

    with path.open("rb") as f:
        selesai = httpx.post(
            upload_url,
            headers={
                "Content-Length": str(ukuran),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            content=f,
            timeout=900.0,
        )
    _wajib_ok(selesai, "mengunggah audio")
    file = (selesai.json() or {}).get("file") or {}
    name, uri = str(file.get("name") or ""), str(file.get("uri") or "")
    if not name or not uri:
        raise RuntimeError("Respons upload Gemini tidak memuat nama dan URI file")
    return name, uri


def _tunggu_aktif(key: str, name: str) -> None:
    for _ in range(60):
        r = httpx.get(
            f"{BASE}/v1beta/{name}", headers={"x-goog-api-key": key}, timeout=30.0
        )
        _wajib_ok(r, "memeriksa audio")
        state = str((r.json() or {}).get("state") or "ACTIVE").upper()
        if state == "ACTIVE":
            return
        if state == "FAILED":
            raise RuntimeError("Gemini gagal memproses audio yang diunggah")
        time.sleep(2)
    raise TimeoutError("Audio Gemini belum siap setelah 120 detik")


def _hapus(key: str, name: str) -> None:
    try:
        r = httpx.delete(
            f"{BASE}/v1beta/{name}", headers={"x-goog-api-key": key}, timeout=30.0
        )
        _wajib_ok(r, "menghapus file")
    except Exception as e:  # noqa: BLE001 — cleanup remote tidak boleh membuang hasil
        log.warning("file sementara Gemini %s gagal dihapus: %s", name, e)


def _jeda_429(teks: str) -> float | None:
    """Detik yang perlu ditunggu, atau None kalau yang habis kuota harian.

    Semua 429 Google berbunyi "exceeded your current quota", baik batas per
    menit maupun per hari — kalimat itu tidak membedakan apa pun.
    """
    m = re.search(r"metric: ([\w./]+), limit: (\d+)", teks)
    if m and "token" not in m.group(1) and int(m.group(2)) >= HARIAN_MIN:
        return None
    w = re.search(r"retry in ([\d.]+)s", teks)
    return min(float(w.group(1)) + 1.0, 65.0) if w else 30.0


def _minta(key: str, path: Path) -> list[dict]:
    """Upload, transkrip word-timestamp, hapus. Waktu kata lokal terhadap berkas.

    Satu key dari upload sampai request: berkas Files API milik project key
    pengunggahnya, dan request dengan key project lain dijawab 403.
    """
    name = ""
    try:
        name, uri = _upload(key, path)
        _tunggu_aktif(key, name)
        ditunggu = 0.0
        while True:
            r = httpx.post(
                f"{BASE}/v1beta/interactions",
                headers={"x-goog-api-key": key},
                json={
                    "model": MODEL,
                    "input": [{"type": "audio", "uri": uri, "mime_type": MIME}],
                    "generation_config": {
                        "transcription_config": {
                            "mode": {
                                "type": "verbatim",
                                "timestamp_granularities": ["word"],
                            }
                        }
                    },
                },
                timeout=900.0,
            )
            if r.status_code != 429:
                break
            jeda = _jeda_429(r.text)
            if jeda is None:
                # "quota_exceeded" dan "gemini" sengaja ada di teksnya: itu yang
                # dikenali utils/pesan.py untuk menyuruh menambah key Gemini.
                raise KuotaHabis(
                    f"Gemini Transcribe quota_exceeded: kuota harian habis — {r.text[:200]}"
                )
            if ditunggu + jeda > TUNGGU_MAKS:
                break
            # Hampir pasti terjadi tepat sesudah pass pertama: audio 10 menit
            # sudah 15 ribu token, di atas batas 10 ribu token per menit.
            log.info("gemini: rate limit per menit, tunggu %.0f detik", jeda)
            time.sleep(jeda)
            ditunggu += jeda
        _wajib_ok(r, "mentranskrip audio")
        return _annotations(r.json(), 0.0)
    finally:
        if name:
            _hapus(key, name)


def _minta_cadangan(key: str, path: Path) -> list[dict]:
    """Kuota harian habis di tengah perbaikan: coba key lain, jangan membuang
    pass pertama yang sudah terbayar. Key satu project berbagi kuota, jadi
    sebagian key lain bisa ikut habis — itu yang dilewati di sini."""
    try:
        return _minta(key, path)
    except KuotaHabis:
        for lain in keypool.keys("gemini"):
            if lain == key:
                continue
            try:
                return _minta(lain, path)
            except KuotaHabis:
                continue
        raise


def _bersuara(a: float, b: float, hening: list[tuple[float, float]]) -> float:
    return (b - a) - sum(max(0.0, min(b, e) - max(a, s)) for s, e in hening)


def _lubang(words: list[dict], durasi: float, hening: list[tuple[float, float]]) -> list[dict]:
    """Celah antar kata yang bersuara — termasuk sebelum kata pertama dan
    sesudah kata terakhir: pembukaan video Maudy di detik 0 ternyata ucapan
    Inggris yang dibuang, bukan musik intro."""
    out, ujung = [], 0.0
    for w in words + [{"s": durasi, "e": durasi}]:
        if w["s"] - ujung >= CELAH_MIN:
            suara = _bersuara(ujung, w["s"], hening)
            if suara >= SUARA_MIN:
                out.append({"a": ujung, "b": w["s"], "ucapan": suara})
        ujung = max(ujung, w["e"])
    return out


def _rakit(path: Path, lubang: list[dict], out: Path) -> list[dict]:
    """Sambung potongan celah jadi satu audio; kembalikan tabel posisinya.

    Dipotong PAS di batas kata, tanpa bantalan: potongan Inggris 16,3 detik
    menghasilkan 34 kata, tapi potongan yang sama dengan bantalan 0,7 detik
    (kena "bahwa" dan "Karena berarti") cuma 3 kata — sedikit bahasa Indonesia
    sudah cukup membuat model mengunci ke bahasa Indonesia lagi.
    """
    dl = Deadline(600)
    pcm = run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        dl, binary=True,
    ).stdout
    jeda = b"\0\0" * int(JEDA_GABUNG * SR)
    mentah, tabel, t = bytearray(), [], 0.0
    for h in lubang:
        seg = pcm[int(h["a"] * SR) * 2: int(h["b"] * SR) * 2]
        panjang = len(seg) / 2 / SR
        tabel.append({**h, "ca": t, "cb": t + panjang})
        mentah += seg + jeda
        t += panjang + JEDA_GABUNG
    raw = out.with_suffix(".raw")
    raw.write_bytes(bytes(mentah))
    try:
        ffmpeg(["-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                "-c:a", "libopus", "-b:a", "24k", str(out)], dl)
    finally:
        raw.unlink(missing_ok=True)
    return tabel


def _petakan(kata: list[dict], tabel: list[dict]) -> list[list[dict]]:
    """Kembalikan tiap kata audio gabungan ke waktu aslinya, per potongan."""
    per = [[] for _ in tabel]
    for w in kata:
        tengah = (w["s"] + w["e"]) / 2
        for i, p in enumerate(tabel):
            if p["ca"] - JEDA_GABUNG / 2 <= tengah < p["cb"] + JEDA_GABUNG / 2:
                geser = p["a"] - p["ca"]
                per[i].append({
                    "w": w["w"],
                    "s": min(max(w["s"] + geser, p["a"]), p["b"]),
                    "e": min(max(w["e"] + geser, p["a"]), p["b"]),
                })
                break
    return per


def _sah(kata: list[dict], ucapan: float, latin: bool) -> bool:
    """Hasil perbaikan boleh dipakai? Diputuskan PER POTONGAN, bukan per batch.

    Tolak aksara non-Latin pada transkrip Latin: di atas efek suara 25 detik
    model menulis "મમ્મી આ મમ્મી". Ambang kata/detik 0,5, bukan 1,0 — terukur,
    hasil yang benar ada di 0,74-0,93 ("Iya. Gua", "portofolio") dan kebocoran
    sungguhan di 0,12-0,18.
    """
    if not kata:
        return False
    if latin and rasio_non_latin(" ".join(k["w"] for k in kata)) > 1.0:
        return False
    return ucapan < PENDEK or len(kata) / ucapan >= KATA_PER_DETIK


def _batch(key: str, path: Path, lubang: list[dict], latin: bool) -> tuple[list[dict], list[dict]]:
    gabungan = path.with_name(f"{path.stem}.lubang.ogg")
    try:
        tabel = _rakit(path, lubang, gabungan)
        kata = _minta_cadangan(key, gabungan)
    finally:
        gabungan.unlink(missing_ok=True)
    pulih, gagal = [], []
    for h, k in zip(tabel, _petakan(kata, tabel)):
        if _sah(k, h["ucapan"], latin):
            pulih += k
        else:
            gagal.append({"a": h["a"], "b": h["b"], "ucapan": h["ucapan"]})
    return pulih, gagal


def _hening(path: Path) -> tuple[float, list[tuple[float, float]]]:
    dl = Deadline(600)
    durasi = probe(path, dl)["duration"]
    return durasi, silences(path, durasi, dl,
                            settings.SILENCE_NOISE_DB, settings.SILENCE_MIN_DUR)


def _perbaiki(key: str, path: Path, words: list[dict]) -> list[dict]:
    """Transkrip ulang ucapan yang dibuang. Gagal di sini tidak menggagalkan job:
    pass pertama tetap dipakai, tapi sisa detik yang tak tertranskrip dicatat
    WARNING — diam-diam memakai transkrip bolong adalah bug yang sedang ditambal."""
    lubang: list[dict] = []
    try:
        durasi, hening = _hening(path)
        lubang = _lubang(words, durasi, hening)
        if not lubang:
            return words
        total = sum(h["ucapan"] for h in lubang)
        log.info("gemini: %d celah bersuara tanpa kata (%.0f detik) — ditranskrip ulang",
                 len(lubang), total)
        latin = rasio_non_latin(" ".join(w["w"] for w in words)) <= 1.0

        pulih, gagal = _batch(key, path, lubang, latin)
        # Satu potongan berbahasa pemenang (sahutan yang tumpang tindih) bisa
        # mengunci seluruh gabungan dan mengosongkan sisanya. Kalau mayoritas
        # gagal, yang gagal saja dipecah dua lalu diulang sekali.
        if len(gagal) >= 4 and len(gagal) * 2 > len(lubang):
            tengah, sisa = len(gagal) // 2, []
            for bagian in (gagal[:tengah], gagal[tengah:]):
                p, g = _batch(key, path, bagian, latin)
                pulih += p
                sisa += g
            gagal = sisa

        hilang = sum(h["ucapan"] for h in gagal)
        (log.warning if hilang >= 10 else log.info)(
            "gemini: %d dari %d celah dipulihkan (+%d kata), %.0f detik bersuara tetap tanpa kata",
            len(lubang) - len(gagal), len(lubang), len(pulih), hilang,
        )
        return sorted(words + pulih, key=lambda w: w["s"])
    except Exception as e:  # noqa: BLE001
        log.warning("gemini: perbaikan ucapan yang dibuang gagal (%s) — %.0f detik bersuara "
                    "tanpa kata tetap kosong di caption", e, sum(h["ucapan"] for h in lubang))
        return words


def _panggil(key: str, path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    words = _minta(key, path)
    if not words:
        raise RuntimeError("Gemini Transcribe tidak mengembalikan timestamp kata")
    words = _perbaiki(key, path, words)
    if offset:
        words = [dict(w, s=w["s"] + offset, e=w["e"] + offset) for w in words]
    return words, sentences_from_words(words)


@retry(attempts=3, backoff=5.0)
def transcribe(path: Path, offset: float) -> tuple[list[dict], list[dict]]:
    idx, key = keypool.ambil("gemini")
    try:
        hasil = _panggil(key, path, offset)
    except Exception as e:
        keypool.lapor("gemini", idx, False, f"{type(e).__name__}: {e}")
        raise
    keypool.lapor("gemini", idx, True, f"{len(hasil[0])} kata")
    return hasil
