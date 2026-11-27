# Agent CAPIO video-first: implementasi dan evaluasi Cania

Tanggal: 1 Oktober 2026. Branch: `agentic_cliping`. Prototipe lokal.

## Implementasi

- Sesi baru menerima sumber saja; brief/jumlah lama tetap diterima. Nilai internal target baru 0 dan tidak membatasi shortlist.
- Persiapan sumber sekali; overview dan peta topik sebelum arahan editorial, tanpa kandidat otomatis. Kutipan batas topik dan cakupan halaman diperiksa; cakupan yang belum lengkap ditandai parsial.
- Chat memakai pesan resmi, pemahaman editorial, asumsi, hal belum diketahui dan peta sumber. Riwayat tools disimpan untuk audit, tidak diputar ulang sebagai transkrip penuh setiap chat.
- Koreksi terbaru menjadi pending terbaru; pesan terdahulu tetap tersimpan. Aturan menyertakan kutipan dan ID pesan pengguna.
- Kandidat ditambahkan. Penggantian hanya pending yang disebut eksplisit; kept terkunci; rejected tidak diajukan ulang. Restatement rentang kept merupakan no-op tanpa validasi ulang kutipan legacy.
- Usulan wajib dibaca lengkap dengan konteks sampai 15 detik di tiap sisi. Pembuka/penutup 3-20 kata harus cocok dengan batas sumber. Durasi tetap 30-90 detik.
- Semua masalah kandidat dilaporkan sekaligus untuk satu koreksi. Setelahnya hanya kandidat yang lolos disimpan; koreksi parsial tidak menghapus pending. Pelanggaran aturan/persetujuan tetap ditolak. Kandidat valid tidak hilang karena kandidat lain ditolak.
- Maksimum 20 kandidat per balasan, tanpa batas total sesi; UI memilih subset maksimal 20 per job render. Ada pemutaran konteks serta kutipan batas dan durasi yang dihitung server.
- Router native, telemetry, deadline dan batas 8 permintaan Gemini termasuk rotasi serta 16 tools tetap dipakai. JSON menyimpan audit kegagalan dan metrik operasi.

## Pengujian teknis

Regresi seluruh repo final: 714 lulus, 2 dilewati, 13 peringatan. Kontrak Agent terakhir: 30 lulus. Ada peringatan cleanup MediaPipe yang sudah ada ketika proses tes berhenti, tanpa kegagalan tes.

Browser dengan ASR/model tiruan, Postgres/Redis terpisah, RQ dan FFmpeg nyata: unggah -> overview tanpa kandidat -> chat -> kept -> alternatif -> refresh -> preview/konteks -> dua kept -> pilih subset satu -> Mentahan -> hasil, lulus. Artefak: `C:/Users/HYPEAM~1/AppData/Local/Temp/capio-agent-ui-Mb0sQ9`.

Instance nyata setelah restart: sesi versi 4, source_ready=true, satu kept tetap ada, render tertaut, preview seek mengembalikan HTTP 206 dan 1024 byte. Worker/API memakai build final pada port 8006. Browser nyata juga memperlihatkan hasil SELESAI, template Mentahan, satu klip dan label Pilihan editor - Agent, serta ringkasan/peta, satu kept 40.2 detik, kutipan batas, pemutar sumber, chat dan tautan hasil. Pemahaman dari operasi yang gagal diberi label sebagai pemahaman terakhir yang selesai, dengan arahan pengguna terbaru tetap tersedia.

## Protokol editorial dan keterbatasan

Sumber: https://youtu.be/Fb0E6sN62QQ. Transcript resmi dibekukan dari job gagal e0e8b3d0: 3493 kata dan 377 kalimat. Source/preview/audio yang sudah tersedia dipakai ulang. Tidak ada timestamp patokan yang dikirim dalam brief atau feedback. Pembandingan memakai transkrip yang sama dengan uji pipeline sebelumnya.

Empat gagasan: belajar efektif, emosi/logika, neuroplastisitas, genetik/lingkungan. Maksimal dua pesan feedback editorial diberikan. Ada beberapa retry teknis selama perbaikan harness/validasi; karena kode ikut diperbaiki selama trial, ini BUKAN evaluasi terkontrol versi final yang dibekukan. Tidak dilakukan feedback ketiga untuk mengejar keberhasilan.

Penilaian keutuhan menggunakan transkrip dan konteks bertimestamp. Tidak ada penilai manusia independen atau stopwatch editor manusia; `editor_seconds=0` berarti tidak diukur, bukan bukti editor tidak bekerja. Angka 105 detik sempat dimasukkan sebagai estimasi otomatis pada trial, kemudian direset; bukan data waktu manusia.

### Hasil awal dan feedback

| Tahap | Hasil |
|---|---|
| Overview awal | 0 kandidat sesuai kontrak, tetapi beberapa indeks peta tidak sesuai isi; diperbaiki lewat validasi kutipan topik. Snapshot awal tetap disimpan. |
| Overview yang diperbaiki | Membaca 7/7 halaman dan peta mencakup akhir sumber 1357.4s; 0 kandidat. Peta masih kasar, bukan batas klip. |
| Pencarian awal | Tidak ada shortlist yang lolos. Beberapa retry habis anggaran atau menghasilkan indeks/durasi/kutipan tidak valid. |
| Feedback 1 | Satu kandidat belajar diterima: 661.3-701.5s, 40.2 detik. Kandidat emosi tidak lolos. |
| Feedback 2 | Kandidat belajar kept tidak berubah. Tidak ada kandidat tambahan yang lolos seluruh pemeriksaan; operasi tetap retriable. |

**Kesimpulan editorial: parsial, 1 dari 4 gagasan diterima.** Belum membuktikan Agent sudah konsisten pada semua momen.

Klip belajar dimulai dari gagasan belajar selalu fun, memberi contoh frustrasi belajar editing, lalu menyelesaikan argumen bahwa have fun saja belum tentu belajar. Berakhir sebelum pertanyaan emosi pada 703.2s. Agent lama memotong 661.3-746.8s (85.5 detik) dan menggabungkan topik belajar dengan emosi; klip baru memisahkannya.

Pemeriksaan neuroplastisitas dan genetik dilakukan pada usulan serta konteksnya: model beberapa kali memakai indeks kata yang keliru, mengambil penutup dari bagian lain, atau menyebut genetika untuk rentang yang sebenarnya neuroplastisitas. Contoh penutup genetik yang diinginkan ada setelah penjelasan contoh panjang; rentang utuh melebihi 90 detik dan perlu subgagasan lengkap, bukan padding/cut mekanis. Usulan gagal tidak dirender.

Kutipan yang cocok hanyalah pemeriksaan sumber. Itu tidak membuktikan kesimpulan semantik utuh. Narasi reason model juga pernah menyebut durasi 32 detik untuk klip yang sebenarnya 40.2; angka server/MP4 menjadi patokan, dan prompt/UI final menegaskan waktu dihitung server.

### Waktu dan pemakaian

| Tahap | Waktu Agent | Permintaan native | Token masuk | Token keluar |
|---|---:|---:|---:|---:|
| Overview diperbaiki (snapshot sebelum penyimpanan akhir) | 87.66s | 3 | 27463 | 5991 |
| Feedback 1 yang menghasilkan kandidat (snapshot) | 28.09s | 6 | 72804 | 2218 |
| Total sesi termasuk seluruh kegagalan/retry | 515.16s | 69 | 1140577 | 30571 |

- Persiapan benchmark: 0 detik download/ASR karena cache; durasi copy dicatat di setup.json. Bukan ukuran kecepatan persiapan video baru.
- Render normal Mentahan, dari job dibuat hingga status done: 11.21s, termasuk antrean dan metadata; bukan durasi encoder saja.
- Waktu aktif editor manusia: tidak tersedia. Evaluasi ini dilakukan oleh Codex.
- Total sesi 69 permintaan berasal dari banyak operasi, bukan satu operasi. Batas 8 tetap berlaku per operasi.
- Model utama sesi gemini-3.5-flash; route nyata juga menggunakan gemini-3.5-flash-lite. Jangan menganggap seluruh trial memakai model utama saja.
- Usage merupakan token yang dilaporkan provider, bukan biaya aktual BYOK. Smoke test schema manual di luar stage sesi tidak termasuk tabel sesi.

## Render dan pemeriksaan batas

Job: `7b9be988-6425-4449-bad7-0ebbeef7e970`, template Mentahan. Hanya kandidat kept aa78c1cd24be5764 disetujui; snapshot 1603-1723 kata sumber. Jalur download/transkripsi/seleksi dilewati; tes RQ/FFmpeg juga memastikan sumber sesi tetap tersedia.

- Rentang disetujui: 661.3-701.5s.
- Durasi MP4: 40.20s, sama dengan 40.2s yang disetujui.
- Korelasi audio 4 detik awal: 0.999509; lag 0.0ms.
- Korelasi audio 4 detik akhir: 0.999395; lag 0.0ms.
- Ini memverifikasi render mengikuti potongan sumber; tidak menjamin timestamp ASR tepat pada tingkat fonem atau menggantikan peninjauan manusia.

Sesi: http://localhost:8006/agent#e69dad62-b8a2-47b4-8c54-e7115419b96e

Hasil: http://localhost:8006/results#7b9be988-6425-4449-bad7-0ebbeef7e970

File: clips/7b9be988-6425-4449-bad7-0ebbeef7e970/c1.mp4

Bukti mentah: data/evaluations/agent-video-first/{setup,overview-first,overview-corrected,search-first-failed,feedback-one,final-session,usage,render-validation}.json. Riwayat gagal dan snapshot keputusan lengkap juga tetap di Postgres sesi.

## Keputusan

Fitur workspace video-dulu sudah bisa diuji dari UI, dan render pilihan yang valid berhasil. Hasil editorial Cania belum layak disebut lulus penuh. Perlu memperbaiki ketepatan indeks/kutipan model dan perilaku model cadangan sebelum memperluas fitur atau menyatakan kualitas stabil. Belum merge main atau rilis produksi; style/template baru tidak disentuh.
