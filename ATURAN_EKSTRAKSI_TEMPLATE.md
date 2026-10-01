# Rumus dan aturan ekstraksi template CAPIO

Panduan wajib untuk membaca referensi video, merumuskan caption/template,
menulis brief implementasi, serta menilai revisi visual. Ini adalah spesifikasi
kerja dan catatan fitted values; bukan prototype engine atau fitur ekstraksi
otomatis yang sudah terpasang.

## 1. Sumber, ruang lingkup, dan otoritas

Dirangkum pada 1 Oktober 2026 dari `template_enggine_ref` milik pengguna:

- `CAPIO_Caption_Formula_Extraction_Guide_v2_1.docx` — alur ekstraksi utama.
- `AGENT_BUILDER_ENGINE_GUIDE.md` — kontrak layout, compositing, revisi, dan QA.
- `AGENT_ENGINE_REUSE_GUIDE.md` — aturan adaptasi dan elemen yang dikunci.
- README, brief koreksi, implementation report, preset, dan pembacaan renderer
  enam keluarga aktif: Soft Focus V7, Editorial Focus V5, Kinetic Words V5,
  Soft Phrase V1, Single Word Float V1, dan Scatter Emphasis V1.

Folder asal saat ekstraksi: `C:\Users\HYPE AMD\Downloads\template_enggine_ref`.
Panduan ini berdiri sendiri; CAPIO tidak membutuhkan folder Downloads itu
untuk menjalankan pipeline.

Instruksi pengguna menentukan tujuan dan ruang lingkup. Video referensi menjadi
patokan tampilan, timing, dan motion. Brief menjelaskan hasil pengamatan serta
interpretasi. Prototype menjadi bukti pendekatan implementasi, bukan jaminan
bahwa setiap parameter atau klaim README benar-benar dijalankan kodenya.

Nilai hasil fitting tidak boleh diklaim sebagai setting editor asli. Video
ekspor tidak mengungkap timeline, blend mode asli, stack efek, atau riwayat
kompresi. Beberapa kombinasi parameter bisa menghasilkan piksel yang serupa.

Aturan ini terutama mencakup caption. Geometri video, crop, latar, transisi,
footage pembuka, dan caption dicatat sebagai komponen terpisah jika memang
diamati pada referensi. Cut scene bukan cue caption. Ekstraksi style tidak
memberi kewenangan memilih momen atau menyetujui render Agent.

## 2. Label bukti wajib

| Label | Isi yang diperbolehkan |
|---|---|
| Observed | Piksel dan perilaku yang terlihat/terukur, disertai frame atau rentang waktu. |
| Inferred | Dugaan arsitektur efek atau motion, beserta alasan dan alternatif. |
| Fitted CAPIO equivalent | Nilai yang dipilih untuk menghasilkan kecocokan visual dalam renderer CAPIO tertentu. |
| Confidence | Low, medium, high, atau mixed per aspek; jelaskan keterbatasannya. |

Setiap parameter mencatat nama, nilai, unit, resolusi acuan, semantik renderer,
label bukti, confidence, dan pengaruhnya terhadap layout. Font yang mirip secara
visual belum membuktikan nama font asli. Jika fallback digunakan, catat nama
font aktual dan ukur ulang seluruh layout.

## 3. Klasifikasi sebelum fitting angka

Klasifikasi wajib diselesaikan sebelum memilih blur, opacity, offset, atau scale.

| Dimensi | Pilihan/contoh |
|---|---|
| Caption type | Editorial serif, social subtitle, karaoke phrase, kinetic title, lower-third, other. |
| Motion primitive | Fade, pop, scale overshoot, slide, stagger, group exit, transform-only. |
| Highlight system | Hero word, color, scale, glow, timing, line break, none. |
| FX family | Shadow, edge light, outer glow, bloom, rim, outline, emission. |
| Glow family | Enam keluarga pada tabel di bawah. |

| Glow family | Perilaku dan arah fitting |
|---|---|
| `none` | Tidak ada halo/emission bermakna. Gunakan pemisahan yang terlihat saja. |
| `subtle_editorial` | Kontur/cahaya kecil, tertahan; edge light dan glow kecil ber-opacity rendah. |
| `outside_halo` | Halo di luar glyph; uji outside-only mask dan falloff sambil menjaga core. |
| `luminous_single` | Satu lapisan luminous dominan; verifikasi sebelum menambah stack. |
| `luminous_multi_layer` | Energi dekat tepi dan falloff lebar; tight, medium, bloom, edge, optional rim/shadow. |
| `neon_emissive` | Emission terang/berwarna; uji akumulasi screen/additive dan isolasi layer. |

Klasifikasi yang salah harus dikoreksi sebelum melanjutkan tuning. Stack
luminous bukan default untuk semua style.

## 4. Rumus geometri dan layout

### Koordinat dan resolusi

Untuk kanvas acuan `W0 × H0` dan kanvas output `W × H`:

```text
x_norm = x_px / W0                 y_norm = y_px / H0
x_out  = x_norm × W                y_out  = y_norm × H
k      = W / W0                    px_out = px_reference × k
```

Rumus skala `k` berlaku untuk perubahan resolusi dengan rasio yang sama; ukuran
font, blur, outline, offset, padding, dan translation mengikuti resolusi acuan
yang dicatat. Perubahan rasio membutuhkan fitting layout ulang dan tidak boleh
meregangkan glyph. Di dalam video card, gunakan koordinat lokal card, lalu
tambahkan offset card ketika ditempel ke kanvas akhir. Safe area card dan safe
area kanvas harus sama-sama diperiksa.

### Pengukuran, footprint, fit, dan clamp

Ukur teks dengan font aktual sebelum animasi. Jika bbox adalah `(l,t,r,b)`:

```text
glyph_width  = r - l
glyph_height = b - t
draw_origin  = (padding_left - l, padding_top - t)
```

Ukuran akhir mencakup glyph, stroke, shadow offset, seluruh dukungan blur,
padding, hero/emphasis scale, dan peak scale motion. Jangan hanya memvalidasi
ukuran glyph normal. Tentukan padding dari stack efek dan uji tepi patch;
`3 × blur_radius` merupakan perkiraan awal untuk Gaussian, bukan bukti bahwa
seluruh halo sudah aman. Hindari menghitung stroke/padding dua kali jika
keduanya sudah termasuk bbox atau patch yang diukur.

Untuk patch penuh yang sudah diukur `P_w × P_h`, peak scale `s_max`, dan ruang
yang tersedia `A_w × A_h`:

```text
fit = min(1, A_w / (P_w × s_max), A_h / (P_h × s_max))
```

Nilai `fit` dikunci sebelum motion. Maksimum footprint sesudah fit harus muat
pada area aman. Untuk area `[L,R] × [T,B]` dan ukuran layer final `F_w × F_h`:

```text
x_center = clamp(x_requested, L + F_w/2, R - F_w/2)
y_center = clamp(y_requested, T + F_h/2, B - F_h/2)
```

Clamp hanya valid jika `F_w <= R-L` dan `F_h <= B-T`. Jika belum muat, kecilkan
font/fit atau ubah line break yang disetujui, ukur ulang, lalu clamp. Jangan
mengembalikan primary anchor yang belum divalidasi dari fallback. Setelah paste,
pastikan batas final aman terhadap frame/card dan area subjek.

### Layout samping dan hero axis

Untuk style pembicara di samping, tentukan negative space dan area wajah,
badan, mikrofon, serta tangan dari footage. Urutan penempatan: dominant
dark-side lane → secondary side lane → center sebagai emergency fallback.
Angka lane prototype di bagian 7 adalah contoh untuk footage tersebut.

Kunci seluruh word/line positions sebelum reveal; kata baru tidak boleh
menggeser kata lama. Untuk Editorial Focus, hero line pertama menentukan
sumbu; jika tidak ada hero, gunakan baris terlebar:

```text
hero_axis = outer_anchor + hero_width/2     # blok kiri
hero_axis = outer_anchor - hero_width/2     # blok kanan
line_center = hero_axis + role_offset
```

Hero memakai offset nol. Supporting lines memakai offset stabil sesuai peran.
Clamp dilakukan pada seluruh blok. Jangan menurunkan sumbu dari baris terlebar
ketika ada hero, mengacak offset per frame, atau meniru arah komposisi dengan
skew/perspective/deformasi glyph.

## 5. Rumus cue dan motion

Pisahkan model satu kata, phrase, dan grup kata. Grup memiliki `group_start`
dan `group_end`; kata memiliki `appear_offset`, posisi, ukuran, emphasis, dan
profil motion. Waktu tampil absolut kata adalah:

```text
t_appear = group_start + appear_offset
p_enter  = clamp((t - t_appear) / duration_enter, 0, 1)
p_exit   = clamp((t - (group_end - duration_exit)) / duration_exit, 0, 1)
value    = v0 + (v1 - v0) × E(p)
```

Gunakan durasi positif dan unit waktu konsisten; `seconds = milliseconds/1000`.
Kata tidak terlihat sebelum `t_appear`; grup tidak terlihat di luar
`[group_start, group_end)`. Validasi `group_end > group_start` dan waktu masuk
kata berada di dalam grup. Words accumulate dan shared exit hanya digunakan
jika memang terlihat dalam referensi; one-word style tetap satu kata per cue.

Contoh easing yang tersedia sebagai keluarga fitting:

```text
cubic ease-out: E(p) = 1 - (1-p)^3
sine ease-out:  E(p) = sin(p × π/2)
```

Keduanya berbeda; jangan menggantinya diam-diam. Untuk cubic-bezier, cari
parameter kurva `u` yang memenuhi `Bezier_x(u)=p`, lalu gunakan `Bezier_y(u)`.
Jangan langsung memperlakukan waktu sebagai parameter kurva tanpa memeriksa
semantik renderer. Profil memakai keyframe normalisasi yang terurut; setiap
segmen diinterpolasi dengan easing yang dicatat.

Pop biasanya menggunakan `scale_start < 1 → scale_peak > 1 → 1`. Anchor scale
tetap pada center yang dikunci. Float mengikuti translation menuju posisi
settled. Motion hanya mengubah transform, opacity, dan blur transisi yang
ditetapkan; tidak mengukur/wrap ulang teks setiap frame. Blur motion dan blur
FX statis tetap dua parameter terpisah.

## 6. Rumus alpha, glow, dan kontrak renderer

Dengan alpha dan RGB dalam rentang `[0,1]`, source-over straight alpha:

```text
a_out = a_src + a_dst × (1-a_src)
C_out = (C_src × a_src + C_dst × a_dst × (1-a_src)) / a_out
```

Jika `a_out=0`, hasil transparan. Untuk premultiplied alpha, RGB sudah
mengandung faktor alpha dan tidak dikalikan ulang. Terapkan opacity ke layer
sekali, lalu composite sekali. Hindari alpha ganda saat paste/masking.

Konsep outside-only mask:

```text
M_outside = clamp(GaussianBlur(M_glyph, radius) - M_glyph, 0, 1)
```

Soft exclusion dapat dipakai untuk menghindari cincin keras. Pilih outside
mask jika target adalah `outside_halo` atau glow mengotori core. Jangan
menggunakan glow untuk menutupi glyph yang tidak terbaca.

Contoh akumulasi RGB untuk light stack:

```text
screen(A,B)   = 1 - (1-A) × (1-B)
additive(A,B) = min(1, A+B)
```

Ini adalah rumus blend RGB, bukan pengganti kontrak alpha. Catat color space,
straight/premultiplied alpha, masking, dan cara akumulasi yang digunakan;
screen dan additive tidak menghasilkan output yang sama. Verifikasi isolasi
layer dan hasil compositing sebelum fitting artistic. Stack luminous dari
belakang ke depan: broad bloom → medium glow → tight glow → edge light →
sharp main glyph; posisi shadow/rim didokumentasikan sesuai target.

Syarat renderer sebelum tuning:

- Blur memiliki mapping yang diketahui: tidak ada pembagian/skala tersembunyi.
- Text shaping, font aktual, line breaks, layout, dan transform anchor stabil.
- Padding tidak memotong outline, shadow, rim, atau bloom di patch boundary.
- Setiap layer dapat diisolasi; gunakan debug color untuk menilai halo.
- Stills memakai PNG lossless sebelum menilai output terkompresi.
- Output transparan memakai format/codec yang menjaga alpha; H.264 MP4 biasa
  untuk preview/composite, bukan penyimpanan layer RGBA transparan.

## 7. Enam keluarga dan fitted values referensi

Semua angka berikut adalah titik awal fitting dari dokumen/preset referensi,
bukan default CAPIO atau setting editor asli. Seluruh profil contoh memakai
30 fps. Cue demo hanya contoh opening/motion; teks serta timing produksi harus
berasal dari transkrip yang sudah ditinjau.

| Keluarga | Kanvas acuan dan tipografi | Layout/model cue | Motion dan FX contoh |
|---|---|---|---|
| Soft Focus V7 | 1080×1920; Georgia Bold 62 px, hero 1.08 | Center blok `(0.73,0.37)`, max width 0.39, maksimal 3 baris; layout terkunci | Enter normal 180 ms, hero 200 ms, exit 120 ms; core tajam; mode subtle, luminous single, atau multi. |
| Editorial Focus V5 | 1024×576; Arial Bold 52 px, hero 1.12 | Outer side anchor, margin 0.05, max width 0.45; sumbu hero | Enter normal 160 ms, hero 220 ms, exit 140 ms; shadow hitam blur 6 px/opacity 0.48/offset y=2; glow/bloom mati. |
| Kinetic Words V5 | 576×1024; Impact/condensed uppercase, base 64 px | Grup persistent, appear offset per kata, stacked pair dan shared exit, dark-side-first | Normal 120 ms; emphasis 190 ms: scale 0.80→1.10→1; exit 80 ms; outline 3 px, shadow blur 4 px/opacity 0.70/offset y=4; broad bloom/neon mati. |
| Soft Phrase V1 | 576×1024; Georgia Bold 55 px, hero 1.55 | Center `(0.50,0.57)`, max width 0.86, margin 0.05; 1–3 baris | Enter 150 ms, scale 0.88→1.04→1; exit target 110 ms; warm white `(250,248,242)`, dark outline 2 px, shadow separation y=3. |
| Single Word Float V1 | 576×1024; Georgia Bold 54 px | Satu kata per cue; center `(0.50,0.58)`, max width 0.72, margin 0.05 | Enter 170 ms, scale 0.88→1.035→1, float 7 px; fade replacement 100 ms; white/dark outline 2 px/shadow y=3. |
| Scatter Emphasis V1 | 576×1024; Georgia Bold 42 px, emphasis 1.12 | Aktor kata independen, explicit positions/entry, lifetime grup; central box x=0.08–0.92, y=0.33–0.66 | Enter 170 ms, scale 0.88→1.06→1, float 8 px, exit 120 ms; normal warm white, emphasis yellow `(255,232,0)`, outline 2 px/shadow y=3. |

Contoh lane Kinetic: dominant x=0.68–0.90, secondary x=0.05–0.32,
y=0.30–0.75; emergency center x=0.38–0.62, y=0.50–0.75. Subject safe zone
contoh x=0.20–0.68, y=0.10–0.80. Tumpang tindih zona pada preset tidak memberi
izin menutup subjek; posisi final tetap harus lolos collision/footprint test.

Contoh Editorial hero-axis offsets pada lebar 1024 px:

| Peran | Blok kiri | Blok kanan |
|---|---:|---:|
| Supporting above | +30 px | -30 px |
| Hero | 0 px | 0 px |
| Supporting below | +18 px | -18 px |
| Supporting last | +34 px | -34 px |

Contoh luminous dalam panduan v2.1 dan preset V7 berbeda intensitasnya. Simpan
sebagai dua sumber fitted values berbeda; jangan gabungkan menjadi satu
klaim baseline yang sama:

| Layer | Blur acuan | Opacity contoh guide v2.1 | Opacity preset V7 |
|---|---:|---:|---:|
| Tight glow | 4 px | 0.30 | 0.75 |
| Medium glow | 14 px | 0.24 | 0.45 |
| Broad bloom | 32 px | 0.14 | 0.25 |
| Edge light | 1.5 px | 0.48 | 0.60 |
| Directional rim | 1.5 px, offset (-1,-1) px | 0.25 | 0.30 |

Guide memakai warm-white core `(248,244,236)`; preset V7 memakai putih dengan
glow berwarna warm white. Pilih baseline dengan A/B terhadap video sebenarnya.
Jika rim offset membulat menjadi nol pada resolusi kecil, gunakan jalur subpixel
atau offset minimal satu piksel dan catat perubahan fitted value.

Catatan pembacaan prototype: keberadaan parameter belum membuktikan efeknya
aktif. Misalnya Soft Phrase V1 mendeklarasikan `exit_ms` tetapi fungsi render
yang dibaca belum menerapkan exit; beberapa renderer V1 memakai tuple shadow
untuk offset/fill tanpa menerapkan Gaussian blur yang digambarkan di laporan.
Preset Kinetic dalam folder V5 juga masih ber-ID `kinetic_word_v4`. Karena itu
identitas versi, semantik efek, alpha, dan safety harus diverifikasi pada renderer
CAPIO aktual, bukan diambil dari nama variabel/README saja. Kekurangan prototype
tidak menjadi aturan baru yang wajib ditiru.

## 8. Alur ekstraksi dan revisi

1. Baca permintaan, brief, video, dan bukti implementasi sesuai perannya.
2. Amati stills serta motion sequence representatif: entrance, peak, hold,
   pair-complete, replacement, shared exit, long words, dan perpindahan blok.
3. Catat canvas/fps, safe area, subject area, typography, segmentation,
   line breaks, emphasis, timing, scale/translation, shadow, dan halo falloff.
4. Klasifikasikan caption, motion, highlight, FX, dan glow family.
5. Ukur nilai observed dan beri alasan untuk inferred architecture.
6. Susun fitted parameters lengkap dengan unit/semantik/confidence; verifikasi
   renderer conformance dan kunci layout sebelum artistic tuning.
7. Render kalimat, cue, background, font, resolusi, dan timing yang deterministik.
   Bandingkan layer isolation dahulu, lalu complete stack dan composite footage.
8. Terima feedback; ubah satu keluarga parameter, kunci keluarga lainnya, dan
   simpan A/B serta log revisi: feedback, baseline, perubahan, hasil, keterbatasan.
9. Kunci preset yang lolos penilaian dengan versi renderer, sumber, fitted values,
   frozen elements, dan known limitations. Simpan baseline sebelumnya.

| Feedback | Parameter yang diperiksa |
|---|---|
| Kurang nyala | Emission stack, tight/medium glow. |
| Kurang cahaya di tepi | Edge light, tight glow, directional rim. |
| Cahaya kurang jauh | Medium glow dan broad bloom. |
| Terlalu berkabut | Kurangi radius/opacity broad bloom. |
| Huruf terlalu tebal | Outline dan glow contamination; periksa outside mask sebelum mengganti weight/font. |
| Terlalu neon | Kurangi emission/additive intensity. |
| Terlalu kecil/besar | Per-word size dan hero/emphasis scale, lalu ulang footprint check. |
| Menutup pembicara | Lane, cue position, dan subject safe zone. |
| Tiba-tiba ke tengah | Lane priority/fallback; center hanya emergency untuk style samping. |
| Gerakan kaku/lemah | Motion keyframes, easing, scale, durasi. |
| Jitter | Precomputed measurement/layout dan transform anchor. |
| Pair hilang keliru | Group lifetime, persistence, shared exit. |
| Keluar frame | Final footprint, fit, patch padding, dan clamp. |

Jika feedback tentang FX, typography/layout/segmentation/timing/motion tetap
dikunci. Jika tentang motion, FX dikunci. Ulang klasifikasi hanya ketika bukti
menunjukkan keluarganya salah.

## 9. Format brief hasil ekstraksi wajib

Ekstraktor menghasilkan brief yang dapat digunakan untuk implementasi. Urutan
section berikut wajib; isi aspek yang tidak terlihat/tidak relevan dengan
status yang jelas, bukan dengan parameter rekaan:

1. **Header:** project, reference source/rentang, style family, glow family,
   canvas/fps, confidence, goal.
2. **Executive Summary:** ciri utama dan target visual terukur.
3. **Observed Visual Findings:** typography, layout, motion, FX, highlight;
   setiap pengamatan merujuk frame/waktu.
4. **Inferred Implementation:** arsitektur yang diduga, alasan, alternatif
   yang ditolak, confidence.
5. **Fitted CAPIO Parameters:** nilai main glyph, shadow, edge, tight/medium
   glow, bloom, rim, layout, cue, dan motion yang relevan; unit, resolusi,
   semantik renderer, confidence, dan efek terhadap layout.
6. **Engine Requirements:** kemampuan yang dibutuhkan dan perilaku yang
   harus dihindari; cek dukungan renderer yang sudah tersedia.
7. **Implementation Priority:** renderer correctness → layout stability →
   main glyph → shadow/edge → glow architecture bila ada → motion polish.
8. **Required Tests:** layer isolation, entrance/peak/hold/exit, boundary,
   subject safety, motion, final A/B.
9. **Human Feedback Mapping:** feedback → parameter family; keluarga yang
   tetap dikunci pada iterasi itu.
10. **Frozen Elements:** font, weight, base size, segmentation, line breaks,
    posisi, frame/fps, group behavior, dan renderer semantics yang disepakati.
11. **Final Task for Engine Agent:** perubahan konkret dan acceptance criteria
    untuk renderer CAPIO yang ada, sesuai instruksi pengguna.
12. **Deliverables:** preset/config/brief, implementation changes bila diminta,
    PNG, motion/composite preview, comparison sheet, dan laporan singkat.
13. **Confidence/Limitations:** bagian belum pasti, font substitusi, cue demo,
    kompresi, parameter tidak didukung, serta batas klaim original settings.

Brief ekstraksi tidak otomatis berarti pembangunan engine sudah diizinkan.
Untuk permintaan rumus/aturan saja, deliverable adalah dokumen ini.

## 10. QA dan kriteria penguncian

Pemeriksaan berikut berlaku saat mengimplementasikan atau mengubah render:

- Main-only, shadow-only, outline/edge-only, tight-glow-only, medium-glow-only,
  broad-bloom-only, dan complete-stack; hanya layer yang relevan dengan style.
- Entrance pertama, peak scale, hold, pair/group-complete, replacement, shared
  exit, dan batas cue. Seluruh glyph serta FX mengikuti opacity/exit yang sama
  ketika referensi menunjukkan satu grup menghilang bersama.
- Kata pendek/lebar/panjang dan stacked group di seluruh lane. Contoh stres
  Kinetic: NUNGGU 86 px, MELAKUKAN 78 px, APAPUN 84 px, MEREKA/BISA bertumpuk,
  semuanya di scale peak 1.10 pada resolusi acuan.
- Editorial kiri/kanan: hero lebih lebar dan lebih pendek daripada supporting
  line, beberapa supporting lines, zero-offset vs hero-axis offset, debug axis,
  perpindahan grup, blur/shadow padding, dan edge clamp.
- Preview caption-only dan composite di footage sebenarnya; PNG lossless dan
  comparison sheet pada timestamp/frame yang sama. Source burned-in captions
  yang masih terlihat dalam composite demo bukan bukti output produksi bersih.
- Tidak ada clipping, overflow, jitter, per-frame reflow, collision subjek
  yang tidak disetujui, atau redesign style yang tidak diminta.

Preset dikunci setelah still dan motion cocok, glyph terbaca, glow sesuai
klasifikasi, timing/grup tepat, safety lolos, dan fitted values/frozen elements/
renderer version/limitations tercatat. Perubahan satu keluarga tidak boleh
menghilangkan hasil yang sudah lolos pada keluarga lain.

## 11. Penggunaan di CAPIO dan pemeliharaan

Pada branch yang memiliki modul terkait, kontrak pengguna ada di `template.md`,
validasi konfigurasi di `pipeline/templates.py`, overlay caption khusus di
`pipeline/reference_caption.py`, dan geometri di `pipeline/composition.py`.
Pelajari jalur yang berlaku pada branch tersebut dan gunakan renderer/helper
yang sudah tersedia ketika implementasi diminta.

Nama parameter panduan bukan janji API CAPIO. Jangan meneruskan fitted knobs
yang belum didukung melalui adjustment job. Penggantian font atau canvas dari
referensi ke CAPIO harus dicatat sebagai adaptasi dan diuji visual ulang.

Panduan ini tidak mengubah renderer, default template, API, Agent clipping,
atau dependensi. Tidak menyertakan prototype, media output, cue demo, arsip
versi lama, maupun cache. Pembaruan rumus/aturan disebarkan ke branch lokal
yang dipelihara; branch baru harus membawa `AGENTS.md` dan panduan ini ketika
pekerjaan template dilanjutkan.
