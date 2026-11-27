# Sistem Tampilan dan Caption CAPIO

Dokumen ini menjelaskan arsitektur yang berjalan. Katalog karakteristik visual
dan adjustment pengguna ada di [`template.md`](template.md); katalog kode dan
validasi ada di `pipeline/templates.py`.

## Model tampilan

CAPIO punya lima pilihan Template: `mentahan`, `full_screen`,
`pembicara_samping`, `blur_atas_bawah`, dan `kotak_tengah`. `custom` adalah jalur
konfigurasi terpisah, bukan anggota katalog Template. API menyelesaikan default
dan adjustment menjadi satu konfigurasi lengkap, lalu menyimpan snapshot itu
bersama job. Render job tidak mengambil ulang default yang mungkin berubah.

Adjustment dibatasi per template. Template tanpa adjustment, seperti
`mentahan`, tidak menerima knob tambahan. Custom memvalidasi rasio, mode video,
latar, caption, hook, warna, dan posisi sebelum job masuk antrean.

## Pipeline render

Urutan stage ditetapkan di `worker/orchestrator.py`:

1. Sumber video: unggahan lokal atau download YouTube.
2. Transkripsi bertimestamp melalui Gemini.
3. Seleksi momen dan hook melalui Gemini.
4. Perapian batas klip pada jeda alami.
5. Analisis crop dan wajah.
6. Pembuatan caption.
7. Komposisi dan render audio/video dengan FFmpeg.
8. Pembuatan metadata klip melalui Gemini.
9. Penyimpanan hasil dan pembaruan status job.

Stage crop memakai MediaPipe tanpa dependensi model tambahan. `full_screen` dan
`blur_atas_bawah` mengambil beberapa sampel sepanjang klip, membuat jejak wajah,
lalu menentukan posisi crop serta titik perpindahan. Pergeseran dibuat ketika
wajah utama keluar area aman dan dapat dijadwalkan dekat jeda ucapan. Blur
mempertahankan dua wajah bila keduanya muat dalam panel. Jika wajah tidak
terdeteksi atau analisis gagal, crop memakai titik tengah. Sistem mengikuti
posisi wajah, bukan identitas maupun giliran bicara.

Template lain dan Custom memakai fokus wajah/tengah sesuai konfigurasinya.
`mentahan` melewati crop. Seluruh jalur menjaga rasio source; tidak meregangkan
video untuk memenuhi kanvas.

## Renderer caption

- Caption karaoke umum dibuat sebagai file `.ass`, lalu dibakar ke video oleh
  FFmpeg/libass. Gaya kata aktif dapat berupa perubahan warna, blok, atau blok
  dengan pembesaran sesuai adjustment template.
- Enam motion khusus `pembicara_samping` dan `kotak_tengah` memakai
  `pipeline/reference_caption.py` untuk merender overlay video transparan dari
  transkrip dan timestamp CAPIO, kemudian digabungkan oleh FFmpeg. Emphasis
  mengikuti pilihan kata penting; jika anotasi LLM tidak tersedia, renderer
  memakai fallback deterministik.
- Hook `blur_atas_bawah` dan Custom berasal dari metadata `hook_title`, terpisah
  dari spoken caption yang bersumber dari transkrip.
- Preview template menggunakan jalur render yang sama dengan job. Preview
  sintetis memeriksa tampilan dan posisi, bukan konten video sumber tertentu.

Geometri dan filter template dirakit oleh `pipeline/composition.py`, sedangkan
layout compatibility dan subtitle `.ass` lama tetap dikelola `pipeline/layout.py`.
Metrik font untuk blok per kata dihitung oleh `pipeline/metrik.py`.

## Pemakaian Gemini

Setiap pemanggilan Gemini dicatat ke tabel lokal `gemini_usage`: ID job, stage,
model, token input/output/total, waktu, status, dan penanda estimasi. Prompt,
teks transkrip, respons mentah, dan API key tidak disimpan di tabel tersebut.
Retry dicatat sebagai pemanggilan tambahan.

Settings menampilkan ringkasan per model dan perkiraan setara tarif API Standard
berbayar. Tarif mengacu pada [harga resmi Gemini](https://ai.google.dev/gemini-api/docs/pricing)
dan disimpan dalam kode bersama tanggal pemeriksaan;
nilainya bukan tagihan akun BYOK. Alias model `-latest` dipasangkan ke tarif
model versi tertentu sebagai asumsi dan ditandai di UI. Token historis yang
tidak memiliki rincian input/output tetap dihitung sebagai total token, tetapi
biayanya tidak ditebak.

## Batas antar modul

- `pipeline/stages/*` mengolah konteks stage dan tidak menjalankan HTTP atau
  antrean.
- `worker/orchestrator.py` menjalankan stage secara berurutan dan memperbarui
  progres job.
- `pipeline/templates.py` menjadi sumber validasi konfigurasi tampilan.
- `api/routes.py` menerima konfigurasi, menyimpan job, dan mengirimkannya ke
  antrean; render berjalan di worker.
- `db/` menyimpan job dan catatan pemakaian Gemini; kode render tidak
  mengakses UI.
