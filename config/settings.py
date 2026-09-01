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
    # groq       : murah ($0.04/jam) dan sangat cepat, tapi meleset di campuran
    #              Indonesia-Inggris dan MENOLAK IP datacenter dengan 403 —
    #              perhatikan ini kalau worker nanti dijalankan di VPS.
    # elevenlabs : jauh lebih akurat untuk Bahasa Indonesia (~2.4% vs ~7.7% WER),
    #              $0.22/jam, tanpa blokir IP.
    ASR_PROVIDER: str = "groq"  # groq | elevenlabs

    GROQ_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_MODEL: str = "scribe_v2"

    # Stage 3 (segment) dan Stage 8 (metadata) sama-sama lewat llm/, jadi ganti
    # provider atau model cukup ubah env var di sini — kode stage tidak disentuh.
    LLM_PROVIDER: str = "openrouter"  # openrouter | gemini

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash-lite"

    # Gemini dipanggil langsung (endpoint OpenAI-compatible milik Google), bukan
    # lewat OpenRouter. Boleh diisi lebih dari satu key dipisah koma: free tier
    # Gemini dibatasi PER KEY, jadi key yang dirotasi menaikkan atap tanpa biaya.
    GEMINI_API_KEYS: str = ""  # "key1,key2,key3"
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

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
        return self.API_HOST not in ("127.0.0.1", "localhost", "::1")

    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    # Domain publik bucket (custom domain atau r2.dev). Dipakai menyusun url klip
    # yang disimpan ke Postgres dan ditampilkan di history.html.
    R2_PUBLIC_BASE_URL: str = ""

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

    @property
    def gemini_keys(self) -> list[str]:
        """Key Gemini sebagai list. Entri kosong dan spasi sisa copy-paste
        dibuang, supaya "key1, key2," tidak menghasilkan key kosong yang
        dikirim ke API dan balik 400.
        """
        return [k.strip() for k in self.GEMINI_API_KEYS.split(",") if k.strip()]

    @property
    def r2_endpoint(self) -> str:
        return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


settings = Settings()
