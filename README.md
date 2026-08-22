# Video Clipping Engine — Validation Build

Mengubah satu link YouTube panjang menjadi beberapa klip 9:16 siap posting,
lengkap dengan caption karaoke burned-in, judul, caption, dan hashtag.

Build ini adalah **versi validasi**. Tujuannya membuktikan seluruh pipeline
berjalan end-to-end, dan membuat kualitas seleksi momen bisa dinilai manusia:
tiap klip di halaman History menampilkan `score` dan `reason` dari LLM.

Belum termasuk (sengaja, sesuai PRD): stage context-research, crop per-shot
untuk b-roll, multi-tenant/auth/billing.

---

## Setup

Butuh **Python 3.12**, **ffmpeg** di PATH, dan **Docker**.

```bash
# 1. Dependency
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Infra
docker compose up -d          # postgres:16 + redis:7

# 3. Konfigurasi
copy .env.example .env        # lalu isi GROQ_API_KEY, OPENROUTER_API_KEY, R2_*
```

Jalankan di **dua terminal terpisah**:

```bash
venv\Scripts\python.exe main.py api       # http://localhost:8000
venv\Scripts\python.exe main.py worker
```

Buka `http://localhost:8000`, paste link YouTube, tentukan jumlah klip, submit.
Pantau progresnya di `/history`.

Worker sengaja tidak punya supervisor sendiri. Crash native dari MediaPipe/tflite
mematikan seluruh proses worker karena tidak ada work horse yang memisahkannya —
kalau perlu tahan banting, bungkus dengan `.bat` loop atau NSSM.

---

## Arsitektur

```
POST /jobs -> row Postgres (queued) -> job_id ke Redis (RQ)
           -> worker: orchestrator.run(job_id)
              download -> transcribe -> segment -> refine
                       -> caption -> crop -> render -> metadata
              -> upload R2 -> status done
```

Ini pipeline sekuensial berbasis workflow, **bukan agentic loop**. Urutan stage
ditentukan di kode; LLM hanya dipanggil untuk tugas sempit di Stage 3 (seleksi
momen) dan Stage 8 (metadata), tidak pernah memutuskan urutan eksekusi.

**Aturan dependency yang dipegang:**

- `pipeline/stages/*` tidak mengimpor `api/`, `web/`, `jobqueue/`, atau `db/`.
  Tiap stage bertanda tangan `run(ctx) -> dict`: baca yang dibutuhkan dari ctx,
  kembalikan field yang di-merge. Stage tidak tahu-menahu soal HTTP atau queue.
- `worker/orchestrator.py` satu-satunya yang memanggil stage berurutan dan
  menulis progress.
- `db/` murni schema + CRUD, nol logic AI.
- `utils/` dan `config/` foundational, tidak mengimpor folder lain.
- `api/routes.py` tidak pernah menjalankan pipeline secara sinkron.

Ganti model LLM cukup ubah `OPENROUTER_MODEL` di `.env` — Stage 3 dan 8
sama-sama lewat `llm/client.py`.

---

## Deviasi dari PRD

| PRD | Dipakai | Alasan |
|---|---|---|
| folder `queue/` | `jobqueue/` | `queue` menimpa modul stdlib. `python main.py` menaruh root project di `sys.path[0]`, jadi `import queue` dari `logging.handlers`, `concurrent.futures`, atau dependency mana pun akan nyasar ke folder kita — pipeline patah diam-diam. Scope commit untuk folder ini `jobqueue`. |
| Silero VAD | ffmpeg `silencedetect` | Silero menarik torch + torchaudio (~2.4GB wheel Windows) hanya untuk mencari batas hening. ffmpeg sudah jadi prasyarat dan menghasilkan daftar batas yang sama. |
| PySceneDetect | ffmpeg `select='gt(scene,..)'` | Alasan sama. PySceneDetect men-decode seluruh file satu jam; yang dibutuhkan cuma jendela ±1.5 detik di sekitar tiap batas (~3 detik decode per klip). |
| status `rendering -> done` | +`metadata`, +`uploading` | Stage 8 dan upload R2 memakan waktu nyata. Tanpa keduanya History menampilkan "rendering" padahal render sudah selesai. |
| — | +folder `assets/` | Model MediaPipe `.tflite` di-vendor, bukan diunduh saat runtime, supaya job tidak gagal gara-gara jaringan. |

Dua deviasi pertama disetujui sebelum implementasi; sisanya mengikuti alasan
yang sama.

---

## Kalibrasi

Semua ada di `.env` (default di `config/settings.py`). Ini knob yang benar-benar
perlu diputar saat hasilnya belum pas:

| Var | Default | Putar kalau |
|---|---|---|
| `SILENCE_NOISE_DB` | `-30` | Source ber-musik latar atau berisik → `-35`. |
| `SILENCE_MIN_DUR` | `0.25` | Terlalu banyak kandidat batas → `0.5`. |
| `SNAP_MAX_DRIFT` | `1.2` | Batas klip terasa meleset dari maksud LLM → kecilkan. |
| `MIN/MAX_CLIP_SEC` | `30` / `90` | Menyesuaikan platform tujuan. |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash-lite` | Seleksi momen terasa dangkal → model yang lebih besar. |

Kalau daftar silence kembali kosong, refine **tidak** menggeser batas sama
sekali. Itu perilaku yang benar dan disengaja: batas yang tidak di-snap masih
menghasilkan klip yang layak, sedangkan batas yang di-snap ke hening palsu
justru lebih buruk. Jangan melonggarkan threshold secara otomatis.

Bitrate audio 24kbps opus (`pipeline/stages/download.py`) menghasilkan ~10.8
MB/jam, jadi limit 25MB Groq baru tersentuh di sekitar 2.3 jam audio. Naikkan
ke `32k` kalau timestamp per kata terasa meleset.

---

## Test

```bash
venv\Scripts\python.exe -m pytest              # semua kecuali integration
venv\Scripts\python.exe -m pytest -m integration
```

Stage deterministik (`caption`, `segment`, `refine`) diuji dengan JSON sintetis,
tanpa perlu video. Stage yang butuh media (`crop`, `render`) memakai fixture
yang di-generate ffmpeg lewat `tests/fixtures/make_fixture.py` — tidak ada
binary video yang ikut masuk git.

Test `render` sengaja menjalankan ffmpeg sungguhan. Yang paling mungkin patah di
stage itu bukan logika Python-nya melainkan urutan argumen ffmpeg, dan salah
urut `-ss` tetap menghasilkan exit code 0 dengan caption yang lenyap.

End-to-end penuh butuh:

```bash
set TEST_YOUTUBE_URL=https://www.youtube.com/watch?v=...
venv\Scripts\python.exe -m pytest -m integration
```

---

## Catatan Windows

Hal-hal yang sudah ditangani di kode, dicatat di sini supaya tidak "diperbaiki"
balik oleh orang berikutnya:

- **RQ pakai `SimpleWorker`.** `rq.Worker` default memanggil `os.fork()` yang
  tidak ada di Windows. `SpawnWorker` juga tidak bisa meski docs menyebutnya
  Windows-friendly — ia mewarisi `os.wait4`/`os.killpg` dari `Worker`.
- **`job_timeout` diisi angka nyata, bukan `-1`.** `SimpleWorker` menjalankan
  job di thread dequeue sehingga tidak bisa heartbeat di tengah job, dan
  `get_heartbeat_ttl()` jatuh ke 420 detik saat timeout `-1`. Job 30 menit akan
  ditandai abandoned di menit ke-7.
- **Deadline ditegakkan sendiri** lewat `time.monotonic()` yang disuntikkan ke
  tiap `subprocess(timeout=...)`. `TimerDeathPenalty` milik RQ tidak bisa
  membunuh ffmpeg yang hang.
- **`silencedetect` butuh `-v info`.** Filter itu menulis hasilnya ke log level
  info; dengan `-v error` output-nya tertelan habis dan yang kembali adalah list
  kosong dengan exit code 0.
- **`-ss` sebelum `-i` saat render**, supaya pts filtergraph ter-rebase ke nol
  dan timestamp `.ass` yang relatif klip menjadi benar.
- **File `.ass` dirujuk dengan nama relatif + `cwd=workdir`.** Filter
  `subtitles` mem-parse argumennya sendiri, jadi path absolut Windows menuntut
  escape berlapis; nama relatif menghindarinya sama sekali.
- **`WORK_DIR` sengaja pendek** (`C:/work/<8 char job_id>`) karena MAX_PATH 260.
- Helper ffmpeg di stage di-import sebagai `ff`, bukan `run` — tiap stage
  mengekspor `run(ctx)` sendiri dan nama itu akan menimpa helper.

---

## Commit

Conventional Commits, scope = nama folder, deskripsi Bahasa Indonesia. Untuk
`pipeline/stages/`, scope-nya `pipeline/<nama-stage>`.

Commit yang mengubah kontrak data antar stage **wajib** punya body yang
menjelaskan apa yang berubah dan stage mana saja yang terdampak — itu titik
paling rawan pipeline patah diam-diam.
