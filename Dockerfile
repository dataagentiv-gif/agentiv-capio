# Satu image dipakai dua service (api dan worker) — bedanya cuma argumen
# perintah. Memisahkannya jadi dua image berarti dua kali build dan dua kali
# unduh dependency yang isinya identik.
FROM python:3.12-slim

# ffmpeg wajib ada di dalam image: hampir semua stage memanggilnya, dan versi
# distro sudah membawa libx264, libopus, dan libass yang dibutuhkan.
# libgl1 + libglib2.0-0 dibutuhkan OpenCV yang ikut terbawa MediaPipe.
#
# libegl1 WAJIB, dan ketiadaannya tidak menjatuhkan job — itulah bahayanya.
# MediaPipe menautkan libEGL.so.1 saat FaceDetector dibuat, dan Stage 6 sengaja
# menangkap kegagalan deteksi lalu jatuh ke center crop supaya satu wajah yang
# tidak terdeteksi tidak menggagalkan seluruh job. Tanpa paket ini, kegagalannya
# permanen dan senyap: seluruh klip keluar center crop, pipeline melaporkan
# sukses, dan pelacakan wajah — fitur inti 9:16 — tidak pernah benar-benar
# berjalan. Terjadi sungguhan; baru ketahuan saat log crop dihitung satu per satu.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1

WORKDIR /app

# Disalin duluan dan sendirian supaya layer dependency tidak ikut ter-build
# ulang setiap kali ada satu baris kode yang berubah.
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 600 --retries 10 -r requirements.txt

COPY . .

# A release image must carry licensed copies of the exact reference fonts.
# Local test builds may set this to 0 and mount a read-only font directory.
ARG CAPIO_REQUIRE_LICENSED_FONTS=1
RUN if [ "$CAPIO_REQUIRE_LICENSED_FONTS" = 1 ]; then \
        for font in georgiab.ttf impact.ttf arialbd.ttf; do \
            test -f "/app/assets/reference-fonts/$font" || \
                { echo "Missing licensed caption font: $font" >&2; exit 1; }; \
        done; \
    fi
ENV CAPIO_REFERENCE_FONT_DIR=/app/assets/reference-fonts

# Font caption dipasang ke sistem supaya libass menemukannya lewat fontconfig.
#
# Tanpa ini image cuma punya DejaVu, dan nama font apa pun yang ditulis di .ass
# diam-diam diganti: `fc-match Arial` mengembalikan DejaVu Sans "Book" — bahkan
# bukan versi tebalnya. Caption tetap terender, jadi tidak ada tanda apa pun
# bahwa yang tampil bukan font yang diminta.
#
# fc-cache WAJIB: tanpanya berkas ada di disk tapi fontconfig tidak
# mengetahuinya, dan gejalanya persis sama dengan font yang tidak terpasang.
RUN mkdir -p /usr/share/fonts/truetype/capio \
    && cp assets/fonts/*.ttf /usr/share/fonts/truetype/capio/ \
    && fc-cache -f > /dev/null

# Berjalan sebagai non-root. Kalau container jebol, penyerang tidak langsung
# dapat root di dalamnya.
# /app/data WAJIB ikut dibuat di sini, bukan dibiarkan muncul sendiri saat
# volume dipasang. Kalau direktorinya tidak ada di dalam image, Docker yang
# membuat titik mount-nya saat container start — dan miliknya root, sementara
# proses berjalan sebagai clipper. Akibatnya verifikasi lisensi jatuh dengan
# PermissionError pada /app/data/license.json, muncul sebagai HTTP 500 di
# halaman Setting, di SETIAP pemasangan baru.
#
# Tidak pernah ketahuan selama pengembangan karena satu-satunya yang menulis ke
# sana adalah verifikasi lisensi, dan itu belum pernah benar-benar berjalan di
# dalam container sebelum alamat server bisa ditimpa.
RUN useradd -m -u 1000 clipper \
    && mkdir -p /work /app/clips /app/data \
    && chown -R clipper:clipper /app /work
USER clipper

EXPOSE 8000
CMD ["python", "main.py", "api"]
