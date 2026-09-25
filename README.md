# CAPIO

Ubah video panjang jadi beberapa klip pendek 9:16 siap posting — lengkap dengan
caption karaoke yang terbakar di video, judul, caption, dan hashtag.

Sumbernya boleh **link YouTube** atau **berkas video sendiri** yang diunggah
lewat halaman Submit (MP4, MOV, MKV, WEBM, dan wadah lain yang bisa dibaca
ffmpeg). Berkas yang diunggah melewati yt-dlp sepenuhnya, jadi ia tidak
tersentuh bot-detection YouTube maupun urusan cookies.

Semua pemrosesan berat berjalan di mesin sendiri. Klip jadi mendarat sebagai
file mp4 biasa di folder `clips/`, bukan di storage cloud mana pun.

CAPIO memakai **satu layanan AI: Gemini**, untuk transkrip, pemilihan momen,
dan metadata. Satu key dapat menjalankan semuanya dan tersedia tingkat gratis
untuk pemakaian ringan.

---

## Daftar isi

- [Cara pakai](#cara-pakai)
- [Halaman](#halaman)
- [Cara kerjanya](#cara-kerjanya)
- [Konfigurasi](#konfigurasi)
- [Kalibrasi](#kalibrasi)
- [Keamanan](#keamanan)
- [Arsitektur](#arsitektur)
- [Pengembangan](#pengembangan)
- [Batasan yang diketahui](#batasan-yang-diketahui)

---

## Cara pakai

> Panduan publik instalasi, update, dan multi-worker tersedia di portal Agentiv.
> Tutorial penggunaan harian dan cara memilih style dibahas di video channel
> pribadi Agentiv, agar dokumentasi bisnis tetap ringkas.

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

### Dengan Docker (disarankan)

Cuma butuh **Docker**. Tidak perlu Python, ffmpeg, maupun database.

Untuk pemakai rilis, unduh `capio.zip` dari tab **Cara pakai** di portal
Agentiv, ekstrak, lalu jalankan dari folder hasil ekstraknya:

```bash
docker compose up -d
```

Perintah clone di bawah khusus pengembangan dari source repo:

```bash
git clone <repo-ini>
cd video-clipper
cp .env.example .env        # copy di Windows
docker compose up -d
```

Buka **http://localhost:8000**, lalu ke halaman **Setting** untuk mengisi API
key Gemini dan license key (petunjuknya ada di halaman itu). Klik **Simpan**,
lalu **Tes** untuk memastikan key Gemini benar dan verifikasi lisensinya.
Setelah itu langsung bisa submit video.

```bash
docker compose logs -f worker   # ikuti prosesnya
docker compose down             # matikan; data tetap tersimpan
```

Saat job berjalan, browser boleh ditutup tetapi Docker, container CAPIO, dan
komputer harus tetap menyala; komputer juga tidak boleh masuk mode sleep.
Matikan CAPIO dengan `docker compose down` hanya setelah job selesai.

Update rilis tanpa menghapus data:

```bash
docker compose pull
docker compose up -d
```

CAPIO memeriksa versi terbaru saat API menyala dan setiap satu jam setelahnya.
Jika ada rilis baru, petunjuk update muncul sebagai banner di semua halaman.

**Jangan memakai `docker compose down -v`.** Opsi `-v` menghapus volume
Postgres, Redis, source upload, install ID, dan data lisensi. Perintah update di
atas mempertahankan semuanya.

Kalau port 8000 sudah dipakai proses lain, ubah `HOST_PORT` di `.env` lalu
`docker compose up -d`. Port di dalam container tetap 8000 — yang berubah hanya
sisi host.

Ubah **kode** perlu `docker compose up -d --build`. Tanpa `--build`, compose
memakai image lama dan perubahan tidak terpakai — tanpa error, cuma perilaku
yang tidak berubah. Ubah **konfigurasi** lewat halaman Setting tidak perlu
rebuild: worker membaca ulang `.env` di awal tiap job.

`docker-compose.yml` yang dikirim ke client tidak punya `build:` sama sekali
(mereka menarik image jadi dari Docker Hub). `docker-compose.override.yml` di
repo ini yang mengembalikannya untuk pengembangan lokal — dibaca Compose
otomatis, tidak perlu flag tambahan, dan tidak ikut ke paket client.

### Tanpa Docker

Butuh **Python 3.12** dan **ffmpeg** di PATH.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt   # bin/python di Linux
docker compose up -d postgres redis
cp .env.example .env
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
| **Submit** `/` | Link YouTube atau unggah berkas sendiri, jumlah klip, pemilih layout dengan contoh videonya, dan knob gaya caption — semuanya per video. Begitu satu layout dipilih, halaman melebar dan panel pratinjau caption (dirender lewat jalur yang sama dengan produksi, bukan tiruan CSS) muncul di sebelah kanan. Strip di atas menunjukkan provider aktif, status lisensi, dan apakah konfigurasi sudah lengkap, jadi yang bolong ketahuan *sebelum* submit, bukan belasan menit kemudian. |
| **Proses** `/process` | Job berjalan dengan penanda 9 tahap dan peringatan agar Docker/komputer tetap menyala. Job gagal menampilkan sebab, detail tahap terakhir, tombol **Proses ulang**, dan tombol hapus. Retry memakai source, jumlah klip, layout, serta gaya yang sama—upload lokal tidak perlu diunggah ulang. |
| **Hasil** `/results` | Klip jadi, bisa diputar, diunduh, atau dihapus — satu per satu maupun sekaligus per job. |
| **Setting** `/settings` | Semua konfigurasi dalam lima tab — API Key, Lisensi, Klip, Kinerja, Infra — dengan tombol tes Gemini dan verifikasi lisensi. Penjelasan tiap setelan tersembunyi di balik ikon `?`, dan setelan yang jarang disentuh (model, kalibrasi) dilipat di bagian *Lanjutan*. |

Klip juga bisa diambil langsung dari folder `clips/<job-id>/` lewat file
manager — tidak perlu lewat aplikasi.

Tombol **Hapus** membuang berkasnya dari disk, bukan sekadar barisnya dari
layar. Menghapus job juga membersihkan folder kerjanya, yang menyimpan video
sumber mentah dan biasanya jadi penyebab utama disk penuh.

Dua hal muncul di **semua halaman**, bukan cuma satu: nomor versi yang
terpasang (`vX.Y.Z`, kecil di sebelah logo Agentiv di nav — buat
troubleshooting, bukan branding) dan banner "versi baru tersedia" kalau
Agentiv sudah mengumumkan rilis lebih baru dari yang sedang berjalan.
Keduanya cuma informasi; tidak ada yang diblokir kalau belum update.

---

## Cara kerjanya

Pipeline sekuensial sembilan tahap. Urutannya tetap dan ditentukan di kode; LLM
dipanggil untuk dua tugas sempit saja dan tidak pernah memutuskan alur.

| # | Tahap | Alat | Hasil |
|---|---|---|---|
| 1 | Unduh | yt-dlp + ffmpeg | `source.mp4`, `audio.ogg` (16kHz mono opus) |
| 2 | Transkrip | Gemini Transcribe | kata + kalimat, bertimestamp |
| 3 | Seleksi momen | LLM | kandidat klip + skor + alasan |
| 4 | Geser batas | ffmpeg | batas dipindah ke jeda alami terdekat |
| 5 | Caption | generator `.ass` | caption karaoke per kata |
| 6 | Crop | MediaPipe | jendela 9:16 mengikuti posisi wajah |
| 7 | Render | ffmpeg | mp4 1080×1920, caption terbakar |
| 8 | Metadata | LLM | judul, caption, hashtag |
| 9 | Simpan | — | file ke `clips/<job-id>/` |

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

Satu key, dua tugas: transkrip (Stage 2) lewat `GEMINI_API_KEYS`, lalu seleksi
momen dan metadata (Stage 3 & 8) lewat key yang sama. Bukan pilihan di antara
beberapa provider — CAPIO cuma jalan dengan Gemini.

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
sempit dari batas laju harian Gemini, dan target market CAPIO sensitif harga.
`ASR_PROVIDER`, `LLM_PROVIDER`, `ELEVENLABS_*`, dan `OPENROUTER_*` yang masih
tertulis di `.env` lama diabaikan tanpa error — tidak ada yang perlu
disunting setelah update.

### Lisensi

CAPIO butuh **license key** untuk memproses video baru — diisi lewat halaman
**Setting**, bagian Lisensi. Kosong atau tidak aktif berarti aplikasi tetap
jalan normal: klip yang sudah ada tetap bisa dibuka, diputar, dan diunduh,
cuma submit job **baru** yang diblokir sampai key-nya terverifikasi.

Gerbangnya satu fungsi (`license.boleh_submit()`), disengaja begitu —
lihat komentar di `license/__init__.py` sebelum menyentuhnya. Verifikasi
tidak pernah memblokir halaman Setting sendiri: kalau iya, key tidak akan
pernah bisa dimasukkan sama sekali.

### Tampilan

Lima bentuk klip (`penuh`, `duo`, `kotak`, `samping`, `ori`) plus gaya caption
(font, ukuran, jumlah kata per tampilan, huruf besar, gaya kata aktif) —
dipilih **per video** di halaman Submit, bukan sekali untuk semua video.
Nilai di halaman Setting cuma jadi nilai awal yang tampil pertama kali.
Detail tiap layout ada di `pipeline/layout.py`.

**Gaya kata aktif** ada tiga: *warna teks* (kata yang diucapkan cuma berubah
warna), *blok* (blok bersudut tumpul di belakang kata itu), dan *blok +
membesar* (blok, dan katanya membesar 1,08×). Warna blok, warna teks di dalam
blok, radius sudut, dan padding bisa diatur. Karena libass tidak punya latar per
kata yang bersudut tumpul, di dua gaya blok posisi tiap kata dihitung sendiri
dari metrik font (`pipeline/metrik.py`) dan bloknya digambar sebagai vector
drawing di titik tengah yang sama dengan katanya.

Layout **Pembicara di samping** (`samping`) bisa menaruh pembicara di kiri atau
kanan, dengan gradasi pada sisi sebaliknya. Kepekatan ujung (0–100%) dan luasnya
(20–80% lebar) bisa digeser per
video di halaman Submit.

Layout **Podcast 2 Orang** (key kompatibilitas: `duo`) mengambil 20 sampel
sepanjang klip. Jika tepat dua wajah terlihat stabil pada sedikitnya 90% sampel,
posisi median keduanya dikunci: pembicara kiri di panel atas dan kanan di panel
bawah sepanjang klip. Video multicam, close-up bergantian, atau tiga orang
otomatis memakai `penuh`, dan halaman Hasil menampilkan peringatan fallback.

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
              unduh → transkrip → seleksi → batas
                    → caption → crop → render → metadata
              → simpan ke clips/ → status done
```

```
main.py               entry point tunggal: api | worker
config/               settings + baca-tulis .env
api/                  REST + penyaji halaman
web/                  template Jinja2 + aset
worker/               orchestrator (satu-satunya pemanggil stage)
pipeline/stages/      sembilan tahap, masing-masing satu file
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

---

## Pengembangan

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
- **Source lebih sempit dari 9:16** (misalnya 9:20) akan ter-stretch vertikal.
  Perbaikannya mode `fit` dengan latar blur; worker memperingatkannya di log.
- **Satu crop per klip, bukan per shot.** Memadai untuk talking-head satu orang.
  Pada video wawancara yang berpindah kamera antar pembicara, **wajah utama
  berada di luar bingkai sekitar 18% waktu** — **diukur SEKALI, pada satu video
  7 menit**, 120 frame sampel, memakai jendela per 60 detik persis seperti cara
  crop bekerja. Perlakukan 18% sebagai satu pengamatan, bukan sebagai laju yang
  berlaku umum. Klipnya tetap jadi; yang hilang cuma wajah orang yang sedang
  bicara.
- **Chunking transkrip** memotong tepat di menit ke-20 tanpa menyesuaikan ke
  jeda bicara. Gemini menolak word timestamp di atas 30 menit per request,
  jadi cabang ini aktif untuk setiap audio **di atas 20 menit** — bukan cuma
  video sangat panjang seperti pada provider sebelumnya. Satu kata terpotong
  di tiap batas chunk; diverifikasi end-to-end pada podcast 2,44 jam.
- **Tidak ada autentikasi bawaan** selain `AUTH_TOKEN` opsional.

---

## Lisensi

Produk berbayar milik Agentiv, bukan open source — didistribusikan ke client
sebagai image Docker (`agentiv/capio`), bukan lewat source ini. Mekanisme
teknisnya (bukan syarat legalnya — itu keputusan bisnis, di luar cakupan
dokumen ini) ada di `license/__init__.py`.
