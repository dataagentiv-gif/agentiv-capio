"""Satu-satunya sumber konfigurasi. Modul lain tidak boleh baca os.environ sendiri.

`.env` ada di root project (sejajar main.py), bukan di dalam folder ini — folder
config/ berisi kode pembaca konfigurasi, bukan kredensialnya.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Transkrip (Stage 2) & Seleksi momen/metadata (Stage 3 & 8) ---
    #
    # Semuanya lewat Gemini sekarang — satu key, dua tugas. Groq (halusinasi
    # bahasa: 29,6% keluaran jadi TEKS JEPANG pada satu dari tiga video
    # Indonesia berisi istilah Inggris) dan ElevenLabs (akurat tapi free tier
    # cuma ~15 video/bulan, seperlimapuluh dari jatah Gemini) sudah dibuang.
    # ASR_PROVIDER / LLM_PROVIDER / ELEVENLABS_* / OPENROUTER_* yang masih
    # tertulis di .env lama diabaikan tanpa error (extra="ignore" di atas).
    #
    # Gemini dipanggil langsung (endpoint OpenAI-compatible milik Google).
    # Boleh diisi lebih dari satu key dipisah koma: free tier Gemini dibatasi
    # PER PROJECT Google Cloud (terukur: dua key satu project habis bersamaan
    # di 28 request gabungan), jadi rotasi hanya menaikkan atap untuk key dari
    # project yang berbeda.
    GEMINI_API_KEYS: str = ""  # "key1,key2,key3"
    # Alias "-latest", BUKAN nomor versi. Google memensiunkan model untuk
    # pengguna baru tanpa menyentuh yang lama: key dari project lama tetap bisa
    # memanggil gemini-2.5-flash-lite, sementara key yang baru dibuat dapat
    # HTTP 404 "no longer available to new users" untuk model yang sama persis.
    # Nomor versi yang di-hardcode artinya default repo ini akan berhenti jalan
    # untuk setiap orang yang baru mencobanya, dan gejalanya menyesatkan —
    # kelihatan seperti key yang salah, padahal modelnya yang sudah ditutup.
    GEMINI_MODEL: str = "gemini-flash-lite-latest"
    # Beberapa model dipisah koma, dicoba BERGILIRAN sama seperti key. Kuota
    # gratis Gemini dihitung PER MODEL, bukan cuma per key — terbukti saat
    # kuota yang habis pulih seketika hanya dengan berpindah model, tanpa
    # menunggu reset harian. Jadi dua sumbu rotasi mengalikan atapnya:
    # 3 key x 3 model memberi 9 jatah yang berdiri sendiri.
    #
    # Bonus yang tidak diduga tapi terukur: saat diuji, gemini-flash-latest dan
    # gemini-3.8-flash dua-duanya menjawab 503 "experiencing high demand" pada
    # setiap percobaan. Dengan satu model, itu job yang gagal. Dengan beberapa,
    # percobaan berikutnya memakai model lain dan job tetap selesai.
    GEMINI_MODELS: str = ""
    # Tarif global lama di .env diabaikan: estimasi kini memakai harga per model.

    # --- Tampilan klip (Stage 5 & 7) ---
    #
    # Layout dipilih UTUH, bukan dipreteli jadi setelan terpisah: posisi teks,
    # geometri kotak, dan arah gradien harus sepakat satu sama lain. Yang di
    # bawahnya adalah knob yang benar-benar berdiri sendiri — diputar
    # bagaimanapun tidak bisa menghasilkan kombinasi yang bertentangan.
    CLIP_LAYOUT: str = "penuh"  # penuh | duo | kotak | samping | ori

    # Font harus SUDAH ADA di image. Nama yang tidak terpasang tidak menghasilkan
    # error apa pun — libass diam-diam menggantinya, dan yang terlihat cuma
    # caption yang "kurang mirip". Yang tersedia: Poppins, Anton, Archivo Black.
    CAPTION_FONT: str = "Poppins"
    CAPTION_SIZE: int = 0       # 0 = ikut bawaan layout
    # RRGGBB seperti yang biasa ditulis orang, BUKAN urutan BGR milik .ass.
    # Nilai lama di kode ditulis "00E5FF" karena itu sudah bentuk BGR-nya;
    # ditulis sebagai RGB, warna yang sama adalah FFE500 (kuning keemasan).
    # Menyalinnya mentah-mentah akan membalik emas jadi biru langit — dan itu
    # tetap terlihat seperti pilihan desain, bukan kesalahan.
    CAPTION_COLOR: str = "FFE500"
    CAPTION_WORDS: int = 0      # 0 = ikut bawaan layout
    CAPTION_UPPER: bool = False

    # Gaya kata yang sedang diucapkan:
    #   text_color       : cuma warnanya berubah (CAPTION_COLOR) — perilaku lama
    #   background       : blok bersudut tumpul di belakang kata aktif
    #   background_scale : blok + kata aktif membesar sedikit
    # Angka di bawah dalam piksel kanvas 1080x1920, dan dipakai hanya oleh dua
    # gaya blok. Radius setengah tinggi blok atau lebih = pil penuh.
    ACTIVE_WORD_STYLE: str = "text_color"
    ACTIVE_WORD_BACKGROUND_COLOR: str = "FFE500"
    ACTIVE_WORD_TEXT_COLOR: str = "000000"
    ACTIVE_WORD_BORDER_RADIUS: int = 18
    ACTIVE_WORD_PADDING_X: int = 18
    ACTIVE_WORD_PADDING_Y: int = 8

    # Folder yang HARUS bertahan melewati update image. Bukan CLIPS_DIR (dikelola
    # pengguna) dan bukan WORK_DIR (disapu berkala): install_id yang hilang saat
    # update berarti slot perangkat baru diklaim tiap ganti versi, dan batas 1
    # atau 3 perangkat habis sendiri tanpa penggunanya berbuat apa-apa.
    DATA_DIR: Path = ROOT / "data"

    # Ditampilkan sebagai versi kecil di nav (_layout.html).
    VERSI: str = "1.7.0"
    AGENTIV_WA: str = "6285843570782"

    DATABASE_URL: str = "postgresql+psycopg://clipper:clipper@localhost:5432/clipper"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Localhost, BUKAN 0.0.0.0. Halaman /settings bisa menulis API key ke .env,
    # jadi mengikatnya ke semua interface berarti siapa pun di jaringan yang sama
    # bisa membaca status kredensial dan menimpanya. Ubah ke 0.0.0.0 hanya kalau
    # memang perlu diakses dari mesin lain, dan sadari konsekuensinya.
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    # Kosong = tanpa autentikasi, aman selama server hanya mendengar di
    # loopback. Diisi = seluruh halaman dan endpoint meminta HTTP Basic dengan
    # nilai ini sebagai password (username diabaikan). Wajib diisi kalau
    # API_HOST diubah ke 0.0.0.0 atau di-tunnel keluar: halaman /settings bisa
    # membaca status kredensial dan menimpanya.
    AUTH_TOKEN: str = ""

    @property
    def host_terbuka(self) -> bool:
        """True kalau server benar-benar terbuka ke jaringan.

        Di dalam container, 0.0.0.0 justru WAJIB — mengikat ke loopback membuat
        service tidak bisa dijangkau sama sekali dari luar container. Yang
        membatasi akses di sana adalah baris `ports` di compose, yang hanya
        mem-publish ke loopback host. Jadi peringatannya dibungkam di container,
        bukan karena aman diabaikan, tapi karena di sana ia salah sasaran.
        """
        if Path("/.dockerenv").exists():
            return False
        return self.API_HOST not in ("127.0.0.1", "localhost", "::1")

    # Klip disimpan sebagai file mp4 biasa di sini. Tidak ada storage cloud di
    # project ini sama sekali.
    CLIPS_DIR: Path = ROOT / "clips"

    # --- Auto clear (api/bersih.py) ---
    #
    # Bawaan MATI: fitur yang menghapus data tidak boleh menyala sendiri setelah
    # update. Umur dihitung dari created_at; job yang antre/berjalan tidak
    # pernah disentuh.
    #   task     : job tanpa klip (gagal, atau klipnya sudah dibuang) + workdir
    #   hasil    : berkas klip dibuang, baris job tetap ada di Riwayat
    #   keduanya : job + klip + workdir, sama dengan tombol Hapus
    AUTO_CLEAR_ENABLED: bool = False
    AUTO_CLEAR_DAYS: int = 30
    AUTO_CLEAR_TARGET: str = "keduanya"

    # --- Guardrail (PRD Bagian 6) ---
    JOB_TIMEOUT_SEC: int = 1800  # 30 menit untuk video referensi 1 jam
    MIN_CLIP_SEC: float = 30.0
    MAX_CLIP_SEC: float = 90.0
    TARGET_CLIPS_DEFAULT: int = 8
    MAX_UPLOAD_MB: int = 2048

    # --- Konkurensi worker ---
    #
    # multi menjalankan beberapa proses worker sekaligus lewat subprocess.Popen
    # di dalam container yang sama (worker/runner.py) — bukan replika container
    # terpisah, supaya bisa diganti dari halaman Setting tanpa menyentuh
    # docker-compose.yml.
    WORKER_MODE: str = "single"   # single | multi
    WORKER_COUNT: int = 2          # dipakai hanya kalau WORKER_MODE = multi

    # --- Kalibrasi pipeline (lihat README bagian Kalibrasi) ---
    # Threshold silencedetect. -30dB cocok untuk podcast bersih; source ber-musik
    # latar butuh -35dB. Kalau daftar silence balik kosong, refine tidak nge-snap
    # sama sekali — itu perilaku yang benar, jangan longgarkan threshold otomatis.
    SILENCE_NOISE_DB: int = -30
    SILENCE_MIN_DUR: float = 0.25
    SNAP_MAX_DRIFT: float = 1.2  # boundary tidak boleh geser lebih dari ini

    # Workdir sengaja pendek. Path Windows mentok di MAX_PATH 260, dan
    # C:\Users\<nama>\AppData\Local\Temp\<uuid>\... sudah makan separuh jatah.
    WORK_DIR: Path = Path("C:/work")

    @staticmethod
    def _pecah(mentah: str) -> list[str]:
        """Entri kosong dan spasi sisa copy-paste dibuang, supaya "key1, key2,"
        tidak menghasilkan key kosong yang dikirim ke API dan balik 400."""
        return [k.strip() for k in mentah.split(",") if k.strip()]

    @property
    def gemini_keys(self) -> list[str]:
        return self._pecah(self.GEMINI_API_KEYS)

    @property
    def gemini_models_kustom(self) -> list[str]:
        """Daftar model yang DITULIS SENDIRI di .env, kosong kalau tidak ada.

        Urutan bawaannya dipaku di llm/rute.py TIER dan tidak bisa disetel dari
        UI — itu hasil pengujian, dan setelan yang bisa diputar sembarangan
        hanya menurunkan mutu klip tanpa ada yang tahu. Kolom ini tetap
        dihormati sebagai jalan keluar untuk yang memang tahu apa yang
        dilakukannya, dan supaya .env lama yang sudah mengisi GEMINI_MODEL
        tetap jalan tanpa disunting."""
        return self._pecah(self.GEMINI_MODELS) or self._pecah(self.GEMINI_MODEL)


settings = Settings()
