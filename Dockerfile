# Satu image dipakai dua service (api dan worker) — bedanya cuma argumen
# perintah. Memisahkannya jadi dua image berarti dua kali build dan dua kali
# unduh dependency yang isinya identik.
FROM python:3.12-slim

# ffmpeg wajib ada di dalam image: hampir semua stage memanggilnya, dan versi
# distro sudah membawa libx264, libopus, dan libass yang dibutuhkan.
# libgl1 + libglib2.0-0 dibutuhkan OpenCV yang ikut terbawa MediaPipe.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1

WORKDIR /app

# Disalin duluan dan sendirian supaya layer dependency tidak ikut ter-build
# ulang setiap kali ada satu baris kode yang berubah.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Berjalan sebagai non-root. Kalau container jebol, penyerang tidak langsung
# dapat root di dalamnya.
RUN useradd -m -u 1000 clipper \
    && mkdir -p /work /app/clips \
    && chown -R clipper:clipper /app /work
USER clipper

EXPOSE 8000
CMD ["python", "main.py", "api"]
