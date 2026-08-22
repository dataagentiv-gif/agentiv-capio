from pydantic import BaseModel, Field, field_validator

from config.settings import settings


class JobCreate(BaseModel):
    url: str
    target_clips: int = Field(default=settings.TARGET_CLIPS_DEFAULT, ge=1, le=20)

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
    status: str
    progress: int
    error: str | None = None
    clips: list[Clip] = []
    created_at: str | None = None
    updated_at: str | None = None


class JobCreated(BaseModel):
    job_id: str
    status: str
