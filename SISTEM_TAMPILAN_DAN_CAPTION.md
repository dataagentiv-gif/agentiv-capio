# Dokumentasi Sistem Tampilan dan Caption Agentiv-CAPIO

Dokumen ini mendetailkan kondisi sistem saat ini untuk keperluan perencanaan refaktor.

---

## 1. Arsitektur Tampilan (Layout System)

Sistem tampilan saat ini bersifat **terpusat dan deklaratif**. Seluruh definisi tampilan mendarat di `pipeline/layout.py` menggunakan dataclass `Layout`.

### Stack & Komponen Utama:
- **Python Data Model**: Dataclass `Layout` menyimpan parameter geometri (zoom, tinggi, wajah_x, kepala, radius) dan gaya teks (align, margin, tumpuk, sorot).
- **FFmpeg Filtergraph**: Geometri diterjemahkan menjadi rantai filter `crop`, `scale`, `pad`, `setsar`, dan `overlay`.
- **Masking Engine**: Filter `geq` digunakan untuk membuat gambar PNG statis (`lapis...png`) sebagai masker untuk sudut tumpul (radius) dan gradasi gelap (redup). Masker ini dibuat sekali per job dan ditumpuk di atas video.

### Daftar Layout Saat Ini:
1.  **`penuh`**: 9:16 mengisi layar, mengikuti wajah pembicara di tengah.
2.  **`duo`**: Panel atas-bawah (1080x960), masing-masing mengikuti satu orang (khusus wide-shot 2 orang).
3.  **`kotak`**: Video di dalam kotak rounded di tengah, latar hitam, caption di area kosong bawah.
4.  **`samping`**: Video pita mendatar, pembicara di satu sisi (kiri/kanan), sisi lain gradasi gelap untuk teks.
5.  **`ori`**: Tanpa modifikasi geometri atau caption (mentahan).

### Alur Kerja (Flow):
1.  **Submit**: User memilih layout dan memutar knob (font, warna, dll).
2.  **Job Enqueue**: Parameter layout dan knob (disimpan dalam `gaya` JSONB) dikirim ke worker.
3.  **Stage Crop**: Deteksi wajah menghasilkan koordinat `fx, fy`.
4.  **Stage Render & Caption**: 
    - `layout.geometri()` menghitung koordinat crop dan scale final.
    - `layout.filtergraph()` menyusun perintah FFmpeg.
    - Jika ada radius/redup, `render._mask()` membangkitkan PNG masker.

---

## 2. Sistem Caption (Caption System)

Caption dirender sebagai **burned-in subtitles** menggunakan format `.ass` (Advanced Substation Alpha).

### Mekanisme Per Kata:
Sistem tidak menggunakan tag karaoke standar (`\k`) karena batasan akurasi dan efek. Sebagai gantinya, sistem membuat **satu event Dialogue terpisah untuk setiap kata**.

### Gaya Kata Aktif (Active Word Style):
Didefinisikan di `pipeline/stages/caption.py` dalam `GAYA_AKTIF`:
1.  **`text_color`**: Menggunakan tag override `{\c&HBBGGRR&}`.
2.  **`background`**: Menggambar blok di belakang kata menggunakan **Vector Drawing (`\p1`)**.
3.  **`background_scale`**: Blok + animasi pembesaran (`\fscx\fscy`) menggunakan tag `\t` (transform).

### Kalkulasi Metrik Teks (`pipeline/metrik.py`):
Karena blok digambar manual (bukan fitur bawaan libass), sistem harus tahu posisi piksel tiap kata:
- Menggunakan `fontTools` untuk membaca tabel `OS/2` dan `hmtx` dari file `.ttf`.
- Menghitung `usWinAscent` dan `usWinDescent` untuk menentukan tinggi baris yang sepakat dengan libass.
- Menghitung `advance width` tiap glyph untuk menentukan titik tengah (`\pos`) dan lebar blok.
- **Penting**: Libass tidak memetakan `Fontsize` ke unit `em`, melainkan ke tinggi `ascent + descent`. Metrik ini ditiru persis di `metrik.py`.

### Struktur File `.ass`:
- **Header**: Dihasilkan oleh `layout.header_ass()`, mengatur `PlayResX/Y` (1080x1920) dan style dasar `Cap`.
- **Events**:
    - Mode Teks: Satu baris per kata atau grup kata dengan tag warna di tengah.
    - Mode Blok: Dua layer event. Layer 0 untuk gambar blok (`\p1`), Layer 1 untuk teks di atasnya.

---

## 3. Knob & Konfigurasi (Customization)

Pengguna bisa menimpa perilaku default layout melalui `knob`:

| Knob | Deskripsi | Target |
|---|---|---|
| `font` | Nama font (Poppins, Anton, Lora, Archivo Black) | Style `.ass` |
| `ukuran` | Ukuran font dalam poin | Style `.ass` |
| `pasif` / `aktif` | Warna teks (hex) | Style `.ass` |
| `kata` | Max kata per tampilan (default 4) | Grouping logic |
| `upper` | Boolean force uppercase | Teks `.ass` |
| `active_word_style` | Gaya (color/bg/scale) | Generator logic |
| `active_word_...` | Warna, radius, padding blok | Vector drawing logic |
| `speaker_side` | Posisi pembicara (kiri/kanan) | Geometri & Redup |
| `redup_luas/gelap` | Intensitas bayangan samping | Mask generator |

---

## 4. Kelemahan & Batasan Saat Ini (Untuk Refaktor)

1.  **Duo Layout Fallback**: Saat ini jika deteksi 2 orang gagal, layout dipaksa kembali ke `penuh` secara hardcoded di orchestrator.
2.  **Statis Geometri**: Radius dan tinggi kotak dikunci per layout, tidak bisa diputar via knob (kecuali redup).
3.  **Satu Font Per Job**: Tidak bisa mencampur font dalam satu klip (batasan .ass style dasar).
4.  **Vector Drawing Performance**: Untuk klip panjang dengan banyak kata, file `.ass` bisa menjadi sangat besar karena setiap kata punya instruksi gambar manual.
5.  **Alignment & Stacking**: Logika penumpukan vertikal (`tumpuk=True`) masih sederhana dan kadang bertabrakan dengan alignment `\an` tertentu.

---

## 5. Pratinjau (Preview Path)

Preview (`api/preview.py`) menggunakan jalur yang sama dengan produksi:
- Menghasilkan file `.ass` sementara.
- Menjalankan `ffmpeg` dengan input warna solid (`color=0x3a3f47`) untuk merender cuplikan 5 detik.
- Menjamin apa yang dilihat user di UI adalah hasil render `libass` yang sebenarnya, bukan simulasi CSS.
