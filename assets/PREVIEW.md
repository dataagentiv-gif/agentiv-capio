# Video contoh untuk preview tampilan

Taruh satu berkas bernama **`preview.mp4`** di folder ini (`assets/`).

Begitu ada, halaman **Setting → Tampilan** berhenti memakai potongan klip
terbaru dan memakai video ini — **bergerak, bukan gambar diam**. Itu penting:
bagian paling menentukan dari gaya caption adalah sorotan kata yang berpindah,
dan itu tidak ada di satu frame.

## Yang membuatnya berguna

| | |
|---|---|
| Rasio | **16:9** (1920×1080 ideal) — sama seperti sumber yang biasa diproses |
| Durasi | **6 detik cukup.** Hanya 5 detik pertama yang dipakai |
| Isi | **satu orang bicara menghadap kamera**, terlihat dari dada ke atas |
| Suara | tidak perlu — preview selalu bisu, dan audionya dibuang saat render |
| Caption | **jangan ada teks terbakar di videonya**; caption contoh ditumpuk di atasnya |

Wajah yang jelas itu yang paling menentukan: layout `kotak` dan `samping`
memposisikan bingkai berdasarkan letak wajah, jadi video tanpa orang membuat
preview tidak bisa dipakai menilai pembingkaian.

## Kalau berkasnya tidak ada

Preview jatuh ke potongan klip terbaru milik pengguna, dan kalau itu pun belum
ada, ke pola sintetis. Halamannya tetap bisa dibuka — hanya tidak bergerak.
