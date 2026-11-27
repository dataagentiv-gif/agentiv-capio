# Evaluasi Agent CAPIO: rekomendasi momen dan batas klip

Tanggal: 2 Oktober 2026  
Branch: `agentic_cliping`  
Instance lokal: `http://localhost:8006/agent`

## Setup

- Sumber: [Kenapa Banyak Orang Indonesia Kerja Keras Tapi Gak Pernah Kaya?](https://youtu.be/Hif0Lrzg6pQ)
- Sesi evaluasi: `51be45f2-fb1a-4109-acb9-fcf6dd1ec08d` — salinan sumber/transkrip untuk test. Sesi asli tidak diubah.
- Transkrip dan video sudah disiapkan sebelum rangkaian chat; waktu persiapan/download/ASR tidak diukur ulang.
- Brief yang dicoba berurutan: “Cari momen yang berisi nasihat” → “Fokus alasan kerja keras tidak cukup buat kaya” → “Yang lain ada?”. Sesudahnya ada pengulangan alternatif dan feedback batas agar sistem diuji sampai kandidat konkret.

## Hasil editorial

| Putaran | Hasil tersimpan | Catatan |
|---|---|---|
| Nasihat, arahan luas | 0 kandidat; 3 rentang rekomendasi unik, tetapi masing-masing sempat muncul dua kali dengan judul berbeda. | Tiga kandidat ditolak karena kutipan penutup tidak cocok dengan batas. Ini sebelum deduplikasi live final; test unit sekarang mencakup deduplikasi tersebut. |
| Fokus kerja keras tidak cukup buat kaya | 0 kandidat; rekomendasi 0.1–99.8s (99.7 detik). | Kandidat awal kurang konteks terbaca dan koreksinya melewati batas 90 detik. Rekomendasi ini bukan klip siap render. |
| “Yang lain ada?” pertama | 0 kandidat; sudut ownership sekitar 281.3–352.2s. | Momen baru ditemukan, tetapi batas/kutipan belum lolos. Fallback sempat menandai `alternatives=false`; ini diperbaiki dan dites. |
| “Yang lain ada?” sesudah fix | 0 kandidat; rekomendasi lain 827.2–869.5s. | Ringkasan menyatakan `alternatives=true`; rentangnya berbeda dari saran sebelumnya. |
| Feedback ownership pertama | 0 kandidat; rekomendasi yang sama, 281.3–351.5s. | Dua koreksi internal masih meleset satu-dua kata pada kutipan penutup. |
| Feedback ownership dengan kalimat penutup eksplisit | 0 kandidat; model mengosongkan kutipan penutup dua kali. | Menemukan bahwa kutipan di schema ternyata opsional, walau validator mewajibkannya. Schema kemudian dibuat wajib. |
| Percobaan setelah schema dan petunjuk indeks batas diperbaiki | **1 kandidat pending**, belum dipertahankan atau dirender. | Sudut, konteks, kutipan, serta batas lolos validasi. |

### Kandidat yang lolos

- Rentang: **281.3–352.9 detik**, durasi **71.6 detik**.
- Batas kata: indeks **811–995**.
- Pembuka: “Kekayaan itu datang dari ownership kepemilikan”.
- Penutup: “sebagian value dari apa lu ciptain.”
- Konteks memuat contoh karyawan yang membesarkan omzet perusahaan dari 10 miliar ke 1 triliun, kontras gaji/promosi dengan pemilik saham, lalu kesimpulan ownership. Kata berikutnya “Contohnya” mulai pada 353.0s dan tidak ikut masuk.
- Kandidat masih berstatus **pending**. Belum ada render karena pilihan akhir tetap milik editor.

## Perubahan yang diterapkan

- “Yang lain?” meneruskan fokus terakhir dan kandidat/rekomendasi sebelumnya menjadi pembanding; rentang yang berulang tidak dihitung sebagai alternatif baru.
- Fallback setelah koreksi mempertahankan status alternatif dan fokus pada ringkasan hasil.
- Kutipan pembuka dan penutup kandidat kini wajib di schema. Saat kutipan yang dipilih tidak pas dengan batas, validator menyertakan indeks tempat kutipan itu cocok sebagai petunjuk koreksi; batas tetap diputuskan model.
- Render memakai validasi `WordRange` yang sudah ada agar kandidat lama tanpa kutipan tidak gagal saat snapshot render.

## Pengukuran dan batas hasil

- Delapan putaran chat: 39 permintaan model, 20 pemanggilan tool, sekitar 447,957 token masuk dan 12,548 token keluar. `processing_seconds` per putaran berjumlah 119.27 detik; pengukuran waktu aktif editor tidak tersedia (`editor_seconds=0`).
- Termasuk ringkasan sumber awal, metrik sesi menjadi 47 permintaan model dan 146.01 detik pemrosesan. Angka ini bukan biaya API. Source prep di test ini menggunakan aset hasil salinan, jadi bukan benchmark download/ASR.
- Penilaian konteks memakai transkrip bertimestamp dan kutipan sumber. Kandidat belum dirender/didengar ulang; kelulusan validator membuktikan indeks, durasi, dan kutipan, bukan menggantikan review audio editor.
- Hasilnya **parsial tetapi konkret**: arahan luas memunculkan beberapa sudut dan loop alternatif menghasilkan sudut berbeda; perlu feedback batas yang eksplisit dan dua perbaikan kode sebelum satu klip lolos. Belum cukup untuk menyebut Agent konsisten pada arahan luas atau semua jenis sumber.

## Pemeriksaan teknis

- `tests/test_agentic.py`: **37 passed**.
- `tests/agent_ui.test.cjs`: **1 passed** — upload, chat, kandidat, alternatif, refresh, preview, pilih subset, render Mentahan dan halaman hasil dengan layanan uji terpisah.
- API/worker lokal sudah dibangun ulang dari branch ini dan berjalan di port **8006**.
- Tidak ada render dari sesi evaluasi ini. Belum merge ke `main` atau rilis.

Sesi untuk ditinjau: http://localhost:8006/agent#51be45f2-fb1a-4109-acb9-fcf6dd1ec08d
