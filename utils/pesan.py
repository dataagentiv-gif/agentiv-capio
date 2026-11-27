"""Menerjemahkan kegagalan jadi kalimat yang bisa ditindaklanjuti orang biasa.

Pesan kegagalan yang tersimpan di database adalah teks untuk yang menulis
kodenya: nama kelas exception, potongan JSON balasan API, lalu traceback
Python. Untuk yang memakai alat ini, semua itu bukan sekadar sulit dibaca — ia
tidak menyebutkan satu pun hal yang bisa DILAKUKAN. Contoh nyata:

    RuntimeError: ElevenLabs HTTP 401: {"detail":{"type":"invalid_request",
    "code":"quota_exceeded","message":"This request exceeds your quota of
    10000. You have 704 credits remaining, while 965 credits are required..."}}

Yang sebenarnya terjadi: jatah transkrip bulan ini habis, dan solusinya
menambah API key kedua di halaman Setting. Tidak satu kata pun di atas
mengatakan itu.

Diterjemahkan SAAT DITAMPILKAN, bukan saat kegagalannya terjadi. Dua alasan:
job lama yang sudah tersimpan ikut mendapat penjelasannya tanpa migrasi apa
pun, dan teks mentahnya tetap utuh di database — kalau terjemahannya salah,
yang hilang cuma terjemahannya.
"""
import re

#: Nama penyedia beserta tempat mengurus key-nya. Diambil dari teks mentah,
#: supaya satu aturan ("kuota habis") bisa melayani semua penyedia tanpa
#: ditulis ulang per penyedia.
PENYEDIA = {
    "gemini": ("Gemini", "aistudio.google.com/apikey"),
}

UMUM = "Tunjukkan detail teknis di bawah ke orang yang memasang CAPIO."


def _penyedia(teks: str) -> tuple[str, str]:
    for kunci, (nama, tautan) in PENYEDIA.items():
        if kunci in teks:
            return nama, tautan
    return "penyedia transkrip/AI", "halaman Setting"


def _kuota(teks: str) -> tuple[str, str]:
    nama, tautan = _penyedia(teks)
    return (
        f"Jatah pemakaian {nama} sudah habis",
        f"Ini bukan kesalahan video atau setelanmu — kuotanya memang sudah "
        f"terpakai. Tambahkan API key {nama} yang lain di halaman Setting "
        f"(boleh lebih dari satu, dipakai bergiliran otomatis), atau tunggu "
        f"kuotanya diperbarui. Key baru diambil di {tautan}.",
    )


def _ditolak(teks: str) -> tuple[str, str]:
    nama, tautan = _penyedia(teks)
    return (
        f"API key {nama} ditolak",
        f"Key-nya ada, tapi {nama} tidak menerimanya — biasanya karena salah "
        f"tempel, sudah dihapus, atau dibuat untuk akun lain. Buka halaman "
        f"Setting, hapus key itu, lalu tempel yang baru dari {tautan}.",
    )


def _kosong(teks: str) -> tuple[str, str]:
    nama, tautan = _penyedia(teks)
    return (
        f"API key {nama} belum diisi",
        f"CAPIO butuh key ini untuk bekerja. Buka halaman Setting, lalu tempel "
        f"key dari {tautan}.",
    )


def _model(teks: str) -> tuple[str, str]:
    nama, _ = _penyedia(teks)
    return (
        f"Nama model {nama} sudah tidak berlaku",
        f"Key-nya kemungkinan besar tidak apa-apa — yang perlu diganti nama "
        f"modelnya. Buka halaman Setting → API Key → Lanjutan, lalu pakai nama beralias "
        f"yang berakhiran -latest (misalnya gemini-flash-lite-latest): alias "
        f"selalu menunjuk versi terbaru, jadi ia tidak ikut pensiun. Tekan "
        f"'Tes {nama.lower()}' untuk memastikan sebelum memproses video.",
    )


def _batas(teks: str) -> tuple[str, str]:
    nama, _ = _penyedia(teks)
    return (
        f"{nama} sedang membatasi jumlah permintaan",
        "Terlalu banyak permintaan dalam waktu singkat. Tunggu beberapa menit "
        "lalu proses ulang videonya. Kalau sering terjadi, tambahkan API key "
        "kedua di halaman Setting supaya beban terbagi.",
    )


def _sambung(teks: str) -> tuple[str, str]:
    nama, _ = _penyedia(teks)
    return (
        f"Tidak bisa menghubungi {nama}",
        "Koneksi internetnya terputus di tengah jalan, atau layanannya sedang "
        "bermasalah. Periksa koneksi lalu proses ulang videonya.",
    )


#: Diperiksa BERURUTAN, yang lebih khusus lebih dulu. "quota_exceeded" pernah
#: datang bersama HTTP 401, jadi kalau aturan "key ditolak" diperiksa duluan,
#: kehabisan kuota akan salah dilaporkan sebagai key yang salah — dan orangnya
#: menghapus key yang sebetulnya baik-baik saja.
ATURAN: list[tuple[tuple[str, ...], object]] = [
    (("job lama tidak memakai library template",), (
        "Job memakai tampilan versi lama",
        "Job ini tidak dapat diproses ulang. Kirim lagi sumber videonya dari halaman Submit dan pilih salah satu template baru.",
    )),
    (("worker berhenti saat job",), (
        "Pemrosesan terhenti karena worker berhenti",
        "Nyalakan kembali Docker dan container CAPIO, lalu tekan Proses ulang "
        "pada job ini. Browser boleh ditutup saat proses berjalan, tetapi "
        "Docker, container worker, dan komputer harus tetap menyala.",
    )),
    (("quota_exceeded", "exceeds your quota", "insufficient_quota",
      "credits remaining", "resource_exhausted", "out of credits"), _kuota),
    # Diperiksa SEBELUM aturan "key ditolak": nama model yang salah dijawab 404,
    # dan tanpa aturan ini pesannya jatuh ke "belum dikenali" — lalu orangnya
    # menghapus key yang baik-baik saja. Google memensiunkan nama model
    # berversi untuk akun baru sementara akun lama tetap bisa memakainya, jadi
    # setelan yang diwarisi dari mesin lain bisa mati di mesin ini saja.
    (("no longer available", "is not found for api version", "http 404",
      "model tidak ditemukan"), _model),
    (("api key kosong", "tidak ada api key"), _kosong),
    (("invalid api key", "invalid_api_key", "unauthorized", "api key not valid",
      "invalid authentication", "http 401", "http 403"), _ditolak),
    (("rate limit", "rate_limit", "too many requests", "http 429"), _batas),

    # Penandanya memuat DUA bahasa, dan itu bukan kelebihan. Stage download
    # sudah menerjemahkan sebabnya lebih dulu lalu menempelkan teks aslinya
    # sebagai "Detail: ...", jadi yang tersimpan bisa memuat salah satu atau
    # keduanya — tergantung apakah terjemahan di sana kena.
    (("sign in to confirm", "not a bot", "captcha", "verifikasi bot"), (
        "YouTube meminta verifikasi bahwa kamu bukan robot",
        "YouTube membatasi unduhan dari koneksi ini. Coba dari jaringan rumah "
        "(bukan kantor, kampus, atau VPN). Kalau tetap kena, videonya perlu "
        "diunduh manual dulu.",
    )),
    (("private video", "members-only", "login required",
      "private atau khusus member"), (
        "Videonya private atau khusus member",
        "CAPIO cuma bisa membuka video yang bisa ditonton siapa saja. Pastikan "
        "videonya publik atau unlisted, bukan private.",
    )),
    # Penandanya berupa FRASA, bukan kata lepas seperti "geo" atau "blocked".
    # Kata lepas sepanjang tiga huruf akan cocok di tengah kata lain dan
    # menghasilkan diagnosis yang salah dengan penuh percaya diri.
    (("not available in your country", "diblokir untuk wilayah",
      "geo-restricted", "geo restriction", "video is blocked"), (
        "Video ini diblokir di wilayah kita",
        "Pemiliknya membatasi video ini untuk negara tertentu. Coba video lain.",
    )),
    (("video unavailable", "has been removed", "does not exist",
      "tidak tersedia atau sudah dihapus"), (
        "Videonya sudah tidak ada",
        "Link-nya benar, tapi videonya sudah dihapus atau diubah jadi private. "
        "Coba buka link itu di browser untuk memastikan.",
    )),
    (("no space left", "not enough space", "disk full", "errno 28",
      "ruang disk habis"), (
        "Ruang penyimpanan di komputer ini habis",
        "Hapus beberapa video lama dari halaman Proses untuk mengosongkan "
        "ruang, lalu coba lagi. Video yang gagal sengaja tidak dibersihkan "
        "otomatis supaya bisa diperiksa, jadi ia ikut memakan ruang.",
    )),

    (("deadline job terlampaui", "waktu job habis", "timeoutexpired",
      "timed out"), (
        "Waktunya habis sebelum selesai",
        "Videonya terlalu panjang, atau internetnya sedang lambat sehingga "
        "unduhannya belum selesai saat waktu habis. Coba video yang lebih "
        "pendek, atau naikkan batas waktu di halaman Setting → Klip → Lanjutan.",
    )),
    (("transkrip kosong", "tanpa suara"), (
        "Tidak ada suara yang bisa dikenali di video ini",
        "CAPIO bekerja dari ucapan, jadi video musik, gameplay tanpa narasi, "
        "atau video bisu tidak bisa diproses. Pakai video yang ada orang "
        "bicaranya.",
    )),
    (("tidak ada segmen lolos validasi",), (
        "Tidak ada momen valid untuk parameter klip ini",
        "Belum ada kandidat yang memenuhi validasi seleksi. CAPIO memberi satu "
        "kesempatan koreksi tanpa memaksakan jumlah klip. "
        "Lihat Detail teknis untuk alasan penolakan seperti durasi, batas potongan, atau "
        "tumpang tindih. Jumlah klip tidak dipaksakan.",
    )),
    (("tidak ada segmen lolos",), (
        "Tidak ada bagian yang cocok dijadikan klip",
        "Isi videonya tidak punya momen yang berdiri sendiri dengan durasi "
        "yang diminta — biasanya terjadi pada video yang sangat pendek atau "
        "yang pembicaraannya mengalir tanpa jeda. Coba longgarkan rentang "
        "durasi klip di halaman Setting.",
    )),
    (("face detector tidak ada", "libegl", "libgles", "mediapipe"), (
        "Pemasangan CAPIO belum lengkap",
        "Salah satu komponen pengenal wajah tidak terpasang di komputer ini. "
        + UMUM,
    )),
    (("ffmpeg keluar dengan kode", "ffprobe keluar dengan kode"), (
        "Video ini gagal diolah",
        "Berkas videonya kemungkinan rusak atau formatnya tidak lazim. Coba "
        "video lain; kalau video lain berhasil, masalahnya ada di video itu.",
    )),
    (("connection", "timeout", "temporary failure", "network"), _sambung),
]

CADANGAN = (
    "Pemrosesan berhenti karena masalah yang belum dikenali",
    "Ini bukan sesuatu yang bisa diperbaiki dari halaman ini. " + UMUM,
)


def terjemah(mentah: str | None) -> dict | None:
    """{'judul', 'saran'} — atau None kalau memang tidak ada kegagalan."""
    if not mentah or not mentah.strip():
        return None

    teks = mentah.lower()
    for penanda, hasil in ATURAN:
        if any(p in teks for p in penanda):
            judul, saran = hasil(teks) if callable(hasil) else hasil
            return {"judul": judul, "saran": saran}

    judul, saran = CADANGAN
    return {"judul": judul, "saran": saran}


def ringkas(mentah: str | None, batas: int = 400) -> str:
    """Teks mentah yang dirapikan untuk blok detail teknis.

    Traceback dipotong dari BELAKANG, bukan dari depan: baris terakhir memuat
    exception yang sebenarnya, sementara baris awal cuma rantai pemanggil yang
    sama untuk hampir semua kegagalan.
    """
    if not mentah:
        return ""
    teks = re.sub(r"\n{3,}", "\n\n", mentah.strip())
    return teks if len(teks) <= batas else "…" + teks[-batas:]
