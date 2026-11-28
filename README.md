# CAPIO

Ubah video panjang jadi beberapa klip pendek 9:16 siap posting (TikTok, Reels,
Shorts), lengkap dengan caption karaoke yang terbakar di video, judul, caption,
dan hashtag.

Gratis dan open source (MIT). Semua pemrosesan berat berjalan di komputer
sendiri; klip jadi mendarat sebagai file mp4 biasa di folder `clips/`. AI-nya
cuma satu: **Gemini**, pakai API key milikmu sendiri (tersedia tier gratis).

---

## Fitur

- **Sumber fleksibel:** link YouTube atau unggah video sendiri (MP4, MOV, MKV,
  WEBM, dan format lain yang dibaca ffmpeg).
- **Pilih momen otomatis:** Gemini mentranskrip video, memilih momen yang
  utuh secara gagasan, lalu menulis judul, caption, dan hashtag per klip.
- **Caption karaoke:** kata yang sedang diucapkan disorot; font, ukuran, warna,
  jumlah kata per tampilan, dan gaya sorotan bisa diatur per video, dengan
  preview yang dirender persis seperti hasil akhir.
- **Template siap pakai + Custom:** `mentahan`, `full_screen`,
  `pembicara_samping`, `blur_atas_bawah`, `kotak_tengah`, atau atur sendiri
  rasio, komposisi, latar, caption, dan hook.
- **Crop mengikuti wajah:** pembicara tetap di tengah frame vertikal.
- **Agent · Beta:** cari momen lewat chat ("cariin momen soal …"), tinjau
  kandidat beserta konteksnya, pertahankan yang cocok, lalu render.
- **Antrean job:** proses beberapa video, batalkan, atau coba ulang job gagal
  tanpa mengunduh ulang; bisa multi-worker.
- **Rotasi API key:** isi beberapa key Gemini sekaligus; dipakai bergiliran dan
  pindah otomatis saat kuota satu key habis.
- **Pemakaian & biaya:** token Gemini per model dan estimasi biayanya tercatat
  di halaman Setting.
- **Bersih otomatis (opsional):** hapus job dan hasil lama setelah sekian hari.

---

## Daftar isi

- [Mulai cepat](#mulai-cepat)
- [Halaman](#halaman)
- [Agent · Beta](#agent--beta)
- [Cara kerjanya](#cara-kerjanya)
- [Konfigurasi](#konfigurasi)
- [Kalibrasi](#kalibrasi)
- [Keamanan](#keamanan)
- [Arsitektur](#arsitektur)
- [Pengembangan](#pengembangan)
- [Batasan yang diketahui](#batasan-yang-diketahui)
- [Lisensi](#lisensi)

---

## Mulai cepat

**Yang dibutuhkan:**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac)
  atau Docker Engine (Linux). Tidak perlu Python, ffmpeg, maupun database.
- API key Gemini, gratis dari [Google AI Studio](https://aistudio.google.com/apikey).
- Komputer minimal 4 core/8 thread, RAM 8 GB, SSD kosong 20 GB. Unduhan
  pertama image sekitar 5 GB.

**1. Siapkan folder dan dua file konfigurasi.**

Windows (PowerShell):

```powershell
mkdir capio; cd capio
curl.exe -LO https://raw.githubusercontent.com/dataagentiv-gif/agentiv-capio/main/docker-compose.yml
curl.exe -L -o .env https://raw.githubusercontent.com/dataagentiv-gif/agentiv-capio/main/.env.example
```

Mac/Linux:

```bash
mkdir capio && cd capio
curl -LO https://raw.githubusercontent.com/dataagentiv-gif/agentiv-capio/main/docker-compose.yml
curl -L -o .env https://raw.githubusercontent.com/dataagentiv-gif/agentiv-capio/main/.env.example
```

Atau clone repo ini lalu salin `.env.example` menjadi `.env`. Hasilnya sama:
`docker compose up -d` menarik image jadi dari Docker Hub, tidak membangun dari
source.

**2. Jalankan.**

```bash
docker compose up -d
```

**3. Isi API key.** Buka **http://localhost:8000** → **Setting** → tab
**API Key**, tempel key Gemini, klik **Simpan**, lalu **Tes**. Setelah itu
langsung bisa submit video di halaman utama, atau coba **Agent · Beta**.

Bingung di satu halaman? Klik tombol **▶ Cara pakai** di samping judulnya untuk video
singkat cara pakainya, atau buka **http://localhost:8000/panduan** untuk
seluruh langkah dari awal.

Perintah lain yang sering dipakai:

```bash
docker compose logs -f worker   # ikuti proses job
docker compose down             # matikan; data tetap tersimpan
docker compose pull             # ambil versi terbaru…
docker compose up -d            # …lalu jalankan ulang
```

Catatan:

- Selama job berjalan, browser boleh ditutup, tapi Docker dan komputer harus
  tetap menyala (jangan sleep).
- **Jangan memakai `docker compose down -v`.** Opsi `-v` menghapus database,
  antrean, unggahan, dan data sesi Agent.
- Port bentrok ("port is already allocated")? Ubah di `.env`: `HOST_PORT`
  untuk 8000, `POSTGRES_HOST_PORT` untuk 5432, `REDIS_HOST_PORT` untuk 6379,
  lalu `docker compose up -d` lagi.
- Konfigurasi dari halaman Setting langsung berlaku tanpa restart (kecuali
  jumlah worker, lihat [Kinerja](#kinerja)).

### Tampilan output

Pada halaman Submit, pilih salah satu jalur berikut:

- **Template** untuk tampilan siap pakai dengan adjustment yang dibatasi oleh
  karakter template (`mentahan`, `full_screen`, `pembicara_samping`,
  `blur_atas_bawah`, dan `kotak_tengah`).
- **Custom** untuk mengatur rasio output, komposisi video, latar, caption, dan
  hook dalam satu konfigurasi yang berlaku untuk seluruh klip job.

Setiap job menyimpan snapshot konfigurasi saat dikirim, sehingga perubahan
default di versi berikutnya tidak mengubah hasil job lama. Caption panjang,
source tanpa wajah, dan rasio landscape/square memakai fallback aman agar
render tetap valid.

### Tanpa Docker

Butuh **Python 3.12** dan **ffmpeg** di PATH.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt   # bin/python di Linux
docker compose up -d postgres redis
cp .env.example .env    # Windows: copy .env.example .env
```

Lalu di dua terminal terpisah:

```bash
venv/Scripts/python main.py api
venv/Scripts/python main.py worker
```

> **Dijalankan di laptop sendiri, bukan VPS.** yt-dlp kena bot-detection
> YouTube yang jauh lebih galak dari datacenter, jadi siapkan cookies kalau
> memang harus di server. Transkrip sendiri tidak jadi penghalang, karena
> Gemini tidak memblokir IP datacenter.

---

## Halaman

| Halaman | Isi |
|---|---|
| **Submit** `/` | Link YouTube atau unggah video, jumlah klip, lalu pilih Template atau Custom. Penyesuaian dan preview mengikuti pilihan tersebut; konfigurasi disimpan bersama job. |
| **Proses** `/process` | Tab Berjalan dan Riwayat, progres tiap tahap, statistik klip, pencarian/filter, ringkasan konfigurasi, pembatalan job berjalan, dan penjelasan job gagal. Job gagal dapat dicoba ulang jika aman. |
| **Hasil** `/results` | Klip selesai dengan preview, judul, caption, hashtag, dan ringkasan konfigurasi; bisa diputar, diunduh per klip atau sekaligus per job, dan dihapus. |
| **Panduan** `/panduan` | Delapan langkah bergambar dari isi API key sampai render klip Agent. Tombol **▶ Cara pakai** di tiap halaman membuka langkah yang relevan. |
| **Agent · Beta** `/agent` | Cari momen lewat chat untuk satu video; lihat [Agent · Beta](#agent--beta). |
| **Setting** `/settings` | Tab API Key, Klip, Kinerja, dan Infra. API Key juga menampilkan pemakaian Gemini per model dan estimasi setara tarif API Standard berbayar. |

Klip juga bisa diambil langsung dari folder `clips/<job-id>/` lewat file
manager — tidak perlu lewat aplikasi.

Tombol **Hapus** membuang berkasnya dari disk, bukan sekadar barisnya dari
layar. Menghapus job juga membersihkan folder kerjanya, yang menyimpan video
sumber mentah dan biasanya jadi penyebab utama disk penuh.

Nomor versi yang terpasang (`vX.Y.Z`) tampil kecil di navigasi, berguna saat
melaporkan masalah. Bandingkan dengan rilis terbaru di Docker Hub
(`agentiv/capio`) atau tab Releases/commit repo ini.

---

## Agent · Beta

Mode chat untuk satu video, dibuka dari tombol **Agent · Beta** di halaman
Submit atau langsung di `/agent`.

1. **Siapkan video:** tempel link YouTube atau unggah berkas. CAPIO mengunduh,
   mentranskrip, membuat preview, dan menyusun **peta topik** (ringkasan isi
   video per bagian) sekali saja.
2. **Arahkan lewat chat:** misalnya *"cariin 2 momen soal kenapa gaji naik tapi
   tetap ga kaya, 30–60 detik"*. Agent mencari di transkrip, membaca konteks
   sebelum dan sesudahnya, lalu mengusulkan kandidat yang awal dan akhirnya
   jatuh di batas kalimat.
3. **Tinjau:** putar kandidat beserta konteksnya, lalu **Pertahankan**,
   **Tolak**, atau minta revisi lewat chat. Agent mengingat arahanmu di
   putaran berikutnya.
4. **Render:** pilih sampai 20 kandidat yang dipertahankan, lalu render dengan
   template atau Custom seperti biasa. Hasilnya muncul di halaman Hasil.

Satu putaran biasanya selesai dalam 1–2 menit. Gangguan sementara dari Gemini
(sibuk, kuota habis) ditangani dengan pindah ke key/model lain; kalau tetap
gagal, pesan dan tombol **Coba ulang** muncul di bawah percakapan, tanpa
kehilangan kandidat sebelumnya. Data sesi tersimpan di volume `capiodata`;
hapus sesi lewat menu **•••** untuk membebaskan disk.

Status **Beta**: kualitas pilihan momen sudah baik, tapi alurnya masih bisa
berubah. Detail teknis ada di [`docs/AGENT_EXPERIMENT.md`](docs/AGENT_EXPERIMENT.md).

---

## Cara kerjanya

Pipeline sekuensial sembilan tahap termasuk unggah/unduh. Urutannya tetap dan
ditentukan di kode; Gemini dipakai untuk transkrip, seleksi momen, dan metadata,
tetapi tidak pernah memutuskan alur pipeline.

| # | Tahap | Alat | Hasil |
|---|---|---|---|
| 1 | Sumber | upload atau yt-dlp + ffmpeg | video sumber dan audio kerja |
| 2 | Transkrip | Gemini Transcribe | kata bertimestamp |
| 3 | Seleksi momen | Gemini LLM | kandidat klip, skor, alasan, dan hook |
| 4 | Perapian batas | ffmpeg | batas disesuaikan ke jeda alami |
| 5 | Crop | MediaPipe | posisi wajah dan perpindahan crop bila template memerlukannya |
| 6 | Caption | generator `.ass` atau overlay motion | layer caption mengikuti timestamp kata |
| 7 | Render | ffmpeg | komposisi video, caption, dan audio |
| 8 | Metadata | Gemini LLM | judul, caption deskripsi, hashtag |
| 9 | Simpan | storage lokal | file ke `clips/<job-id>/` dan status job |

Tiga hal yang membuat titik potongnya masuk akal:

**Transkrip disajikan ke LLM per kalimat, bukan per kata**, memakai teks
bertanda baca. Tanpa titik dan koma, kalimat yang menggantung terlihat persis
sama dengan kalimat yang sudah selesai.

**Durasi jeda bicara ikut ditandai** (`jeda 1.4s`), dihitung dari selisih
timestamp antar kata. Tanpa itu, LLM tidak bisa membedakan orang yang selesai
berpikir dari orang yang menarik napas di tengah argumen.

**Batas akhir digeser ke jeda paling panjang di sekitarnya**, bukan yang paling
dekat. Hening 1,5 detik adalah penutup gagasan; hening 0,3 detik cuma tarikan
napas.

---

## Konfigurasi

Semua lewat halaman **Setting**. Yang ditulis di sana masuk ke `.env` di folder
project, jadi bisa juga disunting manual kalau lebih suka.

### Gemini

CAPIO memakai Gemini untuk transkrip, seleksi momen, dan metadata. Beberapa
API key boleh disimpan dan dipakai bergiliran. Model LLM memakai urutan bawaan
hasil pengujian; `GEMINI_MODELS` dapat mengatur urutan model sendiri. Model
transkripsi tetap terpisah dari model chat.

Ini pilihan yang paling terasa hasilnya untuk transkrip, karena **caption
terbakar permanen di video**. Transkrip yang meleset kelihatan oleh penonton
dan tidak bisa diperbaiki setelah render. Gemini 3.5 Transcribe punya satu
sifat yang perlu ditambal: model ini hanya menulis **satu bahasa per
request** dan diam-diam membuang kalimat bahasa lain — 28–31% detik bicara
hilang pada video Indonesia berkutip Inggris. CAPIO menambalnya: celah
bersuara tanpa kata dideteksi ffmpeg lalu ditranskrip ulang sekaligus dalam
satu request tambahan, sisa 2–3% (setara video Indonesia murni). Konten
Indonesia murni tetap 1 request.

Kuota gratisnya per PROJECT Google Cloud, bukan per key — key tambahan cuma
menaikkan atap kalau dibuat di project yang berbeda (terukur: dua key satu
project habis bersamaan di 28 request gabungan). Transkrip: ~25 request/hari
per project. LLM: pipeline memakai dua panggilan per video, dan kuota gratis
chat completions (1.000 permintaan/hari) setara sekitar 500 video per hari.

**Kenapa bukan Groq atau ElevenLabs.** Groq dibuang duluan: tiga video
Indonesia berisi istilah Inggris ditranskrip Groq dan ElevenLabs dari file
audio yang sama persis, dan **29,6% keluaran Groq adalah teks Jepang** pada
satu dari tiga video — Whisper berpindah bahasa lalu mengarang panjang lebar,
dua video lain nol. Kalimat Inggris juga diterjemahkan alih-alih ditranskrip:
*"Tools like Google Analytics"* keluar sebagai *"Tua seperti analitik"*.
ElevenLabs sempat jadi default (akurat, tanpa blokir IP) sampai tambalan di
atas terbukti: free tier-nya tembok bulanan (~15 video/bulan) jauh lebih
sempit dari batas laju harian Gemini, dan kebanyakan pemakai CAPIO mengandalkan tier gratis.
`ASR_PROVIDER`, `LLM_PROVIDER`, `ELEVENLABS_*`, dan `OPENROUTER_*` yang masih
tertulis di `.env` lama diabaikan tanpa error — tidak ada yang perlu
disunting setelah update.

### Tampilan dan caption

CAPIO menyediakan lima template (`mentahan`, `full_screen`,
`pembicara_samping`, `blur_atas_bawah`, `kotak_tengah`) serta jalur Custom.
Adjustment hanya muncul pada mode yang mendukungnya dan konfigurasi lengkap
disimpan sebagai snapshot per job. `mentahan` mempertahankan source tanpa
caption; Custom mengatur rasio, komposisi video, latar, caption, dan hook.
Spesifikasi visual dan adjustment ada di [`docs/template.md`](docs/template.md), katalog
kode di `pipeline/templates.py`.

Full Screen dan Blur atas-bawah melacak wajah dari beberapa sampel sepanjang
klip. Crop dapat bergeser ketika wajah utama keluar dari area aman; saat wajah
tidak terdeteksi, renderer memakai titik tengah source. Motion caption khusus
Pembicara di samping dan Kotak tengah dirender sebagai overlay transparan,
sementara caption lain memakai subtitle `.ass`.

### Paket template

Template khusus (mis. gaya caption brand) tidak perlu mengubah kode CAPIO. Taruh
file `*.json` di folder `templates_extra/` (bisa diganti lewat `TEMPLATE_PACK_DIR`):

```json
{"id": "nama_template", "title": "Nama Template", "description": "Satu kalimat.",
 "adjustments": {"caption_color": "F8B818", "active_text_color": "F8B818",
                 "caption_italic": true, "caption_px": 87, "hook": true, "hook_block": "frame"}}
```

`adjustments` memakai kunci Custom (lihat `CUSTOM_DEFAULTS` di `pipeline/templates.py`),
divalidasi saat API start; file yang tidak valid dilewati dengan pesan di log. Template
paket tampil paling depan di halaman Submit dan dirender lewat jalur Custom dengan
nilai yang dikunci. Tambahkan `"brand": {"name": "Nama Brand", "color": "800010"}` untuk
edisi brand: nama brand tampil di header dan tab **Khusus Brand** berisi template-nya.
Tanpa paket brand, tab itu menjadi tombol pemesanan template khusus ke Agentiv lewat
WhatsApp (`AGENTIV_WA`). Untuk distribusi, buat repo terpisah berisi `templates/` dan
Dockerfile `FROM agentiv/capio:<versi>` yang menyalinnya ke `/app/templates_extra/`.

### Pemakaian Gemini

Settings menampilkan panggilan dan token Gemini per model. Catatan lokal
mencakup model, tahap, jumlah token, waktu, status, dan penanda estimasi; prompt,
transkrip, respons mentah, serta API key tidak disimpan dalam tabel pemakaian.
Nilai biaya di UI adalah pembanding terhadap tarif API Standard berbayar, bukan
tagihan BYOK. Tarif per model mengikuti [harga resmi Gemini](https://ai.google.dev/gemini-api/docs/pricing)
dan tanggal pemeriksaannya ditampilkan. Alias model
`-latest` memakai asumsi harga yang ditandai; riwayat lama tanpa rincian input
dan output tetap masuk total token, tetapi tidak diberi estimasi biaya.

### Auto clear

Tab **Infra** bisa membuang task dan hasil lama secara otomatis — **mati secara
bawaan**. Umur dihitung dari tanggal video disubmit, dicek tiap jam oleh proses
API, dan video yang sedang antre atau diproses tidak pernah disentuh.

| Target | Yang dibuang |
|---|---|
| `keduanya` | Job beserta semua klip dan folder kerjanya — sama dengan tombol Hapus. |
| `task` | Hanya job yang tidak punya klip (gagal, atau klipnya sudah dibuang). Job yang masih punya klip dibiarkan, supaya tidak ada klip yang hilang dari halaman Hasil sementara berkasnya tertinggal di disk. |
| `hasil` | Berkas klip saja. Riwayat job tetap ada di halaman Proses. |

### Kinerja

Satu job diproses sekaligus secara bawaan (`WORKER_MODE=single`). Bisa
diganti ke `multi` di halaman Setting untuk memproses beberapa job
bersamaan — lebih cepat kalau CPU-nya cukup, tapi setiap job menjalankan
ffmpeg yang memakai semua core tanpa batas, jadi di mesin kecil job
paralel bisa membuat semuanya lebih lambat, bukan lebih cepat. Naikkan
`WORKER_COUNT` bertahap sambil memperhatikan beban CPU. Keduanya baru berlaku
setelah worker di-restart (`docker compose restart worker`).

Patokan perangkat: minimum 4 core/8 thread, RAM 8 GB, dan SSD kosong 20 GB;
lebih nyaman 6 core/12 thread dengan RAM 16 GB. Untuk multi-worker, siapkan
sekitar 8 logical thread dan cadangan RAM 1,2 GB per worker aktif. Mulai dari 2
worker. Multi-worker menaikkan jumlah video yang diproses bersamaan, **bukan**
mempercepat satu video.

---

## Kalibrasi

Semua ada di halaman Setting → Klip (angka hening dan geser batas ada di bagian
*Lanjutan*). Ini yang benar-benar perlu diputar kalau hasilnya belum pas:

| Pengaturan | Default | Putar kalau |
|---|---|---|
| Ambang hening | `-30` dB | Source ber-musik latar → **NAIKKAN** ke `-20`, jangan turunkan |
| Durasi hening minimum | `0.25` s | Terlalu banyak kandidat batas → `0.5` |
| Pergeseran batas maksimum | `1.2` s | Batas klip terasa meleset dari maksud LLM → kecilkan |
| Durasi klip | `30`–`90` s | Menyesuaikan platform tujuan |
| Model LLM | flash-lite | Seleksi momen terasa dangkal → model lebih besar |

Kalau tidak ada hening terdeteksi sama sekali, batas klip **tidak** digeser.
Itu perilaku yang disengaja: batas yang tidak digeser masih menghasilkan klip
yang layak, sedangkan batas yang digeser ke hening palsu justru merusak.

**Ambang hening dinaikkan, bukan diturunkan, saat ada musik latar.** Ini
berlawanan dengan naluri, jadi worker ikut menyebutkannya di log. Musik
menaikkan lantai kebisingan — ambang `-30` dB berarti "dianggap hening kalau di
bawah −30 dB", dan kalau musiknya sendiri duduk di −24 dB, tidak ada satu momen
pun yang pernah turun ke sana. Menurunkannya ke −35 atau −40 membuat syaratnya
makin mustahil. Diukur pada audio bicara yang sama, dicampur musik bertingkat:

| Musik latar | −30 dB | −25 dB | −20 dB | −15 dB | −10 dB |
|---|---|---|---|---|---|
| tanpa musik | 7 | 13 | 18 | 25 | 39 |
| −30 dB | 2 | 9 | 18 | 28 | 41 |
| −24 dB | **0** | 2 | 15 | 27 | 40 |
| −18 dB | **0** | 0 | 1 | 24 | 39 |
| −12 dB | **0** | 0 | 0 | 0 | 32 |

Angkanya jumlah jeda yang terdeteksi dalam 3 menit. Baca menyamping: makin keras
musiknya, makin ke kanan ambang yang dibutuhkan.

---

## Keamanan

Halaman Setting bisa menulis API key, jadi ada beberapa pembatas yang sebaiknya
dipahami sebelum diubah.

**Server hanya mendengar di localhost.** Di Docker, port dipublikasikan sebagai
`127.0.0.1:8000:8000` — bukan ke seluruh jaringan.

**Isi `AUTH_TOKEN` kalau perlu diakses dari luar localhost.** Begitu terisi,
semua halaman meminta HTTP Basic (username diabaikan, password = token itu).
Tanpa itu, siapa pun yang bisa menjangkau server dapat melihat provider mana
yang terisi dan menimpa key-nya — tidak ada autentikasi bawaan.

**Nilai rahasia tidak pernah dikirim utuh ke browser**, hanya bentuk ter-mask
plus penanda terisi/kosong.

**Port Postgres dan Redis diikat ke `127.0.0.1` di compose. Jangan hapus awalan
itu.** Tanpa awalan alamat, Docker membuka port ke semua interface, dan Redis
di sini berjalan tanpa password. Akibatnya bukan sekadar data terbaca: RQ
menyimpan nama fungsi sebagai string dotted-path yang di-import worker apa
adanya, jadi siapa pun yang bisa menjangkau Redis dapat mengantre job berisi
fungsi apa saja — eksekusi kode jarak jauh di mesin yang menjalankan worker.

`.env` berisi kredensial dan sudah masuk `.gitignore`. Pastikan tetap begitu.

---

## Arsitektur

```
POST /jobs → row Postgres (queued) → job_id ke Redis (RQ)
           → worker: orchestrator.run(job_id)
              sumber → transkrip → seleksi → perapian batas
                     → crop → caption → render → metadata
              → simpan ke clips/ → status done
```

```
main.py               entry point tunggal: api | worker
config/               settings + baca-tulis .env
api/                  REST + penyaji halaman
web/                  template Jinja2 + aset
worker/               orchestrator (satu-satunya pemanggil stage)
pipeline/stages/      stage pipeline (urutan dikelola orchestrator)
asr/                  transkrip (gemini)
llm/                  LLM (gemini)
storage/              penyimpanan klip lokal
db/                   skema + CRUD
jobqueue/             adapter Redis + RQ
utils/                logging, retry, helper ffmpeg
tests/
```

Aturan yang dipegang konsisten dan sebaiknya dijaga:

- **`pipeline/stages/*` tidak mengimpor `api/`, `web/`, `jobqueue/`, atau
  `db/`.** Tiap stage bertanda tangan `run(ctx) -> dict`: baca yang dibutuhkan
  dari ctx, kembalikan field yang di-merge. Stage tidak tahu-menahu soal HTTP
  atau antrean.
- **`worker/orchestrator.py` satu-satunya** yang memanggil stage berurutan dan
  menulis progress.
- **`db/` murni skema + CRUD**, nol logika AI.
- **`utils/` dan `config/` foundational** — tidak mengimpor folder lain.
- **`api/routes.py` tidak pernah menjalankan pipeline secara sinkron.**

Folder `asr/` dan `llm/` tetap dipisah karena kontrak transkrip dan chat berbeda,
tetapi provider aktif keduanya sekarang hanya Gemini. `storage/` sengaja satu
file; lapisan pemilih untuk satu implementasi hanyalah indirection.

> Folder antrean bernama `jobqueue/`, bukan `queue/`. `queue` adalah nama modul
> stdlib Python, dan root project berada di `sys.path[0]` saat `main.py`
> dijalankan — `import queue` dari dependency mana pun akan nyasar ke folder
> project dan memecahkan pipeline diam-diam.

## Pengembangan

Membangun image dari source di repo ini (bukan menarik dari Docker Hub):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Tanpa `--build`, compose memakai image lama dan perubahan kode tidak terpakai.

Video panduan (`web/static/panduan/*.webm`) direkam ulang dengan
`scripts/rekam_panduan.py` (Playwright + Google Chrome) terhadap instance demo
yang bersih; petunjuk lengkap ada di docstring script tersebut.
Dokumen desain dan catatan teknis lain ada di folder [`docs/`](docs/).

```bash
venv/Scripts/python -m pytest          # semua kecuali integration
venv/Scripts/python -m pytest -m integration
```

Test yang butuh Postgres/Redis akan di-skip sendiri kalau infra tidak jalan.
End-to-end penuh butuh video nyata:

```bash
set TEST_YOUTUBE_URL=https://www.youtube.com/watch?v=...
venv/Scripts/python -m pytest -m integration
```

Stage deterministik diuji dengan data sintetis. Stage yang butuh media memakai
fixture yang di-generate ffmpeg, jadi tidak ada file video besar di repo.

Test render sengaja menjalankan ffmpeg sungguhan: yang paling mungkin patah di
sana bukan logika Python-nya melainkan urutan argumen ffmpeg, dan salah urut
`-ss` tetap menghasilkan exit code 0 dengan caption yang lenyap.

### Konvensi commit

Conventional Commits dengan scope berbasis folder (`feat(pipeline/render): …`).
Commit yang mengubah kontrak data antar stage wajib punya body yang menjelaskan
apa yang berubah dan stage mana saja yang terdampak — itu titik paling rawan
pipeline patah tanpa error.

---

## Batasan yang diketahui

Dirancang untuk **talking-head berbahasa Indonesia**. Di luar itu tetap jalan,
tapi hasilnya belum tentu layak — dan yang berikut ini sudah diukur, bukan
diperkirakan.

- **Bukan talking-head** (screencast, gameplay, animasi) dibingkai center karena
  tidak ada wajah untuk diikuti. Pada sumber 16:9 itu **memotong 68% lebar**.
  Diuji pada satu tutorial Excel: teks menu dan label angka terpotong di tengah
  kata. Job-nya tetap selesai, jadi worker mencatat peringatan `TIDAK ADA WAJAH`
  ketika seluruh klip jatuh ke center — periksa hasilnya sebelum diposting.
- **Jumlah kandidat menyusut pada video sangat panjang** — 3 dari target 5 pada
  podcast 2,4 jam, sementara video 15 menit biasanya 7–9.

  Catatan penting: gejala kedua yang dulu tercatat di sini — index meleset
  11–45 detik dari kalimat yang dikutip model sendiri — **ternyata bukan soal
  panjang video, dan sudah diperbaiki.** Penyebabnya label index di transkrip
  yang kita kirim sendiri: `_anchors` membuang duplikat lewat `set()`, jadi
  begitu dua kalimat jatuh di kata yang sama, seluruh label sesudahnya
  menempel pada kalimat berikutnya. Terukur pada podcast 27 menit: 540 kalimat,
  538 anchor, **518 dari 540 baris salah label**. Sesudah diperbaiki, ketepatan
  index naik dari 0/7 jadi 8/9 pada transkrip dan model yang sama.

  Penyusutan jumlah kandidat belum diukur ulang sesudah perbaikan itu — bisa
  jadi ikut membaik, bisa jadi sebab yang berbeda.
- **Pelacakan crop mengikuti posisi wajah, bukan giliran bicara.** Full Screen
  dan Blur atas-bawah dapat menggeser crop ketika wajah utama keluar dari area
  aman. Sistem belum mengenali siapa yang sedang berbicara; jika dua orang
  berjauhan, crop tetap memilih satu wajah.
- **Chunking transkrip** memotong tepat di menit ke-20 tanpa menyesuaikan ke
  jeda bicara. Gemini menolak word timestamp di atas 30 menit per request,
  jadi cabang ini aktif untuk setiap audio **di atas 20 menit** — bukan cuma
  video sangat panjang seperti pada provider sebelumnya. Satu kata terpotong
  di tiap batas chunk; diverifikasi end-to-end pada podcast 2,44 jam.
- **Tidak ada autentikasi bawaan** selain `AUTH_TOKEN` opsional.

---

## Lisensi

MIT, lihat [`CAPIO-LICENSE.txt`](CAPIO-LICENSE.txt): bebas dipakai, diubah, dan dibagikan ulang, termasuk untuk komersial, selama teks lisensinya ikut disertakan. Font pihak ketiga mengikuti lisensinya masing-masing di [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt).
