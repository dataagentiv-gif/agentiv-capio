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

    # --- Kredensial eksternal ---
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    # Stage 3 (segment) dan Stage 8 (metadata) sama-sama lewat llm/client.py, jadi
    # ganti model cukup ubah satu env var ini — tidak menyentuh kode stage.
    OPENROUTER_MODEL: str = "google/gemini-2.5-flash-lite"

    DATABASE_URL: str = "postgresql+psycopg://clipper:clipper@localhost:5432/clipper"
    REDIS_URL: str = "redis://localhost:6379/0"

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
    def r2_endpoint(self) -> str:
        return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


settings = Settings()
