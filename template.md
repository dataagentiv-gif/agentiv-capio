# Template CAPIO

Dokumen ini adalah katalog template output CAPIO. Satu template adalah paket
tampilan yang utuh: geometri video, crop, posisi caption, tipografi dasar, dan
aturan rendernya ditentukan oleh template tersebut.

Template tidak berbagi pengaturan secara otomatis. Setiap template hanya
menampilkan adjustment yang memang tercantum di bagiannya. Template baru
ditambahkan sebagai bagian baru dalam dokumen ini sebelum diimplementasikan.

## Kontrak template

Setiap template harus mencatat:

- **ID** — nilai stabil yang disimpan pada job.
- **Karakteristik terkunci** — hal visual yang tidak dapat diubah pengguna.
- **Adjustment** — parameter yang boleh diubah untuk video itu.
- **Aturan caption** — apakah caption tersedia dan bagaimana perilakunya.

Nilai adjustment selalu berlaku per video. Tidak ada adjustment berarti
template dirender persis sesuai karakteristiknya.

---

## 1. Mentahan

- **ID:** `mentahan`
- **Tujuan:** menghasilkan potongan source untuk diedit kembali di aplikasi
  lain.

### Karakteristik terkunci

- Rasio dan frame source dipertahankan apa adanya.
- Video hanya dipotong pada rentang waktu klip.
- Tidak ada crop, scale, pad, filter tampilan, atau caption burned-in.
- Kualitas encoding memakai mode yang sesuai untuk bahan edit lanjutan.

### Adjustment

Tidak ada.

### Aturan caption

Caption selalu mati dan tidak ditampilkan sebagai pilihan.

---

## 2. Full Screen

- **ID:** `full_screen`
- **Tujuan:** video vertikal layar penuh dengan caption burned-in.

### Karakteristik terkunci

- Output berukuran 1080 × 1920 (9:16).
- Video memenuhi seluruh kanvas.
- Crop mengikuti subjek utama bila wajah terdeteksi; jika tidak, memakai
  center crop.
- Posisi, ukuran dasar, font dasar, dan warna teks pasif ditentukan template.

### Adjustment

| Parameter | Nilai yang tersedia | Keterangan |
|---|---|---|
| `caption_style` | `text_color`, `background`, `background_scale` | Gaya kata yang sedang diucapkan: perubahan warna teks, blok di belakang kata, atau blok dengan kata membesar. |
| `active_text_color` | warna hex RGB | Warna huruf kata aktif. Dipakai pada gaya `text_color`, serta teks di dalam blok pada dua gaya blok. |
| `active_background_color` | warna hex RGB | Warna blok kata aktif. Hanya dipakai pada `background` dan `background_scale`. |

### Aturan caption

- Caption selalu aktif pada template ini.
- Semua caption dibakar ke video.
- Hanya adjustment di atas yang dapat mengubah caption. Pengaturan crop,
  ukuran, posisi, font, jumlah kata, dan warna teks pasif tetap menjadi bagian
  terkunci dari template sampai secara eksplisit ditambahkan ke bagian ini.

---

## 3. Pembicara di samping

- **ID:** `pembicara_samping`
- **Tujuan:** klip 9:16 dengan pembicara di kiri dan ruang editorial untuk
  caption di kanan.

### Karakteristik terkunci

- Kanvas keluaran berukuran 1080 × 1920 (9:16).
- Video menjadi pita horizontal di tengah kanvas; ruang di atas dan bawahnya
  berwarna hitam.
- Pembicara memakai medium shot di sisi kiri, dengan wajah berada kira-kira di
  sepertiga kiri pita video.
- Sisi kanan adalah ruang caption.
- Gradasi gelap halus menguat ke kanan untuk menjaga teks terbaca tanpa garis
  batas kotak yang keras.
- Font, ukuran dasar, warna dasar, posisi, dan crop adalah bagian dari
  template, bukan pengaturan umum.

### Adjustment

| Parameter | Nilai yang tersedia | Keterangan |
|---|---|---|
| `caption_motion` | `soft_focus`, `kinetic_words`, `editorial_focus` | Memilih pola susunan dan animasi caption untuk video ini. |

### Aturan caption

Caption selalu aktif dan dibakar ke video. Tiga pilihan motion adalah:

1. **`soft_focus`** — blok pendek dua atau tiga kata, dapat menjadi dua baris;
   kata aktif putih terang dan kata lain abu-abu redup. Caption tetap berada
   di ruang kanan.
2. **`kinetic_words`** — kata atau frasa besar dibangun bertahap sebagai
   komposisi tipografi; tiap elemen masuk dari bawah dengan blur/fade singkat
   lalu berhenti tajam.
3. **`editorial_focus`** — caption multi-baris dengan hierarki ukuran;
   caption dan shadow/blur block di belakangnya dapat berpindah sisi mengikuti
   komposisi pembicara.

Tidak ada adjustment lain pada template ini. Setiap motion membawa aturan
susunan kata, ukuran relatif, dan transisinya sendiri.

---

## 4. Video tengah dengan blur atas-bawah

- **ID:** `blur_atas_bawah`
- **Tujuan:** menaruh video tajam di tengah, dengan judul topik di atas dan
  caption ucapan di bawah tanpa menutupi isi utama video.

### Karakteristik terkunci

- Kanvas keluaran berukuran 1080 × 1920 (9:16).
- Satu source video dipakai sebagai dua lapisan: versi tajam di panel tengah,
  serta versi blur sebagai latar di area atas dan bawah.
- Area blur atas khusus untuk `hook_title`.
- Area blur bawah khusus untuk `spoken_caption`.
- `hook_title` adalah headline/topik klip, bukan transkrip. Nilainya berasal
  dari hook atau judul metadata klip.
- `spoken_caption` adalah teks yang benar-benar diucapkan dan mengikuti
  timestamp transkrip.

### Adjustment

| Parameter | Nilai yang tersedia | Keterangan |
|---|---|---|
| `hook_block` | `none`, `white` | Tanpa blok: judul putih. Blok putih: judul hitam di dalam kotak putih. |
| `caption_style` | `text_color`, `background`, `background_scale` | Gaya kata yang sedang diucapkan di area blur bawah. |
| `active_text_color` | warna hex RGB | Warna huruf kata aktif. Dipakai pada `text_color`, serta teks di dalam blok pada dua gaya blok. |
| `active_background_color` | warna hex RGB | Warna blok kata aktif. Hanya dipakai pada `background` dan `background_scale`. |

### Aturan hook title

- Susunan, ukuran, dan ketebalan hook tetap: judul tebal dengan kapitalisasi
  aslinya, maksimal dua baris.
- `none` menampilkan teks putih langsung di atas blur; `white` menampilkan
  teks hitam di dalam satu kotak putih yang mengikuti lebar judul.

### Aturan spoken caption

- Caption selalu berada di area blur bawah dan dibakar ke video.
- `text_color` menandai kata aktif lewat perubahan warna huruf.
- `background` menandai kata aktif dengan blok berwarna di belakangnya.
- `background_scale` memakai blok yang sama, dengan kata aktif membesar.
- Susunan spoken caption dikunci ke frasa pendek; adjustment gaya kata aktif
  sama dengan template Full Screen.

---

## 5. Kotak tengah

- **ID:** `kotak_tengah`
- **Tujuan:** menonjolkan video dalam kartu bersudut tumpul di tengah kanvas,
  dengan caption editorial yang hidup di dalam area kartu.

### Karakteristik terkunci

- Kanvas keluaran berukuran 1080 × 1920 (9:16) dengan latar hitam.
- Video berada di kartu tengah dengan sudut tumpul.
- Ukuran, posisi, crop, radius kartu, font dasar, dan posisi dasar caption
  adalah bagian terkunci dari template.
- Caption dibakar ke video dan tidak memakai hook title terpisah.

### Adjustment

| Parameter | Nilai yang tersedia | Keterangan |
|---|---|---|
| `caption_motion` | `single_word_float`, `soft_phrase`, `scatter_emphasis` | Memilih pola susunan dan animasi caption untuk video ini. |
| `scatter_accent_color` | warna hex RGB | Warna kata atau frasa yang ditekankan. Hanya berlaku pada `scatter_emphasis`. |

### Aturan caption

1. **`single_word_float`** — satu kata atau frasa sangat pendek, putih serif,
   masuk lembut dengan blur/fade lalu menjadi tajam di area caption.
2. **`soft_phrase`** — frasa pendek dua atau tiga kata, putih serif dengan
   shadow tipis; muncul lembut, bertahan singkat, lalu berganti ke frasa
   berikutnya.
3. **`scatter_emphasis`** — kata dan frasa dirakit bertahap pada beberapa
   zona aman di sekitar subjek. Satu kata atau frasa penting menjadi lebih
   besar dan memakai `scatter_accent_color`; elemen lain tetap putih.

Tidak ada warna lain yang dapat diatur. `scatter_accent_color` tidak
mengubah `single_word_float` maupun `soft_phrase`.

---

## Mode Custom

Mode `custom` bukan template dengan tampilan baku. Ia memberi kontrol atas
komposisi dasar untuk satu video, dengan batas aman agar crop dan caption tetap
terbaca. Semua nilai berlaku untuk seluruh klip dalam satu job.

### Parameter yang dapat diatur

| Kelompok | Parameter |
|---|---|
| Video | rasio output `9:16`, `1:1`, `16:9`; video penuh atau panel; rasio/ukuran panel; crop atau video utuh; fokus wajah atau tengah; radius sudut |
| Latar | hitam, warna polos, atau blur dari source video |
| Caption | tampil/sembunyi, posisi vertikal, Poppins/Archivo Black/Anton/Lora, ukuran, 1–4 kata per grup, huruf besar semua |
| Gaya kata aktif | `text_color`, `background`, `background_scale`, warna huruf aktif, warna blok aktif |
| Keterbacaan | outline, shadow, kekuatan shadow |
| Hook | tampil/sembunyi, teks hook otomatis dari metadata, posisi atas, tanpa blok atau kotak putih–teks hitam |

### Batasan versi awal

- Posisi setiap kata tidak dapat diatur satu per satu; posisi grup caption digeser sebagai satu zona dan berlaku untuk semua klip.
- Motion editorial `soft_focus`, `kinetic_words`, `editorial_focus`,
  `single_word_float`, `soft_phrase`, dan `scatter_emphasis` tetap dimiliki
  template yang mendukungnya.
- Preview Custom memakai cuplikan sintetis; posisi caption disimpan relatif terhadap kanvas final.
- Filter visual kompleks di luar latar blur tidak tersedia.
- Pada rasio `1:1` dan `16:9`, posisi serta ukuran caption diskalakan dari
  layout referensi vertikal agar tidak jatuh di luar kanvas.
- Hook dan caption panjang dibungkus atau diperkecil oleh renderer; transkrip
  kosong tetap menghasilkan video tanpa caption, bukan job gagal.
- Deteksi wajah yang gagal memakai crop titik tengah. Keputusan sisi pembicara
  dibuat sekali per klip agar tidak berpindah-pindah di tengah video.
- Nilai adjustment disalin ke job saat submit. Perubahan default katalog tidak
  mengubah job yang sudah antre atau selesai.

Contoh hasil custom: panel video 70% tinggi di tengah dengan radius 40 px,
latar blur, serta caption bawah bergaya blok kuning.

---

## Alur UI halaman Submit

Setelah pengguna memasukkan link YouTube atau menyelesaikan unggah berkas,
halaman menampilkan pilihan awal:

1. **Template**
2. **Custom**

Caption bukan pilihan mode awal. Caption adalah bagian dari pengaturan yang
muncul setelah pengguna memilih template atau mode custom.

### Jalur Template

1. Pengguna memilih satu kartu dari library template.
2. Halaman hanya menampilkan adjustment yang didukung template tersebut.
3. Template tanpa adjustment, seperti `mentahan`, tidak menampilkan panel
   pengaturan tambahan.
4. Mengganti template membuang adjustment yang tidak berlaku pada template
   baru, supaya nilai lama tidak ikut tersimpan diam-diam.
5. Pratinjau diperbarui berdasarkan template dan adjustment yang dipilih.

Contoh: memilih `pembicara_samping` hanya membuka pilihan `caption_motion`;
memilih `blur_atas_bawah` membuka pilihan blok hook dan gaya kata aktif; memilih
`kotak_tengah` membuka motion caption serta warna aksen hanya ketika
`scatter_emphasis` dipilih.

### Jalur Custom

1. Pengguna memilih **Custom**.
2. Halaman menampilkan kelompok pengaturan Video, Latar, Caption,
   Keterbacaan, dan Hook.
3. Kontrol yang bergantung pada pilihan lain hanya muncul saat relevan;
   misalnya warna blok hanya muncul ketika gaya caption memakai blok.
4. Pratinjau diperbarui berdasarkan nilai custom yang sedang dipilih.

Nilai dari template dan custom tidak dicampur. Saat pengguna berpindah jalur,
halaman memakai nilai awal jalur baru agar hasil job selalu dapat dijelaskan
dengan satu konfigurasi yang utuh.

---

## Template berikutnya

Tambahkan template baru dengan struktur yang sama. Jangan menambahkan
parameter global; parameter harus dimiliki template yang benar-benar
menggunakannya.
