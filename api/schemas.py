from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.settings import settings


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    target_clips: int = Field(default=settings.TARGET_CLIPS_DEFAULT, ge=1, le=20)
    template_id: str
    adjustments: dict = Field(default_factory=dict)
    client_request_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _template_valid(self):
        from pipeline.templates import resolve

        self.adjustments = resolve(self.template_id, self.adjustments)
        return self

    @field_validator("url")
    @classmethod
    def _youtube_only(cls, v: str) -> str:
        v = v.strip()
        # Berkas yang sudah diunggah dirujuk sebagai "unggah:<uuid>". Bentuknya
        # dikunci ke UUID di unggah/ — bukan sekadar "bukan URL YouTube" —
        # karena nilai ini ikut menyusun path di disk. Yang lolos di sini TIDAK
        # PERNAH sampai ke yt-dlp: stage download bercabang lebih dulu.
        from unggah import sumber

        if sumber(v):
            return v

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
            raise ValueError(
                "Link harus dari YouTube (youtube.com atau youtu.be). "
                "Punya berkas videonya sendiri? Pakai tab Unggah berkas."
            )
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
    layout: str = "penuh"
    layout_fallback: bool = False


class JobOut(BaseModel):
    id: str
    url: str
    target_clips: int
    layout: str = "penuh"
    gaya: dict = {}
    template_id: str | None = None
    adjustments: dict = {}
    retryable: bool = False
    status: str
    progress: int
    error: str | None = None
    #: Kegagalan yang sudah diterjemahkan jadi kalimat yang bisa
    #: ditindaklanjuti: {"judul", "saran"}. Diturunkan dari `error`, bukan
    #: disimpan — job lama ikut mendapatkannya tanpa migrasi, dan teks mentahnya
    #: tetap utuh kalau terjemahannya ternyata meleset.
    masalah: dict | None = None
    clips: list[Clip] = []
    created_at: str | None = None
    updated_at: str | None = None
    queue_position: int | None = None
    queued_ahead: int | None = None
    worker_id: str | None = None

    @model_validator(mode="after")
    def _terjemahkan(self):
        from utils.pesan import terjemah

        if self.error and not self.masalah:
            self.masalah = terjemah(self.error)
        return self


class JobCreated(BaseModel):
    job_id: str
    status: str
