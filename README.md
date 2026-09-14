# CAPIO

Ubah video panjang jadi beberapa klip pendek 9:16 siap posting — lengkap dengan
caption karaoke yang terbakar di video, judul, caption, dan hashtag.

Sumbernya boleh **link YouTube** atau **berkas video sendiri** yang diunggah
lewat halaman Submit (MP4, MOV, MKV, WEBM, dan wadah lain yang bisa dibaca
ffmpeg). Berkas yang diunggah melewati yt-dlp sepenuhnya, jadi ia tidak
tersentuh bot-detection YouTube maupun urusan cookies.

Semua pemrosesan berat berjalan di mesin sendiri. Klip jadi mendarat sebagai
file mp4 biasa di folder `clips/`, bukan di storage cloud mana pun.

**Layanan berbayar yang dibutuhkan cuma dua:** satu untuk transkrip, satu untuk
LLM. Keduanya punya tingkat gratis yang cukup untuk pemakaian pribadi.

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

### Dengan Docker (disarankan)

Cuma butuh **Docker**. Tidak perlu Python, ffmpeg, maupun database.

```bash
git clone <repo-ini>
cd video-clipper
cp .env.example .env        # copy di Windows
docker compose up -d
```

Buka **http://localhost:8000**, lalu ke halaman **Setting** untuk mengisi dua
API key (petunjuknya ada di halaman itu). Klik **Simpan**, lalu **Tes** untuk
memastikan key-nya benar. Setelah itu langsung bisa submit video.

```bash
docker compose logs -f worker   # ikuti prosesnya
docker compose down             # matikan; data tetap tersimpan
```

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
> memang harus di server. Transkrip sendiri tidak jadi penghalang selama
> memakai ElevenLabs — hanya Groq yang menolak IP datacenter dengan 403.

---

## Halaman

| Halaman | Isi |
|---|---|
| **Submit** `/` | Link YouTube atau unggah berkas sendiri, jumlah klip, pemilih layout dengan contoh videonya, dan knob gaya caption — semuanya per video. Begitu satu layout dipilih, halaman melebar dan panel pratinjau caption (dirender lewat jalur yang sama dengan produksi, bukan tiruan CSS) muncul di sebelah kanan. Strip di atas menunjukkan provider aktif, status lisensi, dan apakah konfigurasi sudah lengkap, jadi yang bolong ketahuan *sebelum* submit, bukan belasan menit kemudian. |
| **Proses** `/process` | Job berjalan dengan penanda 9 tahap, plus job gagal beserta error-nya. Tiap job bisa dihapus. |
| **Hasil** `/results` | Klip jadi, bisa diputar, diunduh, atau dihapus — satu per satu maupun sekaligus per job. |
| **Setting** `/settings` | Semua konfigurasi (termasuk license key), dengan tombol tes per provider. |

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
| 2 | Transkrip | ElevenLabs / Groq / Gemini Transcribe | kata + kalimat, bertimestamp |
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

### Transkrip

| Provider | Biaya | Catatan |
|---|---|---|
| **ElevenLabs** Scribe — *default* | ada tier gratis | Akurat untuk Bahasa Indonesia termasuk yang bercampur istilah Inggris. Tanpa blokir IP. Mengeja angka, tapi `asr/angka.py` mengubahnya kembali jadi digit. |
| **Groq** Whisper | free tier 8 jam audio/hari | Sangat cepat — 15 menit audio selesai dalam ~4 detik. Aman untuk konten Indonesia murni. **Menolak IP datacenter/VPN dengan 403** — lihat peringatan di bawah. |
| **Gemini 3.5 Transcribe** | tier gratis 25 request/hari **per project** Google Cloud | Memakai `GEMINI_API_KEYS`. Model ini hanya menulis **satu bahasa per request** dan diam-diam membuang kalimat bahasa lain — 28–31% detik bicara hilang pada video Indonesia berkutip Inggris. CAPIO menambalnya: celah bersuara tanpa kata dideteksi ffmpeg lalu ditranskrip ulang sekaligus dalam satu request tambahan, sisa 2–3% (setara video Indonesia murni). Konten Indonesia murni tetap 1 request. Key tambahan hanya menambah jatah kalau dibuat di project lain. |

> ### Groq memblokir IP datacenter, dan gejalanya menyesatkan
>
> Groq menolak permintaan dari IP datacenter dengan **HTTP 403** — VPS, cloud,
> dan sebagian besar VPN termasuk di dalamnya. Yang bikin mahal: 403 terbaca
> seperti "API key salah", jadi orang membuat key baru berkali-kali padahal
> key-nya tidak pernah bermasalah.
>
> **Cara mengenalinya:** tombol *Tes groq* di halaman Setting menjawab
> `Ditolak (403). Groq memblokir IP datacenter — matikan VPN kalau menyala.`
> Kalau pesan itu muncul, jangan sentuh key-nya.
>
> **Jalan keluarnya:** matikan VPN, atau pakai ElevenLabs (default) yang tidak
> memblokir IP mana pun. Ini juga alasan CAPIO ditujukan untuk laptop atau PC
> sendiri, bukan VPS.

Ini pilihan yang paling terasa hasilnya, karena **caption terbakar permanen di
video**. Transkrip yang meleset kelihatan oleh penonton dan tidak bisa
diperbaiki setelah render.

**Kenapa Groq bukan lagi default.** Tiga video Indonesia berisi istilah Inggris
ditranskrip kedua provider dari file audio yang sama persis. Pada satu dari tiga
video, **29,6% keluaran Groq adalah teks Jepang** — Whisper berpindah bahasa
lalu mengarang panjang lebar; dua video lain nol. Kalimat Inggris juga
diterjemahkan alih-alih ditranskrip: *"Tools like Google Analytics"* keluar
sebagai *"Tua seperti analitik"*.

Yang menentukan bukan rata-rata akurasinya, melainkan bentuk kegagalannya: benar
di dua video lalu ambruk total di video ketiga tanpa peringatan. Kegagalan tak
merata seperti itu lebih sulit diantisipasi daripada kesalahan kecil yang
konsisten. Groq tetap disediakan dan tetap berguna — cepat, gratis, dan aman
untuk konten yang murni Bahasa Indonesia.

### LLM

| Provider | Catatan |
|---|---|
| **Gemini** | Ada free tier. Boleh diisi beberapa key dipisah koma. |
| **OpenRouter** | Satu key untuk banyak model. |

Pipeline memakai **dua panggilan LLM per video**, jadi kuota gratis Gemini
(1.000 permintaan/hari) setara sekitar 500 video per hari.

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

Empat bentuk klip (`penuh`, `kotak`, `samping`, `ori`) plus gaya caption
(font, ukuran, warna kata aktif, jumlah kata per tampilan, huruf besar) —
dipilih **per video** di halaman Submit, bukan sekali untuk semua video.
Nilai di halaman Setting cuma jadi nilai awal yang tampil pertama kali.
Detail tiap layout ada di `pipeline/layout.py`.

### Kinerja

Satu job diproses sekaligus secara bawaan (`WORKER_MODE=single`). Bisa
diganti ke `multi` di halaman Setting untuk memproses beberapa job
bersamaan — lebih cepat kalau CPU-nya cukup, tapi setiap job menjalankan
ffmpeg yang memakai semua core tanpa batas, jadi di mesin kecil job
paralel bisa membuat semuanya lebih lambat, bukan lebih cepat. Naikkan
`WORKER_COUNT` bertahap sambil memperhatikan beban CPU.

---

## Kalibrasi

Semua ada di halaman Setting. Ini yang benar-benar perlu diputar kalau hasilnya
belum pas:

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
asr/                  provider transkrip (groq, elevenlabs)
llm/                  provider LLM (openrouter, gemini)
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

Folder `asr/` dan `llm/` berbentuk paket berisi beberapa provider karena memang
punya lebih dari satu implementasi; `storage/` sengaja satu file, karena
lapisan pemilih untuk satu implementasi hanyalah indirection.

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
  jeda bicara. Cabang itu baru aktif di atas ~2,3 jam audio, dan sudah
  diverifikasi end-to-end pada podcast 2,44 jam.
- **Tidak ada autentikasi bawaan** selain `AUTH_TOKEN` opsional.

---

## Lisensi

Produk berbayar milik Agentiv, bukan open source — didistribusikan ke client
sebagai image Docker (`agentiv/capio`), bukan lewat source ini. Mekanisme
teknisnya (bukan syarat legalnya — itu keputusan bisnis, di luar cakupan
dokumen ini) ada di `license/__init__.py`.
