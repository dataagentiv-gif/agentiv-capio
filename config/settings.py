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

    # --- Transkrip (Stage 2) ---
    #
    # Default elevenlabs, dan ini keputusan yang diambil dari pengukuran, bukan
    # dari klaim vendor. Tiga video Indonesia berisi istilah Inggris ditranskrip
    # oleh kedua provider dari file audio yang sama persis:
    #
    #   - Pada satu dari tiga video, 29.6% keluaran Groq adalah TEKS JEPANG.
    #     Bukan salah dengar — Whisper berpindah bahasa lalu mengarang panjang
    #     lebar. Dua video lain nol. Jadi kegagalannya tidak merata, melainkan
    #     ambruk total tanpa peringatan, dan itu lebih sulit diantisipasi
    #     daripada kesalahan kecil yang konsisten.
    #   - Kalimat Inggris DITERJEMAHKAN, bukan ditranskrip: "Tools like Google
    #     Analytics" keluar sebagai "Tua seperti analitik".
    #
    # groq       : gratis dan 5-10x lebih cepat. Aman untuk konten Indonesia
    #              murni. MENOLAK IP datacenter dengan 403 — perhatikan kalau
    #              worker dijalankan di VPS.
    # elevenlabs : akurat, tanpa blokir IP, ada tier gratis. Mengeja angka
    #              ("seratus empat puluh empat"), tapi asr/angka.py sudah
    #              mengubahnya kembali jadi digit sebelum masuk caption.
    ASR_PROVIDER: str = "elevenlabs"  # groq | elevenlabs

    # Boleh lebih dari satu key dipisah koma, sama seperti Gemini — free tier
    # Groq dibatasi per key, jadi key yang dirotasi menaikkan atap tanpa biaya.
    GROQ_API_KEYS: str = ""
    # Nama lama, dipertahankan supaya .env yang sudah ada tetap jalan.
    GROQ_API_KEY: str = ""

    ELEVENLABS_API_KEYS: str = ""
    # Nama lama, dipertahankan supaya .env yang sudah ada tetap jalan.
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_MODEL: str = "scribe_v2"

    # Stage 3 (segment) dan Stage 8 (metadata) sama-sama lewat llm/, jadi ganti
    # provider atau model cukup ubah env var di sini — kode stage tidak disentuh.
    LLM_PROVIDER: str = "openrouter"  # openrouter | gemini

    OPENROUTER_API_KEYS: str = ""
    # Nama lama, dipertahankan supaya .env yang sudah ada tetap jalan.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash-lite"

    # Gemini dipanggil langsung (endpoint OpenAI-compatible milik Google), bukan
    # lewat OpenRouter. Boleh diisi lebih dari satu key dipisah koma: free tier
    # Gemini dibatasi PER KEY, jadi key yang dirotasi menaikkan atap tanpa biaya.
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

    # --- Tampilan klip (Stage 5 & 7) ---
    #
    # Layout dipilih UTUH, bukan dipreteli jadi setelan terpisah: posisi teks,
    # geometri kotak, dan arah gradien harus sepakat satu sama lain. Yang di
    # bawahnya adalah knob yang benar-benar berdiri sendiri — diputar
    # bagaimanapun tidak bisa menghasilkan kombinasi yang bertentangan.
    CLIP_LAYOUT: str = "penuh"  # penuh | kotak | samping | ori

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

    # --- Lisensi ---
    #
    # Key dimasukkan lewat halaman Setting, bukan dengan menyunting berkas ini.
    # Kosong = aplikasi tetap hidup normal, hanya submit job yang diblokir —
    # menolak start berarti halaman Setting tidak bisa dibuka dan key tidak
    # akan pernah bisa dimasukkan sama sekali.
    LICENSE_KEY: str = ""

    # Folder yang HARUS bertahan melewati update image. Bukan CLIPS_DIR (dikelola
    # pengguna) dan bukan WORK_DIR (disapu berkala): install_id yang hilang saat
    # update berarti slot perangkat baru diklaim tiap ganti versi, dan batas 1
    # atau 3 perangkat habis sendiri tanpa penggunanya berbuat apa-apa.
    DATA_DIR: Path = ROOT / "data"

    # VERSI ikut terkirim ke server lisensi sebagai agent_version dan tersimpan
    # di tabel activations — satu-satunya cara tahu versi berapa yang dipakai
    # client saat mereka melaporkan masalah. Naikkan bersamaan dengan tag image.
    VERSI: str = "1.1.0"
    AGENTIV_WA: str = "6285843570782"

    # Kosong = pakai alamat produksi yang tertulis di license/__init__.py.
    # Diisi hanya untuk staging atau pengujian dari mesin sendiri.
    LICENSE_SERVER: str = ""

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

    # --- Guardrail (PRD Bagian 6) ---
    JOB_TIMEOUT_SEC: int = 1800  # 30 menit untuk video referensi 1 jam
    MIN_CLIP_SEC: float = 30.0
    MAX_CLIP_SEC: float = 90.0
    TARGET_CLIPS_DEFAULT: int = 8

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

    # Bentuk jamak dulu, bentuk tunggal sebagai cadangan. Nama tunggal dibaca
    # supaya .env yang sudah ada tetap jalan tanpa harus disunting — termasuk
    # milik orang lain yang sudah memasang versi sebelumnya.
    @property
    def groq_keys(self) -> list[str]:
        return self._pecah(self.GROQ_API_KEYS) or self._pecah(self.GROQ_API_KEY)

    @property
    def elevenlabs_keys(self) -> list[str]:
        return self._pecah(self.ELEVENLABS_API_KEYS) or self._pecah(
            self.ELEVENLABS_API_KEY
        )

    @property
    def openrouter_keys(self) -> list[str]:
        return self._pecah(self.OPENROUTER_API_KEYS) or self._pecah(
            self.OPENROUTER_API_KEY
        )


settings = Settings()
