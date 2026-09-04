from pydantic import BaseModel, Field, field_validator

from config.settings import settings


class JobCreate(BaseModel):
    url: str
    target_clips: int = Field(default=settings.TARGET_CLIPS_DEFAULT, ge=1, le=20)
    # Bentuk tampilan dipilih di sini, bukan di halaman Setting: tiap video
    # bisa menuntut bentuk yang berbeda, dan keputusannya diambil saat menempel
    # link. Kosong = ikut default yang dipilih di Setting.
    layout: str | None = None
    # Knob tampilan untuk video INI. Kosong = ikut default di halaman Setting.
    gaya: dict | None = None

    @field_validator("gaya")
    @classmethod
    def _gaya_bersih(cls, v):
        """Batas kepercayaan: isinya masuk ke generator .ass dan ikut tersimpan
        di database. Hanya kunci yang dikenal yang lolos — sisanya dibuang
        diam-diam, bukan ditolak, supaya form versi lama tetap bisa submit."""
        if not v:
            return None
        BOLEH = {"font", "ukuran", "aktif", "kata", "upper"}
        bersih = {k: v[k] for k in BOLEH if v.get(k) not in (None, "", 0, "0")}
        # `caption` disaring terpisah, dan itu bukan gaya-gayaan: ia satu-satunya
        # knob yang nilai bermaknanya False, sementara `False == 0` di Python
        # membuat saringan di atas MEMBUANGNYA justru saat caption dimatikan.
        # Hanya False yang disimpan — tidak adanya kunci berarti nyala.
        if v.get("caption") is False or str(v.get("caption")).lower() in ("false", "0"):
            bersih["caption"] = False
        return bersih or None

    @field_validator("layout")
    @classmethod
    def _layout_dikenal(cls, v):
        if v is None or v == "":
            return None
        from pipeline.layout import LAYOUTS

        if v not in LAYOUTS:
            raise ValueError(f"Layout '{v}' tidak dikenal")
        return v

    @field_validator("url")
    @classmethod
    def _youtube_only(cls, v: str) -> str:
        v = v.strip()
        # Batas kepercayaan: yang masuk sini langsung jadi argumen subprocess
        # yt-dlp. Dibatasi ke host YouTube supaya field ini tidak bisa dipakai
        # menyuruh yt-dlp mengambil URL sembarangan.
        if not any(
            v.startswith(p)
            for p in (
                "https://www.youtube.com/",
                "https://youtube.com/",
                "https://m.youtube.com/",
                "https://youtu.be/",
            )
        ):
            raise ValueError("URL harus link YouTube (youtube.com atau youtu.be)")
        return v


class Clip(BaseModel):
    id: str
    url: str
    duration: float
    score: int
    hook: str
    reason: str
    title: str
    caption: str
    hashtags: list[str]


class JobOut(BaseModel):
    id: str
    url: str
    target_clips: int
    layout: str = "penuh"
    gaya: dict = {}
    status: str
    progress: int
    error: str | None = None
    clips: list[Clip] = []
    created_at: str | None = None
    updated_at: str | None = None


class JobCreated(BaseModel):
    job_id: str
    status: str
